# -*- coding: utf-8 -*-
"""Intership_AIRLab.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1qciQv_LTl1QgytVN5ipfb5Dh9eWzMXVg

# Import Section
"""

! pip install tensorpac
! pip install lempel_ziv_complexity
! pip install ordpy
! pip install -U mne-connectivity

#import mne
import scipy.io
import numpy.matlib
import math
import cmath
import numpy as np
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import mne.viz
import mne_connectivity
from scipy import stats
from scipy import signal
from scipy.signal import hilbert
from networkx.algorithms.shortest_paths import weighted
from itertools import permutations
from tensorpac import Pac
from tensorpac.signals import pac_signals_wavelet
from tensorpac.utils import PSD
from lempel_ziv_complexity import lempel_ziv_complexity
from ordpy import permutation_entropy
from mne_connectivity import spectral_connectivity_epochs
from google.colab import files
from scipy.interpolate import interp1d
from statsmodels import robust
from mne.preprocessing import ICA
from mne.time_frequency import AverageTFR
import matplotlib.cm as cm
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, PathPatch

# loading EEG.set File & Channel_location

uploaded = files.upload()
load = scipy.io.loadmat('loc_channel.mat')
loc_channel = load['loc_channel']

uploaded = files.upload()
load = scipy.io.loadmat('raw_EEG_event.set')
data_load = load['data']

uploaded = files.upload()
load = scipy.io.loadmat('trigger.mat')
event = load['event']

# read file by mne

path = 'raw_EEG_event.set'
raw = mne.io.read_raw_eeglab(path)

#Channel data

data, times = raw[:]

data.shape

"""# PreProcessing"""

#Normalization (Z_score)

data = stats.zscore(data,axis=0)

#Filtering

raw.load_data()

#Notch Filter

fs = 500
f0 = 50
bandwidth = 0.5;
Q = f0/bandwidth;
# Design notch filter
b, a = signal.iirnotch(f0, Q, fs)
data = scipy.signal.filtfilt(b, a, data)

def design_fir(N,F,A,nfft,W):

  #if len(signature(design_fir).parameters) < 4 or len(nfft)==0:
  if nfft == None and W== None:
    nfft = max(512,np.power(2,math.ceil(np.log(N)/np.log(2))))

  #if len(signature(design_fir).parameters) < 5:
  elif W == None:
    W = 0.54 - 0.46*np.cos(2*np.pi*np.arange(0,N+1)/N)

  # calculate interpolated frequency response
  F = interp1d(np.round_(F*nfft),A,kind='cubic')(np.arange(0,nfft))

  # set phase & transform into time domain
  F = F * np.exp(-(0.5*N)*cmath.sqrt(-1)*np.pi*np.arange(0,nfft)/nfft)
  B = (np.fft.ifft(np.concatenate((F, np.conj(F[-2:0:-1])), axis=0))).real

  # apply window to kernel
  B = B[1:N+2]*W[:].T


  return B

def filtfilt_fast(*args):
  
  B, A, X = args

  w = len(B) 
  t = X.shape[0] 

  # extrapolate
  a1 = 2*X[0]-X[1+np.mod(np.arange(w+1,1,-1)-1,t)-1]
  a2 = X  ############## the order of data is not correct. It's ordert 1e-05 but It has to be 1e+1 (the digit is compeletly true) ####????????????
  a3 = 2*X[t-1]-X[1+np.mod(np.arange((t-1),(t-w-1),-1)-1,t)-1]
  X = np.concatenate((a1, a2, a3), axis=0)  #################### result is diffrent with matlab ###################################???????????????


  # filter, reverse
  X = scipy.signal.lfilter(B,A,X)
  X = X[np.arange(len(X)-1,-1,-1)]

  # filter, reverse
  X = scipy.signal.lfilter(B,A,X)
  X = X[np.arange(len(X)-1,-1,-1)]

  # remove extrapolated pieces
  b1 = np.array([np.arange(1,w+1)])
  b2 = np.array([t+w+np.arange(1,w+1)])
  bb = np.concatenate((b1, b2), axis=1)
  X = np.array([X])
  X = np.delete(X,bb-1)


  return X

