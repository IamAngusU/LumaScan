"""Expiring pairing and scoped phone API; server settings are frozen per intent."""
import hashlib
import io
import json
import secrets
import threading
import time
import uuid

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from .capture_gate import CaptureGate
from .digitize_api import Settings
from .digitize import decode
from .detector import inspect


class Devices:
    def __init__(self):
        self.lock=threading.RLock();self.pairs={};self.devices={}

    def authorize(self,token):
        key=hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            device=self.devices.get(key)
            if not device or device['expires']<time.time():return None
            return device

def install(app,root,adapter,devices,phone_origin):
    @app.post('/api/digitize/sessions/{sid}/pair')
    def pair(sid:str):
        adapter['session'](sid)
        code=secrets.token_urlsafe(32)
        with devices.lock:
            devices.pairs[code]={'sid':sid,'expires':time.time()+600}
        url=phone_origin+'/phone.html#pair='+code
        import qrcode
        image=qrcode.make(url);out=io.BytesIO();image.save(out,format='PNG')
        import base64
        return {'url':url,'qr_data_url':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode(),'expires_in':600}

    @app.post('/api/pair/claim')
    async def claim(request:Request):
        body=await request.json();code=body.get('code','')
        if not isinstance(code,str) or len(code)>100:raise HTTPException(400)
        with devices.lock:
            pairing=devices.pairs.pop(code,None)
            if not pairing or pairing['expires']<time.time():raise HTTPException(410,'Pairing expired. Scan a fresh code.')
            token=secrets.token_urlsafe(32)
            device={'sid':pairing['sid'],'expires':time.time()+86400,'gate':CaptureGate(),'intent':None,'job':None}
            devices.devices[hashlib.sha256(token.encode()).hexdigest()]=device
        return {'token':token,'session_id':device['sid'],'expires_in':86400}

    def current(request):
        d=devices.authorize(request.headers.get('authorization','').removeprefix('Bearer '))
        if d is None:raise HTTPException(401,'Pair again at the computer')
        return d

    def view(d):
        session=adapter['session'](d['sid'])
        count=sum(len(j['pages']) for j in session['jobs'] if j['receipt']['complete'])
        result={'collection':session['name'],'saved_items':count,'settings':session['settings']}
        if d['job']:
            job=next(j for j in session['jobs'] if j['id']==d['job'])
            result.update(receipt=job['receipt'],job_id=job['id'])
            if job['receipt']['complete'] and d['gate'].pending:d['gate'].committed()
        return result

    def intent(d):
        if d['intent'] and not d['job'] and time.monotonic()-d['intent']['created']>120:
            d['intent']=None;d['gate'].failed()
        if d['intent'] and not d['job']:return d['intent']['id']
        if d['job']:
            receipt=adapter['job'](d['sid'],d['job'])['receipt']
            if receipt['state'] in {'processing','review','error'}:raise HTTPException(409,'Complete or review the previous capture first')
        settings=Settings.model_validate({**adapter['session'](d['sid'])['settings'],'request_id':uuid.uuid4().hex})
        d['intent']={'id':settings.request_id,'settings':settings,'created':time.monotonic()};d['job']=None
        return settings.request_id

    @app.get('/api/device/state')
    def state(request:Request):
        with devices.lock:return view(current(request))

    @app.post('/api/device/preview')
    def preview(request:Request,file:UploadFile=File(...)):
        d=current(request)
        raw=file.file.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise HTTPException(413)
        rgb=decode(raw,max_pixels=2_000_000)
        with devices.lock:
            result=view(d)
            if result.get('receipt',{}).get('state') in {'processing','review','error'}:
                return {**result,'state':result['receipt']['state']}
            if d['intent'] and not d['job'] and time.monotonic()-d['intent']['created']>120:
                d['intent']=None;d['gate'].failed()
            if d['intent'] and not d['job']:
                return {**result,'state':'capture','intent_id':d['intent']['id']}
            detection=inspect(rgb,root);gate=d['gate'].observe(rgb,detection)
            if gate['state']=='capture':gate['intent_id']=intent(d)
            return {**result,**gate,'detection':detection}

    @app.post('/api/device/intent')
    def manual_intent(request:Request):
        with devices.lock:
            d=current(request);iid=intent(d);d['gate'].pending=True;d['gate'].candidate=d['gate'].previous
            return {'intent_id':iid}

    @app.post('/api/device/capture',status_code=202)
    def capture(request:Request,file:UploadFile=File(...),intent_id:str=Form(...),source:str=Form('video-frame')):
        d=current(request)
        with devices.lock:
            pending=d['intent']
            if not pending or pending['id']!=intent_id or time.monotonic()-pending['created']>120:raise HTTPException(409,'Capture intent expired')
            if source not in {'video-frame','camera-original','library'}:raise HTTPException(422)
            options=pending['settings'].model_copy(update={'source':source})
            job=adapter['capture'](d['sid'],file,options.model_dump_json())
            d['job']=job['id']
            return {'job_id':job['id'],'receipt':{'state':'processing','complete':False}}

    @app.post('/api/device/review')
    def accept_review(request:Request):
        d=current(request)
        if not d['job']:raise HTTPException(409)
        with devices.lock:
            adapter['review'](d['sid'],d['job'])
            return view(d)

    @app.post('/api/device/retry')
    def retry(request:Request):
        d=current(request)
        if not d['job']:raise HTTPException(409)
        adapter['retry'](d['sid'],d['job'])
        return view(d)

    @app.delete('/api/device')
    def revoke(request:Request):
        token=request.headers.get('authorization','').removeprefix('Bearer ')
        with devices.lock:devices.devices.pop(hashlib.sha256(token.encode()).hexdigest(),None)
        return {'revoked':True}
