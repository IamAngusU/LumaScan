"""Server-owned stability and replacement gate; all timings use monotonic time."""
import time
import cv2
import numpy as np

class CaptureGate:
    def __init__(self, hold=1.6):
        self.hold=hold;self.previous=None;self.saved=None;self.since=None;self.samples=0;self.empty=0;self.pending=False;self.candidate=None

    @staticmethod
    def distance(a,b):
        if a is None or b is None or a.shape!=b.shape:return float('inf')
        diff=np.abs(a-b);n=max(1,int(diff.size*.03));return float(np.partition(diff,-n)[-n:].mean())

    def observe(self,rgb,detection,now=None):
        now=time.monotonic() if now is None else now
        if self.pending:return {'state':'processing','progress':0}
        quads=detection['quads']
        if not quads:
            self.empty+=1;self.since=None;self.samples=0;self.previous=None
            if self.empty>=3:self.saved=None
            return {'state':'empty','progress':0}
        self.empty=0
        from .digitize import rectify
        pixels=[];sharp=[]
        for quad in quads:
            crop=rectify(rgb,quad);gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
            sharp.append(cv2.Laplacian(gray,cv2.CV_64F).var());pixels.append(cv2.resize(gray,(64,64)).ravel())
        current=np.concatenate(pixels).astype(float)
        moving=self.distance(current,self.previous)>4;self.previous=current
        if moving or min(sharp)<20:
            self.since=now;self.samples=0
            return {'state':'moving' if moving else 'focus','progress':0}
        if self.distance(current,self.saved)<10:return {'state':'saved','progress':1}
        if self.since is None:self.since=now
        self.samples+=1;progress=min(1,(now-self.since)/self.hold)
        if progress>=1 and self.samples>=3:
            self.pending=True;self.candidate=current
            return {'state':'capture','progress':1}
        return {'state':'steady','progress':progress}

    def committed(self):self.saved=self.candidate;self.pending=False;self.since=None;self.samples=0
    def failed(self):self.pending=False;self.since=None;self.samples=0