# clean_rawdata()
# Notice: I have to define loc_channel before this func

def find_bad_channels(data,loc_channel,max_allowed_jitter,max_flatline_duration,srate,noise_threshold,num_samples,subset_size,corr_threshold,window_len):
  
  nbchan , timechan = data.shape

  x = loc_channel[0].tolist()
  y = loc_channel[1].tolist()
  z = loc_channel[2].tolist()

  removed_channels = np.zeros((1,nbchan))

  eps = 1e-10 

#### Remove Bad Channel 
# Find flat channel
  for c in range(nbchan):
     compar = np.absolute(np.diff(data[c,:])) < (max_allowed_jitter*eps)
     zero_intervals = np.reshape(np.where(np.diff(np.append(np.append(0,compar),0))!=0),(-1,2))
     
     if zero_intervals.size != 0:
        if np.max(zero_intervals[:,1] - zero_intervals[:,0]) > max_flatline_duration*srate:
           removed_channels[0,c] = 1



# Max acceptable high-frequency noise std dev
  X = np.zeros((timechan,nbchan))
  if srate > 100:
    # remove signal content above 50Hz
    B = design_fir(100,np.concatenate((2*np.array([0, 45, 50])/srate, [1]), axis=0),np.array([1,1,0,0]),None,None) # I change its input
    for c in np.arange(nbchan-1,0,-1):
      X[:,c] = filtfilt_fast(B,1,data[c,:].T)

    # determine z-scored level of EM noise-to-signal ratio for each channel
    noisiness = (pd.DataFrame(data.T-X).mad(axis=0).to_numpy()) / (robust.mad(X, c=1,  axis=0))
    znoise = (noisiness - np.median(noisiness,axis=0)) / (robust.mad(noisiness, c=1,  axis=0)*1.4826)

    # trim channels based on that
    noise_mask = znoise > noise_threshold;

  else:
    X = data.T
    noise_mask = np.zeros((nbchan,1)).T


# Min acceptable correlation between nearby channel
# set the window
  window_len = window_len*srate
  wnd = np.arange(0,window_len-1)
  offsets = np.arange(1,window_len,timechan-window_len)
  W = len(offsets)

# get the matrix of all channel locations
  usable_channels = np.asarray(np.where((np.array(np.invert([i is None for i in x])) & np.array(np.invert([i is None for i in y])) & np.array(np.invert([i is None for i in z])))!=0))
  locs = np.squeeze(np.array([x[usable_channels],y[usable_channels],z[usable_channels]]))
  X = X[:,usable_channels]

# caculate all-channel reconstruction matrices from random channel subsets
  P = calc_projector(locs,num_samples,subset_size)

  
  corrs = np.zeros((len(usable_channels),W))


# calculate each channel's correlation to its RANSAC reconstruction for each window
  for o in range(W):
    XX = X[offsets[o]+wnd,:]
    YY = np.sort(np.reshape(np.dot(XX,P),len(wnd),len(usable_channels),num_samples),2)
    YY = YY[:,:,np.round_(YY.shape[2]/2)]
    corrs[:,o] = np.sum(XX*YY)/(np.sqrt(np.sum(XX**2))*np.sqrt(np.sum(YY**2)))

  flagged = corrs < corr_threshold


#### Artifact Subspace Reconstruction



  
#remove channel for this part and concider special condition


  return removed_channels

max_allowed_jitter = 20 #default
max_flatline_duration = 5 #default
srate = 500
noise_threshold = 0.4 #default
window_len = 5 #default
corr_threshold = 0.8 #default
num_samples = 50;
subset_size = 0.25; 

find_bad_channels(data,loc_channel,max_allowed_jitter,max_flatline_duration,srate,noise_threshold,num_samples,subset_size,corr_threshold,window_len)



