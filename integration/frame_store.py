"""Bounded image decoding for long native avatar motion libraries."""
from collections import OrderedDict
from collections.abc import Sequence
import operator
import threading
import cv2

class FrameStore(Sequence):
    def __init__(self, paths, cache_size=48):
        self.paths=tuple(paths)
        self.cache_size=max(1,int(cache_size))
        self.cache=OrderedDict()
        self.lock=threading.RLock()

    def __len__(self):return len(self.paths)

    def __getitem__(self,index):
        if isinstance(index,slice):return [self[i] for i in range(*index.indices(len(self)))]
        index=operator.index(index)
        if index<0:index+=len(self)
        if index<0 or index>=len(self):raise IndexError('Avatar frame index out of range')
        with self.lock:
            image=self.cache.pop(index,None)
            if image is None:
                image=cv2.imread(self.paths[index])
                if image is None:raise RuntimeError('Cannot decode avatar frame: '+self.paths[index])
            self.cache[index]=image
            while len(self.cache)>self.cache_size:self.cache.popitem(last=False)
            return image
