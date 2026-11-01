"""Standalone offline RapidOCR worker; no private runtime source dependency."""
import argparse, hashlib, importlib.metadata, json, socket
from pathlib import Path
MODELS={
 'PP-OCRv6_det_small.onnx':'090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
 'ch_ppocr_mobile_v2.0_cls_mobile.onnx':'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
 'PP-OCRv6_rec_small.onnx':'6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884'}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('image',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    import rapidocr, numpy as np, cv2
    from rapidocr import RapidOCR
    from PIL import Image
    if importlib.metadata.version('rapidocr')!='3.9.2':raise RuntimeError('Install rapidocr==3.9.2')
    modeldir=Path(rapidocr.__file__).parent/'models'
    for name,sha in MODELS.items():
        if not (modeldir/name).is_file() or hashlib.sha256((modeldir/name).read_bytes()).hexdigest()!=sha:raise RuntimeError('OCR checksum mismatch: '+name)
    class OfflineSocket(socket.socket):
        def connect(self,*args,**kwargs):raise RuntimeError('OCR network access disabled')
        def connect_ex(self,*args,**kwargs):raise RuntimeError('OCR network access disabled')
    socket.socket=OfflineSocket
    params={'Global.model_root_dir':str(modeldir),'Global.return_word_box':False,
      'Det.model_path':str(modeldir/'PP-OCRv6_det_small.onnx'),'Cls.model_path':str(modeldir/'ch_ppocr_mobile_v2.0_cls_mobile.onnx'),
      'Rec.model_path':str(modeldir/'PP-OCRv6_rec_small.onnx'),'Rec.rec_keys_path':None,
      'EngineConfig.onnxruntime.intra_op_num_threads':2,'EngineConfig.onnxruntime.inter_op_num_threads':1,
      'EngineConfig.onnxruntime.use_cuda':False,'EngineConfig.onnxruntime.use_dml':False}
    engine=RapidOCR(params=params)
    rgb=np.asarray(Image.open(args.image).convert('RGB'));bgr=rgb[:,:,::-1].copy();result=engine(bgr,use_det=True,use_cls=True,use_rec=True)
    lines=[]
    if result.boxes is not None:
        for i,(box,text,score) in enumerate(zip(result.boxes,result.txts,result.scores)):
            lines.append({'index':i,'polygon':np.asarray(box).tolist(),'text':str(text),'score':float(score)})
    patches=[];rotations=[]
    for line in lines:
        p=np.float32(line['polygon']);w=max(8,round(np.linalg.norm(p[1]-p[0])));h=max(8,round(np.linalg.norm(p[3]-p[0])))
        matrix=cv2.getPerspectiveTransform(p,np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]]))
        patch=cv2.warpPerspective(bgr,matrix,(w,h));vertical=h>w*1.5
        patches.append(np.rot90(patch).copy() if vertical else patch);rotations.append(270 if vertical else 0)
    votes=[]
    if patches:
        for base,(angle,score) in zip(rotations,engine.text_cls(patches).cls_res or []):
            if float(score)>=.96:votes.append((base+int(angle))%360)
    winner=max(set(votes),key=votes.count) if votes else 0
    trusted=len(votes)>=2 and votes.count(winner)/max(1,len(lines))>=.8
    report={'text':'\n'.join(l['text'] for l in lines),'lines':lines,'models':[{'filename':n,'sha256':s} for n,s in MODELS.items()],
      'orientation':{'clockwise':winner if trusted else 0,'confident':trusted,'votes':votes},'runtime':'rapidocr-3.9.2-cpu-offline'}
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'ocr.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    (args.output/'ocr.txt').write_text(report['text'],'utf-8')
    print(json.dumps({'ready':True,'lines':len(lines)}))
if __name__=='__main__':main()
