"""DocAligner heatmap inference. Local checksum-pinned ONNX; no runtime download."""
import hashlib
import threading
from pathlib import Path
import cv2
import numpy as np

SHA256='f4117b786e3a18470f3865c93f3c2bd69d9b998edd60f385574a5c665e79594e'
_sessions={}
_lock=threading.Lock()

def detect(rgb, root):
    path=Path(root)/'models/docaligner-lcnet100.onnx'
    if not path.is_file():return None
    with _lock:
        key=(str(path),path.stat().st_mtime_ns)
        if key not in _sessions:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA256:raise ValueError('DocAligner model checksum mismatch')
            import onnxruntime as ort
            options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            _sessions.clear();_sessions[key]=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        session=_sessions[key]
    # Official Python upstream uses OpenCV BGR, CHW and [0,1] normalisation.
    x=cv2.resize(rgb[:,:,::-1],(256,256)).transpose(2,0,1)[None].astype(np.float32)/255
    outputs=session.run(None,{session.get_inputs()[0].name:x})
    heatmap=next((v for v in outputs if v.ndim==4 and v.shape[1]==4),None)
    if heatmap is None:raise ValueError('Unsupported DocAligner output contract')
    points=[];confidences=[]
    for channel in heatmap[0]:
        confidence=float(channel.max());confidences.append(confidence)
        if confidence<.3:return None
        mask=np.uint8(channel>=.3)*255
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:return None
        m=cv2.moments(max(contours,key=cv2.contourArea))
        if m['m00']<=0:return None
        points.append([m['m10']/m['m00']*rgb.shape[1]/channel.shape[1],m['m01']/m['m00']*rgb.shape[0]/channel.shape[0]])
    from .digitize import ordered_quad
    p=ordered_quad(points);area=cv2.contourArea(p)
    if area<rgb.shape[0]*rgb.shape[1]*.02 or np.any(p<0) or np.any(p[:,0]>=rgb.shape[1]) or np.any(p[:,1]>=rgb.shape[0]):return None
    return {'quad':p.tolist(),'corner_confidences':confidences,'model_sha256':SHA256,'method':'docaligner-lcnet100-1.1.1'}

def inspect(rgb,root):
    from .digitize import inspect as classic
    result=classic(rgb);result['detector']='opencv-multi'
    # A single-document model cannot choose which of several originals to keep.
    if len(result['quads'])<=1 and not result['mat']:
        model=detect(rgb,root)
        if model:
            result['model_candidate']=model
            if not result['quads']:result['quads']=[model['quad']];result['detector']=model['method']
            else:
                a=np.float32(result['quads'][0]);b=np.float32(model['quad']);intersection,_=cv2.intersectConvexConvex(a,b)
                union=cv2.contourArea(a)+cv2.contourArea(b)-intersection
                result['detector_agreement_iou']=round(float(intersection/max(union,1)),3)
                result['boundary_review']=intersection/max(union,1)<.85
    return result
