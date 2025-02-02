import numpy as np
import os
from pylab import *
import torch 

from fastai.data.core import DataLoaders
import re
import random
from fastai.vision.all import *
from glob import glob

AUDIODIR = '/media/nfarrugi/datapal/narratives/stimuli'
FMRIDIR = '/media/nfarrugi/datapal/narratives/parcellated'

class RPSampler(torch.utils.data.sampler.Sampler):
    r"""Pour chaque subject sample n windows de sorte à avoir un dataset équilibré en 
    terme de subject. `weights` permet de controler la proportion des negative samples.

    Arguments:
    ---------
        dataset (Dataset): dataset to sample from
        size (int): The total number of sequences to sample
    returns:
        a tuple (t,target,subject) such as :
        - The anchor window starts at index t in the fmri recording.
        - The target is the class associeted to the pretexe task (eithre -1 or 1)
    """

    def __init__(self,dataset, batch_size,size,  weights):
    
        
        self.batch_size = batch_size
        self.size = size
        self.dataset = dataset
        self.serie_len = 0
        self.n_subjects = len(self.dataset.subjects)
        self.weights = torch.DoubleTensor(weights)
        self.f = self.dataset.f # fin de la serie temporelle
        self.d = self.dataset.d
        self.tr = self.dataset.tr
        
    def __iter__(self):
        num_batches = self.size// self.batch_size
        n_subject_samples = self.batch_size //self.n_subjects
        while num_batches > 0:
            if num_batches % 100 == 0 :
                print("batches restants :",num_batches)
            #iterate on each subject in the dataset
            for subject in self.dataset.subjects:
                sampled = 0
                #sample `n_subject_samples` per subject
                while sampled < n_subject_samples:
                  
                    # each sample is a target and an anchor window. Positive or/and negative windows are sampled in the Dataset class. 
                    target  = 2*torch.multinomial(
                self.weights, 1, replacement=True) -1
                    t = np.random.rand() if isinstance(self.dataset, RP_Dataset_Multi) else choice(arange(self.d, self.f-int(self.dataset.w/self.tr), 1))
                    sampled += 1
                    yield (t,target,subject)
            
            num_batches -=1

    def __len__(self):
        return self.size  

#@title Relative positioning class
T = 947
class Abstract_Dataset(torch.utils.data.Dataset):
    '''
    Classe dataset  pour les differents sampling
    '''
    def __init__(self, subjects, wind_len , n_features, T = 947):
        self.subjects = subjects
        self.time_series = []
        self.w = wind_len
        self.n = n_features
        self.T = T
    def get_windows(self,index):
        '''
        a method to load  a sequence 
        '''
        raise NotImplementedError
    def get_pos(self, t_anchor):
        '''
        a method to get positive samples
        '''
        raise NotImplementedError
    def load_ts(self, index):
        '''
        a method to get positive samples
        '''
        raise NotImplementedError
    def get_neg(self, t_anchor):
        '''
       a method to get negative samples
        '''
        raise NotImplementedError
    def get_targets(self, index):
        '''
        a method to get labels
        '''
        raise NotImplementedError
    def __getitem__(self, index):
        windows = self.get_windows(index)
        target = self.get_targets(index)
        return windows, target
    def __len__(self): return self.T

class RP_Dataset(Abstract_Dataset):
    r"""Pour chaque subject sample n windows de sorte à avoir un dataset équilibré en 
    terme de subject. `weights` permet de controler la proportion des negative samples.

    Arguments:
    ---------
        subjects (List): list of subjects  to use during training
        sampling_params (tuple(int,int)): positive and negative sampling windows
        wind_len (int): Windows lenght
        debut(int): Starting indice of the considered time series.
    """
    def __init__(self, subjects, sampling_params, wind_len , debut = 0, fin = 946, dry_run = False, tr=1.5 ):
        
        super().__init__(subjects, wind_len = wind_len, n_features = 3)
        self.tr = tr
        self.audio, self.sr = self.load_audio()
        self.pos , self.neg = sampling_params[0]*self.sr, sampling_params[1]*self.sr
        self.d, self.f = debut, fin #in tr
        self.d_audio , self.f_audio = int(self.d*self.tr*self.sr), int(self.f*self.tr*self.sr)
        self.dry_run = dry_run
    def get_windows(self,index):
        '''
        a method to get sampled windows
        '''
        #fmri index
        (t, target,subject) = index
        # sample a positive or negative audio index
        t_ = self.get_pos(t) if target>0 else self.get_neg(t)
        if self.dry_run:
            return (t, t_)
        #load fmri data
        fmri =self.load_fmri(subject)
        # slice 
        fmri_w = fmri[t:t+int(self.w/self.tr)] # fmri index*TR -->seconds
        # sample a positive or negative audio window
        audio_w = self.audio[t_:t_+self.w*self.sr] # could be negative or positive
        return (fmri_w, audio_w)
    
    def load_audio(self):
        return np.load( os.path.join(AUDIODIR, 'sherlock.npy'),mmap_mode = "c" ), 22050
    def load_fmri(self, subject):
        path_= os.path.join(FMRIDIR, f"sub_{subject}.npy")
        return np.load(path_,mmap_mode = "c")
    def get_targets(self, index):
        return (index[1]>0.5)*1
    def get_pos(self, t_anchor):
        w = self.w*self.sr #frmi  to audio window lenght
        t = int(t_anchor*self.tr*self.sr) #frmi indice to audio
        start = max(self.d_audio,t-self.pos ) 
        end = min(self.f_audio - w-1,t+self.pos) # to get a sequence of lenght self.w
        t_ = choice(arange(start,end, 1)) 
        return t_
    def get_neg(self, t_anchor):
        w = self.w*self.sr
        t = int(t_anchor*self.tr*self.sr)
        left_idx = arange(self.d_audio, max(self.d_audio, t - self.neg), 1)
        right_idx =arange(min(self.f_audio-w-1, t + self.neg-1),self.f_audio-w-1 ,1)
        t_ = choice(hstack([left_idx, right_idx])) # 
        return t_

