"""Explicit per-crop checks. These are heuristics, not calibrated accuracy scores."""
import cv2
import numpy as np


def assess(rgb, min_side=900):
    h,w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    ratio = min(1,1200/max(w,h))
    small = cv2.resize(gray,None,fx=ratio,fy=ratio,interpolation=cv2.INTER_AREA)
    sharpness = float(cv2.Laplacian(small,cv2.CV_64F).var())
    reasons=[]
    if min(w,h)<min_side:reasons.append('low_resolution')
    if sharpness<25:reasons.append('soft_focus_or_low_texture')
    if np.percentile(gray,98)-np.percentile(gray,2)<18:reasons.append('low_contrast_or_blank')
    return {'accepted':not reasons,'reasons':reasons,'width':w,'height':h,
            'sharpness':round(sharpness,2),'minimum_short_side':min_side,'method':'heuristics-v1'}


def receipt(job):
    processing=job['status'] in {'queued','processing'}
    reasons=list(job.get('review_reasons',[]))
    if job.get('export_status')=='failed':reasons.append('destination_write_failed')
    if job['status']=='failed':return {'state':'error','complete':False,'message':job.get('error','Processing failed')}
    if processing:return {'state':'processing','complete':False,'stage':job.get('stage',job['status']),'progress':job.get('progress',0)}
    if job.get('export_status')=='failed':return {'state':'review','complete':False,'reasons':sorted(set(reasons))}
    if job.get('export_status') not in {'saved','archive'}:return {'state':'processing','complete':False,'stage':'saving','progress':.95}
    if reasons and not job.get('review_accepted'):return {'state':'review','complete':False,'reasons':sorted(set(reasons))}
    return {'state':'saved','complete':True,'items':len(job['pages']),'sha256':job['sha256'],'reviewed':bool(job.get('review_accepted'))}