## Notice: before this step, convert clean data to raw 
# Run ICA and plot componnet(optional)

def ica_func(raw):
  ica = ICA(n_components=data.shape[0] , max_iter='auto')
  ica.fit(raw)
  ica.apply(raw)

  ica.plot_components()
  
  ica

  return raw

ica_func(raw)



# epoch data and plot 

def epoch_func(raw):
  events, event_id = mne.events_from_annotations(raw)
  epochs = mne.Epochs(raw, events, event_id, preload=True)
  #epochs.plot()

  return epochs

epochs = epoch_func(raw)



#### convert epochs to data and continue processing

## data: num_channel*time*num_epoch

data = epochs.get_data()
s = data.shape
data = np.reshape(data,(s[1],s[2],s[0]))



"""# Visualization

Adjency Matrix Plot
"""

def adjency_plot(feature):
  
  feature_avg = np.mean(feature,axis=2)

  # Make it symmetric
  n = int(feature_avg.shape[:1][0])
  i_lower = np.tril_indices(n, n)
  c2 = feature_avg.copy()
  c2[i_lower] = feature_avg.T[i_lower]
  feature_avg = c2 + feature_avg
  
  plt.figure
  plt.imshow(feature_avg)
  plt.colorbar() 
  plt.show()

  return

"""Over Frequency Plot"""

def plot_over_freq(con,channel,freqs):
    
    #si = 0
    #sj = 0
    
    fig, axes = plt.subplots(len(channel), len(channel), sharex=True, sharey=True)
    feature = con.get_data(output='dense')
    freqs = con.freqs
    
    for i in range(len(channel)): 
        for j in range(i+1):
            if i == j:
                axes[i, j].set_axis_off()
                continue

            axes[i, j].plot(freqs, feature[channel[i],channel[j], :])
            axes[j, i].plot(freqs, feature[channel[i],channel[j], :])

            if j == 0:
              axes[i, j].set_ylabel(i)
            
            if i == (i-1):
              axes[i, j].set_xlabel(j)

            axes[i, j].set(xlim=[1, 100], ylim=[-0.2, 1])
            axes[j, i].set(xlim=[1, 100], ylim=[-0.2, 1])

        # Show band limits
            for f in [4, 8, 14, 30]:
                axes[i, j].axvline(f, color='k')
                axes[j, i].axvline(f, color='k')

            #sj += 1
        #si += 1    
    plt.tight_layout()
    plt.show()
      

    return

"""time-frequency"""

def time_freq_connectivity(epochs, feature, times, freqs):
  plt.figure()
  tfr = AverageTFR(epochs.info, feature, times, freqs, len(epochs))
  tfr.plot_topo(fig_facecolor='w', font_color='k', border='k')
  plt.show()
  return

"""graph"""

def brain_graph(feature,loc_channel):
  fig, ax = plt.subplots(figsize=(6, 6))

  for i in range(loc_channel.shape[1]):
      circle = Circle(loc_channel[0:2,i]*7,1,linewidth=3, alpha=0.5)
      ax.add_patch(circle)

      print(feature[i])

      im = plt.imshow(np.array([feature[i,:]]).T,
                origin='upper', cmap='jet',
                interpolation='spline36',
                extent=([-10, 10, -10, 10]))
      im.set_clip_path(circle)
  plt.colorbar()

  for i in range(19):
       plt.scatter(loc_channel[0:2,i][0]*7, loc_channel[0:2,i][1]*7,c = 'black', linewidths=0.01)
  plt.show()

  return

""" # Graph Analysis"""

def clustering_func(G):

    node_clu = nx.clustering(G, G.nodes, weight = 'weight')
    node_weight_cluster = np.array(list(node_clu.values()))

    node_clu = nx.clustering(G, G.nodes)
    node_cluster = np.array(list(node_clu.values()))
    
    return node_weight_cluster, node_cluster

