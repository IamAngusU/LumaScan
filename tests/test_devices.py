import io
import time
import json
import hashlib
import cv2
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
from lumascan.app import create_app
from lumascan.capture_gate import CaptureGate
from lumascan.repository import Repository
from lumascan.quality import receipt

def picture():
    rgb=np.full((900,1200,3),130,np.uint8)
    cv2.rectangle(rgb,(130,100),(1060,780),(248,246,242),-1)
    for y in range(170,700,70):cv2.putText(rgb,'FAMILY ARCHIVE 2026',(190,y),cv2.FONT_HERSHEY_SIMPLEX,1,(20,30,40),2)
    out=io.BytesIO();Image.fromarray(rgb).save(out,format='PNG');return out.getvalue(),rgb

def test_receipt_never_green_before_export_or_failed_ocr_review():
    job={'status':'ready','pages':[{}],'sha256':'x','export_status':'pending'}
    assert receipt(job)['state']=='processing'
    job.update(export_status='failed');assert receipt(job)['state']=='review'
    job.update(export_status='archive',review_reasons=['ocr_failed']);assert not receipt(job)['complete']
    job['review_accepted']=True;assert receipt(job)['complete']

def test_pairing_scope_one_use_and_saved_receipt(tmp_path):
    app=create_app(tmp_path,token='admin')
    admin=TestClient(app);admin.headers['Authorization']='Bearer admin'
    phone=TestClient(app,client=('192.168.1.12',55000))
    sid=admin.post('/api/digitize/sessions',json={'name':'Family'}).json()['id']
    admin.patch(f'/api/digitize/sessions/{sid}/settings',json={'ocr':False,'min_side':64})
    pair=admin.post(f'/api/digitize/sessions/{sid}/pair').json()
    from urllib.parse import urlsplit,parse_qs
    code=parse_qs(urlsplit(pair['url']).fragment)['pair'][0]
    claimed=phone.post('/api/pair/claim',json={'code':code}).json()
    assert phone.post('/api/pair/claim',json={'code':code}).status_code==410
    phone.headers['Authorization']='Bearer '+claimed['token']
    assert phone.get('/api/digitize/sessions').status_code==401
    assert phone.get('/api/bootstrap').status_code==403
    assert phone.get('/api/device/state').json()['collection']=='Family'
    intent=phone.post('/api/device/intent').json()['intent_id']
    raw,_=picture()
    result=phone.post('/api/device/capture',files={'file':('photo.png',raw,'image/png')},data={'intent_id':intent,'source':'camera-original'})
    assert result.status_code==202,result.text
    assert not result.json()['receipt']['complete']
    for _ in range(100):
        state=phone.get('/api/device/state').json()
        if state.get('receipt',{}).get('state')!='processing':break
        time.sleep(.03)
    if state['receipt']['state']=='review':state=phone.post('/api/device/review').json()
    assert state['receipt']['complete'],state
    assert state['saved_items']==1
    jid=result.json()['job_id']
    job=admin.get(f'/api/digitize/sessions/{sid}/jobs/{jid}').json()
    assert job['options']['min_side']==64
    assert job['attempt']==1
    manifest=admin.get(f'/api/digitize/sessions/{sid}/jobs/{jid}/files/manifest.json').json()
    assert manifest['original_sha256']==hashlib.sha256(raw).hexdigest()
    assert 'page-001/scan.png' in manifest['files']

def test_capture_idempotency_rejects_changed_original(tmp_path):
    c=TestClient(create_app(tmp_path,token='test'));c.headers['Authorization']='Bearer test'
    sid=c.post('/api/digitize/sessions',json={}).json()['id'];raw,rgb=picture()
    opts=json.dumps({'request_id':'a'*32,'ocr':False})
    first=c.post(f'/api/digitize/sessions/{sid}/capture',files={'file':('a.png',raw,'image/png')},data={'options':opts})
    assert first.status_code==202
    rgb[0:50]=0;b=io.BytesIO();Image.fromarray(rgb).save(b,format='PNG')
    assert c.post(f'/api/digitize/sessions/{sid}/capture',files={'file':('a.png',b.getvalue(),'image/png')},data={'options':opts}).status_code==409

def test_replay_preserves_original_and_uses_new_attempt(tmp_path):
    app=create_app(tmp_path,token='a');c=TestClient(app);c.headers['Authorization']='Bearer a'
    sid=c.post('/api/digitize/sessions',json={}).json()['id'];raw,_=picture()
    job=c.post(f'/api/digitize/sessions/{sid}/capture',files={'file':('a.png',raw,'image/png')},data={'options':'{"ocr":false}'}).json()
    for _ in range(100):
        saved=c.get(f'/api/digitize/sessions/{sid}/jobs/{job["id"]}').json()
        if saved['receipt']['state']!='processing':break
        time.sleep(.03)
    repo=app.state.repository;item=repo.load(sid);item['jobs'][0].update(status='processing',stage='ocr');repo.save(item)
    restarted=TestClient(create_app(tmp_path,token='b'));restarted.headers['Authorization']='Bearer b'
    for _ in range(100):
        replayed=restarted.get(f'/api/digitize/sessions/{sid}/jobs/{job["id"]}').json()
        if replayed['status']=='ready' and replayed['attempt']==2 and replayed.get('export_status')=='archive':break
        time.sleep(.03)
    assert replayed['attempt']==2 and replayed['status']=='ready'
    assert (tmp_path/'data/digitize'/sid/job['id']/'original.png').read_bytes()==raw

def test_server_gate_requires_stability_and_replacement():
    _,rgb=picture();d={'quads':[[[130,100],[1060,100],[1060,780],[130,780]]]}
    gate=CaptureGate();results=[gate.observe(rgb,d,now=t) for t in [0,.6,1.2,1.8]]
    assert sum(r['state']=='capture' for r in results)==1
    gate.committed();assert gate.observe(rgb,d,now=3)['state']=='saved'
    for i in range(3):gate.observe(rgb,{'quads':[]},now=4+i)
    assert gate.observe(rgb,d,now=8)['state']=='moving'
