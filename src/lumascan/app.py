"""Standalone local service. Device tokens never authorize archive administration."""
import hmac
import json
import secrets
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pillow_heif import register_heif_opener
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import __version__
from .digitize_api import install as install_archive
from .devices import Devices, install as install_devices


class BodyLimit:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        total=0
        async def limited():
            nonlocal total
            message=await receive();total+=len(message.get('body',b''))
            if total>36*1024*1024:raise HTTPException(413,'Maximum request size: 36 MB')
            return message
        return await self.app(scope,limited,send)


def create_app(root:Path,token=None,lan_hosts=(),phone_origin='http://127.0.0.1:8772'):
    register_heif_opener();root=Path(root).resolve();runtime=root/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    tokenfile=runtime/'admin-token'
    if token is None:
        if not tokenfile.exists():tokenfile.write_text(secrets.token_urlsafe(32),'utf-8')
        token=tokenfile.read_text('utf-8').strip()
    devices=Devices()
    app=FastAPI(title='LumaScan',version=__version__,docs_url='/docs',redoc_url=None)
    app.state.root=root;app.state.devices=devices
    app.add_middleware(BodyLimit)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','testserver',*lan_hosts])
    @app.middleware('http')
    async def privacy(request:Request,next):
        path=request.url.path;local=request.client is not None and request.client.host in {'127.0.0.1','::1','testclient'}
        if path.startswith('/api/'):
            origin=request.headers.get('origin')
            if origin and origin!=str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'Cross-origin API requests are blocked'},status_code=403)
            credential=request.headers.get('authorization','').removeprefix('Bearer ')
            if path=='/api/bootstrap' and not local:return JSONResponse({'detail':'Pair on the computer'},status_code=403)
            public=(path=='/api/bootstrap' and local) or path=='/api/pair/claim'
            admin=hmac.compare_digest(credential,token)
            device=devices.authorize(credential) if path.startswith('/api/device') else None
            if not public and not admin and device is None:return JSONResponse({'detail':'Pair again at the computer'},status_code=401)
        response=await next(request)
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"})
        return response
    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({'detail':str(exc)},status_code=422)
    @app.exception_handler(FileNotFoundError)
    async def missing(request,exc):return JSONResponse({'detail':'File or session not found'},status_code=404)
    @app.get('/healthz')
    def health():return {'ok':True,'product':'LumaScan','version':__version__}
    @app.get('/api/bootstrap')
    def bootstrap():return {'token':token,'status':{'product':'LumaScan'}}
    @app.get('/certificate.cer')
    def certificate():return FileResponse(runtime/'certificate.cer',media_type='application/x-x509-ca-cert')
    adapter=install_archive(app,root)
    install_devices(app,root,adapter,devices,phone_origin)
    @app.get('/')
    def index():return RedirectResponse('/scanner.html')
    @app.get('/api/node/capabilities')
    def capabilities():return {'id':'iamangusu.lumascan','version':__version__,'capabilities':['local-capture','multi-item-rectification','ocr','durable-queue','capture-receipts']}
    app.mount('/',StaticFiles(directory=Path(__file__).with_name('static'),html=True),name='ui')
    return app