def  efficiency_func(G):

    n = len(G)
    denom = n * (n - 1)
    sp = np.zeros((n,n))

    if denom != 0:
        shortest_paths = dict(nx.all_pairs_dijkstra(G, weight = 'weight'))
        for u, v in permutations(G, 2):
            if shortest_paths[u][0][v] != 0:
                sp[u,v] = sp[u,v] + 1/shortest_paths[u][0][v]
            else:
                sp[u,v] = sp[u,v]
    
        weighted_global_efficiency = sp/ denom/2
    
    else:
        weighted_global_efficiency = 0
    
    return weighted_global_efficiency

def centrality_func(G):

    ce = np.array(list(nx.closeness_centrality(G, distance= 'weight').values()))

    be = np.array(list(nx.betweenness_centrality(G, normalized=True, weight = 'weight').values()))
    
    return ce, be

def creat_graph(node_num,edge_weigth):
    G = nx.Graph()
    points = range(edge_weigth.shape[0])
    G.add_nodes_from(points)
    
    for i in points:
        for j in range(i+1, len(points)):
            G.add_edge(i,j,weight=abs(edge_weigth[i,j]))
    
    node_weight_cluster, node_cluster = clustering_func(G)
    weighted_global_efficiency = efficiency_func(G)
    closeness_centrality, betweenness_centrality = centrality_func(G)
    
    return node_weight_cluster, node_cluster, weighted_global_efficiency, closeness_centrality, betweenness_centrality

"""#Computation

Coherence, Imaginary coherence, Phase-Locking Value, Phase Lag Index (mne_package)
"""

def mne_pack(data,args):
    method = args['method']
    sfreq = args['sample_freq']
    if 'mode' in args:
        mode = args['mode']
    else: 
        mode = 'multitaper'
        
    fmin = 0 

    if method == 'Coherence':
      method = 'coh'
    elif method == 'Imaginary coherence':
      method = 'imcoh'
    elif method == 'Phase-Locking Value':
      method = 'plv'
    elif method == 'Phase Lag Index':
      method = 'pli'
    elif method == 'weighted_pli':
      method = 'wpli2_debiased'

    if mode == 'cwt_morlet':
      con = spectral_connectivity_epochs(data,method='wpli2_debiased', mode= 'cwt_morlet', sfreq=sfreq,
                                           cwt_freqs=args['cwt_freqs'], cwt_n_cycles=args['cwt_n_cycles'], n_jobs=1)
    else:
      con = mne_connectivity.spectral_connectivity_epochs(data, method=method, mode=mode, sfreq=sfreq, fmin= fmin)
    
    
    return con

"""Phase Amplitude Coupling """