def ssl_collate(batch):
    anchors = torch.stack([torch.from_numpy(item[0][0]) for item in batch])
    try:
        sampled = torch.stack([torch.from_numpy(item[0][1]) for item in batch])
    except:
        print("error")
    targets = torch.stack([item[1] for item in batch])
    
    return (anchors, sampled), targets

class RP_Dataset_Multi(Abstract_Dataset):
    r"""Pour chaque subject sample n windows de sorte à avoir un dataset équilibré en 
    terme de subject. `weights` permet de controler la proportion des negative samples.

    Arguments:
    ---------
        subjects (List): list of subjects  to use during training
        sampling_params (tuple(int,int)): positive and negative sampling windows
        wind_len (int): Windows lenght
        debut(int): Starting indice of the considered time series.
    """
    def __init__(self, subjects, sampling_params, wind_len , debut = 0, fin = 946, dry_run = False,sr = 22050, tr=1.5 ):
        
        super().__init__(subjects, wind_len = wind_len, n_features = 3)
        self.tr = tr
        self.sr = sr
        self.pos , self.neg = sampling_params[0]*self.sr, sampling_params[1]*self.sr
        with open('mapping.json', 'r') as f : self.sub2stims = json.load(f)
        self.d, self.f = debut, fin #in tr
        self.d_audio , self.f_audio = int(self.d*self.tr*self.sr), int(self.f*self.tr*self.sr)
        self.dry_run = dry_run
    def get_windows(self,index):
        '''
        a method to get sampled windows
        '''
        #fmri index
        (t, target,subject) = index
        # select a stim
        stim = self.select_stimuli(subject)
        #load fmri data
        fmri =self.load_fmri(subject, stim)
        #define sampling intervals
        self.f = fmri.shape[0]
        self.d_audio , self.f_audio = int(self.d*self.tr*self.sr), int(self.f*self.tr*self.sr)
        #rescale t
        end, start =  self.f-int(self.w/self.tr), self.d
        t = int(t*(end-start +1) + start)
        # slice 
        fmri_w = fmri[t:t+int(self.w/self.tr)] # fmri index*TR -->seconds
        # sample a positive or negative audio index
        t_ = self.get_pos(t) if target>0 else self.get_neg(t)
        if self.dry_run:
            return (t, t_)
        # load audio
        audio = self.load_audio( subject, stim)
        # sample a positive or negative audio window
        audio_w = audio[t_:t_+self.w*self.sr] # could be negative or positive
        if audio_w.shape[0] ==0:
            print(stim , t,t_  ,audio_w.shape, fmri_w.shape)
        return (fmri_w, audio_w)
    def select_stimuli(self,subject):
        # find all available  stimuli
        stims = self.sub2stims[subject]
        # select a stim randomly
        return stims[0]#choice(stims)
    def load_audio(self, subject, stim):
        stim_path = os.path.join(STIMS_DIR, f'{stim}_audio.npy')
        return np.load( stim_path,mmap_mode = "c" )#, 22050
    def load_fmri(self ,subject ,stim ):
        path_= os.path.join(FMRIDIR,  f'sub-{subject}_task-{stim}_space-MNI152NLin2009cAsymres-native.npz')
        return np.load(path_,mmap_mode = "c")['X']
    def get_targets(self, index):
        return (index[1]>0.5)*1
    def get_pos(self, t_anchor):
        w = self.w*self.sr #frmi  to audio window lenght
        t = int(t_anchor*self.tr*self.sr) #frmi indice to audio
        start = max(self.d_audio,t-self.pos ) 
        end = min(self.f_audio - w-1,t+self.pos) # to get a sequence of lenght self.w
        t_ = choice(arange(start,end, 1)) 
        return t_
    def get_neg(self, t_anchor):
        w = self.w*self.sr
        t = int(t_anchor*self.tr*self.sr)
        left_idx = arange(self.d_audio, max(self.d_audio, t - self.neg), 1)
        right_idx =arange(min(self.f_audio-w-1, t + self.neg-1),self.f_audio-w-1 ,1)
        t_ = choice(hstack([left_idx, right_idx])) # 
        return t_