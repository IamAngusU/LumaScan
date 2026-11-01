import io,json,time
import cv2
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from lumascan.app import create_app
from lumascan.quality import assess
from test_devices import picture

def terminal(c,sid,jid):
    for _ in range(200):
        job=c.get(f'/api/digitize/sessions/{sid}/jobs/{jid}').json()
        if job['receipt']['state']!='processing':return job
        time.sleep(.02)
    pytest.fail('processing did not finish')

def test_low_resolution_and_empty_crop_require_review():
    assert 'low_resolution' in assess(np.full((100,200,3),200,np.uint8))['reasons']
    assert not assess(np.full((1200,1200,3),200,np.uint8))['accepted']

def test_ocr_failure_is_visible_and_blocks_green(tmp_path,monkeypatch):
    from lumascan import digitize
    monkeypatch.setattr(digitize,'run_ocr',lambda *a:{'status':'failed','text':'','lines':[]})
    c=TestClient(create_app(tmp_path,token='a'));c.headers['Authorization']='Bearer a'
    sid=c.post('/api/digitize/sessions',json={}).json()['id'];raw,_=picture()
    j=c.post(f'/api/digitize/sessions/{sid}/capture',files={'file':('x.png',raw,'image/png')},data={'options':'{"ocr":true,"min_side":64}'}).json()
    job=terminal(c,sid,j['id']);assert job['receipt']['state']=='review'
    assert 'ocr_failed' in job['receipt']['reasons']
    assert c.get(f'/api/digitize/sessions/{sid}/jobs/{j["id"]}/files/original.png').content==raw

def test_intent_freezes_destination_and_settings(tmp_path):
    app=create_app(tmp_path,token='a');admin=TestClient(app);admin.headers['Authorization']='Bearer a'
    sid=admin.post('/api/digitize/sessions',json={}).json()['id']
    da=admin.post('/api/digitize/destinations',json={'path':str(tmp_path/'a')}).json()['id']
    db=admin.post('/api/digitize/destinations',json={'path':str(tmp_path/'b')}).json()['id']
    admin.patch(f'/api/digitize/sessions/{sid}/settings',json={'destination':da,'ocr':False,'min_side':64})
    pair=admin.post(f'/api/digitize/sessions/{sid}/pair').json()
    token=admin.post('/api/pair/claim',json={'code':pair['url'].split('pair=')[1]}).json()['token']
    phone=TestClient(app);phone.headers['Authorization']='Bearer '+token
    intent=phone.post('/api/device/intent').json()['intent_id']
    admin.patch(f'/api/digitize/sessions/{sid}/settings',json={'destination':db,'ocr':True})
    raw,_=picture();j=phone.post('/api/device/capture',files={'file':('x.png',raw,'image/png')},data={'intent_id':intent}).json()
    job=terminal(admin,sid,j['job_id'])
    assert job['destination']==da and not job['options']['ocr']
    assert job['export_status']=='saved'
    assert not list((tmp_path/'b').iterdir())

def test_changed_export_file_never_gets_overwritten_or_green(tmp_path):
    c=TestClient(create_app(tmp_path,token='a'));c.headers['Authorization']='Bearer a'
    sid=c.post('/api/digitize/sessions',json={}).json()['id']
    dest=c.post('/api/digitize/destinations',json={'path':str(tmp_path/'export')}).json()['id'];raw,_=picture()
    j=c.post(f'/api/digitize/sessions/{sid}/capture',files={'file':('x.png',raw,'image/png')},data={'options':json.dumps({'destination':dest,'min_side':64})}).json()
    terminal(c,sid,j['id'])
    original=next((tmp_path/'export').glob('*/original.png'));original.write_bytes(b'changed by user')
    result=c.post(f'/api/digitize/sessions/{sid}/jobs/{j["id"]}/retry-export')
    assert result.status_code==422 and original.read_bytes()==b'changed by user'
    assert not c.get(f'/api/digitize/sessions/{sid}/jobs/{j["id"]}').json()['receipt']['complete']

def test_remote_origin_and_device_revocation(tmp_path):
    app=create_app(tmp_path,token='a');c=TestClient(app);c.headers['Authorization']='Bearer a'
    assert c.post('/api/digitize/sessions',json={},headers={'Origin':'https://untrusted.invalid'}).status_code==403
    sid=c.post('/api/digitize/sessions',json={}).json()['id'];pair=c.post(f'/api/digitize/sessions/{sid}/pair').json()
    token=c.post('/api/pair/claim',json={'code':pair['url'].split('pair=')[1]}).json()['token']
    p=TestClient(app);p.headers['Authorization']='Bearer '+token
    assert p.delete('/api/device').status_code==200
    assert p.get('/api/device/state').status_code==401

def test_expired_pair_and_device_cannot_be_reused(tmp_path):
    app=create_app(tmp_path,token='a');c=TestClient(app);c.headers['Authorization']='Bearer a'
    sid=c.post('/api/digitize/sessions',json={}).json()['id']
    pair=c.post(f'/api/digitize/sessions/{sid}/pair').json();code=pair['url'].split('pair=')[1]
    app.state.devices.pairs[code]['expires']=0
    assert c.post('/api/pair/claim',json={'code':code}).status_code==410
    pair=c.post(f'/api/digitize/sessions/{sid}/pair').json()
    token=c.post('/api/pair/claim',json={'code':pair['url'].split('pair=')[1]}).json()['token']
    import hashlib
    app.state.devices.devices[hashlib.sha256(token.encode()).hexdigest()]['expires']=0
    assert c.get('/api/device/state',headers={'Authorization':'Bearer '+token}).status_code==401