def Pase_Amplitude_coupling_func(data,args):
    """Compute Phase-Amplitude Coupling (PAC).

    Computing PAC is assessed in three steps : compute the real PAC, compute
    surrogates and finally, because PAC is very sensible to the noise, correct
    the real PAC by the surrogates. This implementation is modular i.e. it lets
    you choose among a large range of possible combinations.

    Parameters
    ----------
    idpac : tuple/list | (1, 1, 3)
        Choose the combination of methods to use in order to extract PAC.
        This tuple must be composed of three integers where each one them
        refer

        * First digit : refer to the pac method

            - 1 : Mean Vector Length (MVL) :cite:`canolty2006high`
              (see :func:`tensorpac.methods.mean_vector_length`)
            - 2 : Modulation Index (MI) :cite:`tort2010measuring`
              (see :func:`tensorpac.methods.modulation_index`)
            - 3 : Heights Ratio (HR) :cite:`lakatos2005oscillatory`
              (see :func:`tensorpac.methods.heights_ratio`)
            - 4 : ndPAC :cite:`ozkurt2012statistically`
              (see :func:`tensorpac.methods.norm_direct_pac`)
            - 5 : Phase-Locking Value (PLV)
              :cite:`penny2008testing,lachaux1999measuring`
              (see :func:`tensorpac.methods.phase_locking_value`)
            - 6 : Gaussian Copula PAC (GCPAC) :cite:`ince2017statistical`
              (see :func:`tensorpac.methods.gauss_cop_pac`)

        * Second digit : refer to the method for computing surrogates

            - 0 : No surrogates
            - 1 : Swap phase / amplitude across trials
              :cite:`tort2010measuring`
              (see :func:`tensorpac.methods.swap_pha_amp`)
            - 2 : Swap amplitude time blocks
              :cite:`bahramisharif2013propagating`
              (see :func:`tensorpac.methods.swap_blocks`)
            - 3 : Time lag :cite:`canolty2006high`
              (see :func:`tensorpac.methods.time_lag`)

        * Third digit : refer to the normalization method for correction

            - 0 : No normalization
            - 1 : Substract the mean of surrogates
            - 2 : Divide by the mean of surrogates
            - 3 : Substract then divide by the mean of surrogates
            - 4 : Z-score

    f_pha, f_amp : list/tuple/array | def: [2, 4] and [60, 200]
        Frequency vector for the phase and amplitude. Here you can use
        several forms to define those vectors :

            * Basic list/tuple (ex: [2, 4] or [8, 12]...)
            * List of frequency bands (ex: [[2, 4], [5, 7]]...)
            * Dynamic definition : (start, stop, width, step)
            * Range definition (ex : np.arange(3) => [[0, 1], [1, 2]])
            * Using a string. `f_pha` and `f_amp` can be 'lres', 'mres', 'hres'
              respectively for low, middle and high resolution vectors. In that
              case, it uses the definition proposed by Bahramisharif et al.
              2013 :cite:`bahramisharif2013propagating` i.e
              f_pha = [f - f / 4, f + f / 4] and f_amp = [f - f / 8, f + f / 8]

    dcomplex : {'wavelet', 'hilbert'}
        Method for the complex definition. Use either 'hilbert' or
        'wavelet'.
    cycle : tuple | (3, 6)
        Control the number of cycles for filtering (only if dcomplex is
        'hilbert'). Should be a tuple of integers where the first one
        refers to the number of cycles for the phase and the second for the
        amplitude :cite:`bahramisharif2013propagating`.
    width : int | 7
        Width of the Morlet's wavelet.
    n_bins : int | 18
        Number of bins for the KLD and HR PAC method
    """
    
    sfreq = args['sample_freq']

    p = Pac(f_pha='hres', f_amp='hres', dcomplex='wavelet')
    phases = p.filter(sfreq, data, ftype='phase', n_jobs=1)
    amplitudes = p.filter(sfreq, data, ftype='amplitude', n_jobs=1)
    
    plt.figure(figsize=(14, 8))
    for i, k in enumerate([1, 2, 3, 4, 5, 6]):
        #p = Pac(f_pha='hres', f_amp='hres', dcomplex='wavelet')
      # switch method of PAC
        #for i in range(data.shape[1]):
        if k == 1:
              p.idpac = (1,2,4)
        else:
              p.idpac = (k, 0, 0)
        #phases = p.filter(sfreq, data, ftype='phase', n_jobs=1)
        #amplitudes = p.filter(sfreq, data, ftype='amplitude', n_jobs=1)
            # compute only the pac without filtering
            #if i == 0:
             # xpac = np.zeros((phases.shape[0],phases.shape[0],phases.shape[1]))
            #else:
              #xpac += p.fit(phases, amplitudes)
      # plot
        xpac = p.fit(phases, amplitudes)
        #xpac = xpac/data.shape[1]
        plt.subplot(2, 3, k)
        title = p.method.replace(' (', f' ({k})\n(')
        p.comodulogram(xpac.mean(-1), title=title, cmap='viridis')
        if k <= 3:
           plt.xlabel('')

    plt.tight_layout()
    plt.show()
    
    return

"""# Main Function (Functional Connectivity)"""

def Functional_connectivit(data,loc_channel,args):
    
### data : n_channels*n_times*n_epochs

    method = args['method']
    sfreq = args['sample_freq']
    
    if 'mode' in args:
        mode = args['mode']
    else: 
        mode = 'multitaper'

    if 'channel_labeled' in args:
        channel_labeled = args['channel_labeled']
    else: 
        channel_labeled = [1,2,3]

    # Filtering
    if 'filter_freq' in args:
        filter_freq = args['filter_freq']
        filter_order = args['filter_order']
        filter_type = args['filter_type']
        b, a = signal.butter(filter_order, filter_freq, filter_type)
        data = signal.filtfilt(b, a, data)
    
    # Feature Function
    if method == 'Coherence' or method == 'Imaginary coherence' or method == 'Phase-Locking Value' or method == 'Phase Lag Index' or method == 'weighted_pli':
        args['mode'] = mode
        con = mne_pack(data,args)
        feature = con.get_data(output='dense')
    if method == 'Pase_Amplitude_coupling':
        for i in args['channel_labeled']:
             Pase_Amplitude_coupling_func(epochs.get_data()[:,i,:],args)
        return

        
        
    # Output demonstration 
    if 'plot_methode' in args:
      plot_methode = args['plot_methode']   
      if plot_methode == 'adjency_matrix':
           adjency_plot(feature)
      if plot_methode == 'plot_over_freq': 
           plot_over_freq(con,channel_labeled,con.freqs)
      if plot_methode == 'time_freq_connectivity':
           times = con.times
           freqs = con.freqs
           feature = np.mean(con.get_data(output='dense'), axis=0)
           time_freq_connectivity(data, feature, times, freqs)
      if plot_methode == 'brain_graph':
           print(feature.shape)
           feature = np.mean(feature,axis=2)
           brain_graph(feature,loc_channel)
    else:
      return feature
    
        
        
    return

"""#*Some Example*"""

#sample 1

args = {'method':'Imaginary coherence','sample_freq':500,'plot_methode':'adjency_matrix'}
Functional_connectivit(epochs.get_data(),loc_channel,args)

#sample 2

args = {'method':'Phase-Locking Value','sample_freq':500,'plot_methode':'plot_over_freq','channel_labeled':np.arange(5)}
Functional_connectivit(epochs.get_data(),loc_channel,args)

#sample 3

cwt_freqs = np.arange(7, 30, 2)
cwt_n_cycles = cwt_freqs / 7.

args = {'method':'weighted_pli','sample_freq':500,'plot_methode':'time_freq_connectivity',
        'mode':'cwt_morlet','cwt_freqs':cwt_freqs,'cwt_n_cycles':cwt_n_cycles}
Functional_connectivit(epochs,loc_channel,args)

#sample 4

args = {'method':'Pase_Amplitude_coupling','sample_freq':500,'channel_labeled':np.array([10])}
Functional_connectivit(epochs.get_data(),loc_channel,args)

#sample 5

args = {'method':'Phase-Locking Value','sample_freq':500,'plot_methode':'brain_graph'}
Functional_connectivit(epochs.get_data(),loc_channel,args)

#sample 6

args = {'method':'Coherence','sample_freq':500}
feature = Functional_connectivit(epochs.get_data(),loc_channel,args)


feature_avg = np.mean(feature,axis=2)
# Make it symmetric
n = int(feature_avg.shape[:1][0])
i_lower = np.tril_indices(n, n)
c2 = feature_avg.copy()
c2[i_lower] = feature_avg.T[i_lower]
feature_avg = c2 + feature_avg


node_weight_cluster, node_cluster, global_efficiency, closeness_centrality, betweenness_centrality = creat_graph(192,feature_avg)
global_efficiency = np.mean(global_efficiency,axis=0)

cm = plt.cm.get_cmap('RdYlBu')
plt.scatter(loc_channel[0,:],loc_channel[1,:],c=closeness_centrality,cmap=cm)
plt.colorbar()
plt.show()