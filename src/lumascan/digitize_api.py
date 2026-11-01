"""Digitisation sessions: queued originals, explicit destinations and immutable versions."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from . import digitize as engine
from .detector import inspect as inspect_image
from .repository import Repository
from .quality import assess, receipt


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Session(Strict):
    name: str = Field(default="Digitalisierung", min_length=1, max_length=120)


class Destination(Strict):
    path: str = Field(min_length=1, max_length=1024)


class Settings(Strict):
    quads: list[list[list[float]]] = Field(default_factory=list, max_length=24)
    detect: bool = True
    mode: str = Field(default="original", pattern="^(original|photo|mono|gray|document)$")
    ocr: bool = False
    orient: bool = True
    destination: str = Field(default="archive", max_length=32)
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern="^[a-f0-9]{32}$")
    source: str = Field(default="library", pattern="^(library|camera-original|video-frame)$")
    min_side: int = Field(default=900, ge=64, le=4000)


class Variant(Strict):
    mode: str = Field(default="original", pattern="^(original|photo|mono|gray|document)$")
    rotation: int = Field(default=0, ge=0, le=270, multiple_of=90)
    strokes: list[list[list[float]]] = Field(default_factory=list, max_length=100)
    radius: int = Field(default=5, ge=1, le=40)
    ocr: bool = False


def install(app, root):
    base = root/"data"/"digitize"
    base.mkdir(parents=True, exist_ok=True)
    lock = threading.RLock()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lumascan")
    config = base/"destinations.json"
    repository = Repository(base/'journal.sqlite3')
    app.state.repository = repository

    def now():
        return datetime.now(timezone.utc).isoformat()

    def write(path, data):
        tmp = path.with_suffix(".tmp")
        with tmp.open('wb') as stream:
            stream.write(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8'))
            stream.flush();os.fsync(stream.fileno())
        tmp.replace(path)
        if path.name=='session.json':repository.save(data)

    def identifier(value):
        if not re.fullmatch("[a-f0-9]{32}", value):
            raise ValueError("Invalid identifier / Ungültige ID.")
        return value

    def session_path(sid):
        path = base/identifier(sid)
        if not (path/"session.json").is_file():
            raise HTTPException(404, "Session not found / Sitzung nicht gefunden.")
        return path

    def load(sid):
        with lock:
            return repository.load(identifier(sid))

    def update(sid, fn):
        with lock:
            data = load(sid)
            fn(data)
            write(session_path(sid)/"session.json", data)
            return data

    def destinations():
        with lock:
            return json.loads(config.read_text("utf-8")) if config.exists() else []

    def destination_path(target):
        if target == "archive":
            return None
        found = next((d for d in destinations() if d["id"] == target), None)
        if not found:
            raise ValueError("Select a destination again / Zielordner erneut wählen.")
        return found["path"]

    def export_job(sid, jid):
        data = load(sid)
        job = next(j for j in data["jobs"] if j["id"] == jid)
        if not job.get("destination_path"):
            return
        src = session_path(sid)/jid/job['attempt_dir']
        target = Path(job["destination_path"])/("LumaScan-"+job["created_at"][:10]+"-"+jid)
        target.mkdir(parents=True, exist_ok=True)
        original=session_path(sid)/jid/job['original']
        original_target=target/job['original']
        if original_target.exists() and hashlib.sha256(original_target.read_bytes()).hexdigest()!=job['sha256']:
            raise ValueError('Original in destination differs; refusing to confirm export')
        if not original_target.exists():
            with original_target.open('xb') as stream:stream.write(original.read_bytes());stream.flush();os.fsync(stream.fileno())
        for path in src.rglob("*"):
            if path.is_file():
                output = target/path.relative_to(src)
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists():
                    if hashlib.sha256(output.read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest():
                        raise ValueError("Destination file changed / Datei im Ziel wurde verändert: "+str(output))
                else:
                    with output.open("xb") as stream:
                        stream.write(path.read_bytes())
                        stream.flush();os.fsync(stream.fileno())
        write(target/"batch.json", job)

    def worker(sid, jid, raw, settings):
        job=next(j for j in load(sid)['jobs'] if j['id']==jid)
        attempt=job.get('attempt',0)+1
        path = session_path(sid)/jid/f'attempt-{attempt:03}-{uuid.uuid4().hex[:8]}'
        path.mkdir()
        def job_update(**values):
            def change(data):
                next(j for j in data["jobs"] if j["id"] == jid).update(values)
            return update(sid, change)
        try:
            if hashlib.sha256(raw).hexdigest()!=job['sha256']:raise ValueError('Original checksum mismatch; processing stopped')
            job_update(status="processing", stage='detecting', progress=.05, attempt=attempt, attempt_dir=path.name)
            rgb = engine.decode(raw)
            detected = inspect_image(rgb,root)
            quads = settings.quads or (detected["quads"] if settings.detect else [])
            if not quads:
                raise ValueError("No borders found. Mark four corners or use full image / Keine Ränder erkannt. Vier Ecken markieren oder ganzes Bild wählen.")
            pages = []
            review_reasons=['boundary_disagreement'] if detected.get('boundary_review') and not settings.quads else []
            for index, quad in enumerate(quads, 1):
                crop = engine.rectify(rgb, quad)
                quality=assess(crop,settings.min_side)
                review_reasons.extend(quality['reasons'])
                job_update(stage='processing_pages',progress=.1+.7*(index-1)/len(quads))
                folder = path/f"page-{index:03}"
                folder.mkdir()
                Image.fromarray(crop).save(folder/"crop.png")
                processed = engine.treatment(crop, settings.mode)
                Image.fromarray(processed).save(folder/"scan.png")
                ocr = engine.run_ocr(root, folder/"scan.png", folder/"ocr") if settings.ocr else {"status": "off", "text": "", "lines": []}
                rotation = 0
                if settings.ocr and settings.orient and ocr.get("orientation", {}).get("confident"):
                    rotation = ocr["orientation"]["clockwise"]
                    if rotation:
                        processed = engine.treatment(processed, rotation=rotation)
                        Image.fromarray(processed).save(folder/"scan.png")
                        ocr = engine.run_ocr(root, folder/"scan.png", folder/"ocr-upright")
                if settings.ocr and ocr['status']!='ready':review_reasons.append('ocr_failed')
                (folder/"scan.pdf").write_bytes(engine.page_pdf(processed, ocr))
                (folder/"text.txt").write_text(ocr.get("text", ""), "utf-8")
                preview = Image.fromarray(processed); preview.thumbnail((480, 480)); preview.save(folder/"preview.jpg", quality=88)
                page = {"id": folder.name, "index": index, "quad": quad, "width": processed.shape[1], "height": processed.shape[0],
                        "mode": settings.mode, "rotation": rotation, "ocr": ocr, "versions": [], "quality":quality}
                pages.append(page)
            hashes={}
            for artifact in path.rglob('*'):
                if artifact.is_file():
                    with artifact.open('r+b') as stream:os.fsync(stream.fileno())
                    hashes[str(artifact.relative_to(path)).replace('\\','/')]=hashlib.sha256(artifact.read_bytes()).hexdigest()
            write(path/'manifest.json',{'original_sha256':job['sha256'],'files':hashes,'attempt':attempt})
            job_update(status="ready", stage='saving',progress=.95, export_status='pending',pages=pages, detection=detected,
                       review_reasons=sorted(set(review_reasons)), finished_at=now())
            try:
                export_job(sid, jid)
                job_update(export_status="saved" if settings.destination != "archive" else "archive",stage='complete',progress=1)
            except (OSError, ValueError) as exc:
                job_update(export_status="failed", export_error=str(exc))
        except Exception as exc:
            job_update(status="failed", error=str(exc)[:1000])

    # Durable replay uses a fresh attempt directory, never partially written results.
    for item in repository.listing():
        for job in item['jobs']:
            if job['status'] in {'queued','processing'}:
                raw=(base/item['id']/job['id']/job['original']).read_bytes()
                pool.submit(worker,item['id'],job['id'],raw,Settings.model_validate(job['options']))

    @app.get("/api/digitize/status")
    def status():
        python, script = engine.ocr_runtime(root)
        import importlib.util
        return {"ocr_available": importlib.util.find_spec('rapidocr') is not None, "engine": "RapidOCR / ONNX Runtime",
                "mat": engine.MAT_ID, "destinations": destinations()}

    @app.get("/scan-auto.mjs")
    def capture_gate_module():
        # Windows MIME registries often label .mjs as text/plain, which browsers
        # correctly reject for modules under nosniff.
        return FileResponse(Path(__file__).with_name("static")/"scan-auto.mjs", media_type="application/javascript")

    @app.get("/print/lumascan-a4-v1.pdf")
    def mat(language: str = "de"):
        return Response(engine.mat_pdf(language), media_type="application/pdf")

    @app.get("/api/digitize/sessions")
    def sessions():
        with lock:
            data = repository.listing()
        return sorted(data, key=lambda x: x["created_at"], reverse=True)

    @app.post("/api/digitize/sessions")
    def create_session(data: Session):
        sid = uuid.uuid4().hex
        item = {"id": sid, "name": data.name, "created_at": now(), "jobs": [],'settings':{'destination':'archive','mode':'original','ocr':True,'orient':True,'min_side':900}}
        (base/sid).mkdir()
        write(base/sid/"session.json", item)
        return item

    @app.get("/api/digitize/sessions/{sid}")
    def session(sid: str):
        data=load(sid)
        for job in data['jobs']:job['receipt']=receipt(job)
        return data

    @app.patch('/api/digitize/sessions/{sid}/settings')
    def session_settings(sid:str,data:Settings):
        values=data.model_dump(exclude={'request_id','source','quads','detect'})
        destination_path(values['destination'])
        return update(sid,lambda item:item.update(settings=values))

    @app.post("/api/digitize/destinations")
    def add_destination(data: Destination, request: Request):
        if request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(403, "Choose server folders at the server computer / Serverordner am Server-PC wählen.")
        path = Path(data.path)
        if not path.is_absolute() or "\x00" in data.path:
            raise ValueError("Use an absolute local path / Absoluten lokalen Pfad eingeben.")
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=True)
        with lock:
            items = destinations()
            item = next((x for x in items if x["path"] == str(path)), None)
            if not item:
                item = {"id": uuid.uuid4().hex, "path": str(path), "name": path.name or str(path)}
                items.append(item)
                write(config, items)
        return item

    @app.post("/api/digitize/inspect")
    def inspect(file: UploadFile = File(...)):
        raw = file.file.read(32*1024*1024+1)
        if len(raw) > 32*1024*1024:
            raise HTTPException(413, "32 MB maximum")
        return inspect_image(engine.decode(raw),root)

    @app.post("/api/digitize/preview")
    def compatible_preview(file: UploadFile = File(...)):
        raw = file.file.read(32*1024*1024+1)
        if len(raw) > 32*1024*1024:
            raise HTTPException(413, "32 MB maximum")
        rgb = engine.decode(raw)
        image = Image.fromarray(rgb)
        image.thumbnail((2400, 2400))
        out = io.BytesIO(); image.save(out, format="JPEG", quality=94)
        return Response(out.getvalue(), media_type="image/jpeg")

    @app.post("/api/digitize/sessions/{sid}/capture", status_code=202)
    def capture(sid: str, file: UploadFile = File(...), options: str = Form("{}")):
        settings = Settings.model_validate_json(options)
        raw = file.file.read(32*1024*1024+1)
        if len(raw)>32*1024*1024:raise HTTPException(413,'32 MB maximum')
        incoming_sha=hashlib.sha256(raw).hexdigest()
        with lock:
            item = load(sid)
            existing = next((j for j in item["jobs"] if j["request_id"] == settings.request_id), None)
            if existing:
                if existing['sha256']!=incoming_sha:raise HTTPException(409,'Request ID already belongs to a different original')
                return existing
            if sum(j["status"] in {"queued", "processing"} for j in item["jobs"]) >= 10:
                raise HTTPException(429, "Queue full / Warteschlange voll.")
            engine.decode(raw)  # Validate before accepting an archived job.
            suffix = Path(file.filename or "photo.jpg").suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}:
                suffix = ".bin"
            chosen_destination = destination_path(settings.destination)
            jid = uuid.uuid4().hex
            folder = session_path(sid)/jid; folder.mkdir()
            with (folder/("original"+suffix)).open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            job = {"id": jid, "request_id": settings.request_id, "created_at": now(), "status": "queued", "pages": [],
                   "source": settings.source, "original": "original"+suffix, "sha256": hashlib.sha256(raw).hexdigest(),
                   "destination": settings.destination, "destination_path": chosen_destination, "options": settings.model_dump()}
            update(sid, lambda x: x["jobs"].append(job))
            pool.submit(worker, sid, jid, raw, settings)
            return job

    @app.post("/api/digitize/sessions/{sid}/jobs/{jid}/retry-export")
    def retry(sid: str, jid: str):
        identifier(jid)
        try:export_job(sid, jid)
        except (OSError,ValueError) as exc:
            update(sid,lambda item:next(j for j in item['jobs'] if j['id']==jid).update(export_status='failed',export_error=str(exc)))
            raise ValueError(str(exc)) from exc
        return update(sid, lambda x: next(j for j in x["jobs"] if j["id"] == jid).update(export_status="saved", export_error=None))

    @app.get('/api/digitize/sessions/{sid}/jobs/{jid}')
    def job_status(sid:str,jid:str):
        identifier(jid)
        job=next((j for j in load(sid)['jobs'] if j['id']==jid),None)
        if job is None:raise HTTPException(404)
        return {**job,'receipt':receipt(job)}

    @app.post('/api/digitize/sessions/{sid}/jobs/{jid}/review')
    def accept_review(sid:str,jid:str):
        current=job_status(sid,jid)
        if current['status']!='ready' or current.get('export_status') not in {'saved','archive'}:raise HTTPException(409,'Processing or export incomplete')
        update(sid,lambda item:next(j for j in item['jobs'] if j['id']==jid).update(review_accepted=True,reviewed_at=now()))
        return job_status(sid,jid)

    @app.post('/api/digitize/sessions/{sid}/jobs/{jid}/retry')
    def retry_job(sid:str,jid:str):
        job=job_status(sid,jid)
        if job['status']!='failed':raise HTTPException(409,'Only failed jobs can be retried')
        update(sid,lambda item:next(j for j in item['jobs'] if j['id']==jid).update(status='queued',error=None))
        raw=(session_path(sid)/jid/job['original']).read_bytes()
        pool.submit(worker,sid,jid,raw,Settings.model_validate(job['options']))
        return job_status(sid,jid)

    @app.get("/api/digitize/sessions/{sid}/jobs/{jid}/files/{filename:path}")
    def file(sid: str, jid: str, filename: str):
        folder = session_path(sid)/identifier(jid)
        target = (folder/filename).resolve()
        job=job_status(sid,jid)
        if not target.is_file() and job.get('attempt_dir'):target=(folder/job['attempt_dir']/filename).resolve()
        if not target.is_relative_to(folder.resolve()) or not target.is_file():
            raise HTTPException(404, "File not found")
        return FileResponse(target)

    @app.get("/api/digitize/sessions/{sid}/jobs/{jid}/archive")
    def archive(sid: str, jid: str):
        folder = session_path(sid)/identifier(jid)
        if not folder.is_dir():
            raise HTTPException(404)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in folder.rglob("*"):
                if p.is_file():
                    z.write(p, str(p.relative_to(folder)).replace("\\", "/"))
            job = next(j for j in load(sid)["jobs"] if j["id"] == jid)
            z.writestr("batch.json", json.dumps(job, ensure_ascii=False, indent=2))
        return Response(out.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="LumaScan-{jid[:8]}.zip"'})

    @app.post("/api/digitize/sessions/{sid}/jobs/{jid}/pages/{pid}/versions")
    def variant(sid: str, jid: str, pid: str, options: Variant):
        identifier(jid)
        if not re.fullmatch(r"page-\d{3}", pid) or sum(len(s) for s in options.strokes) > 10000:
            raise ValueError("Invalid page / Ungültige Seite.")
        data = load(sid)
        job = next((j for j in data["jobs"] if j["id"] == jid), None)
        page = next((p for p in (job or {}).get("pages", []) if p["id"] == pid), None)
        if not page:
            raise HTTPException(404)
        folder = session_path(sid)/jid/job['attempt_dir']/pid
        rgb = engine.decode((folder/"crop.png").read_bytes())
        result = engine.treatment(rgb, options.mode, options.rotation, options.strokes, options.radius)
        vid = uuid.uuid4().hex
        Image.fromarray(result).save(folder/(vid+".png"))
        ocr = engine.run_ocr(root, folder/(vid+".png"), folder/vid) if options.ocr else {"status": "off", "lines": []}
        (folder/(vid+".pdf")).write_bytes(engine.page_pdf(result, ocr))
        version = {"id": vid, "created_at": now(), "options": options.model_dump(), "ocr": ocr}
        def add(data):
            job = next(j for j in data["jobs"] if j["id"] == jid)
            next(p for p in job["pages"] if p["id"] == pid)["versions"].append(version)
        update(sid, add)
        try:
            export_job(sid, jid)
        except (OSError, ValueError) as exc:
            update(sid,lambda item:next(j for j in item['jobs'] if j['id']==jid).update(export_status='failed',export_error=str(exc)))
            version["export_error"] = "Version in local archive; destination unavailable / Version lokal; Ziel nicht erreichbar."
        return version

    def metadata():
        return [{"id": s["id"], "name": s["name"], "created_at": s["created_at"],
                 "captures": len(s["jobs"]), "saved_items": sum(len(j["pages"]) for j in s["jobs"] if j["status"] == "ready")}
                for s in sessions()]

    return {"status": status, "metadata": metadata,'session':session,'capture':capture,'job':job_status,'settings':session_settings,'review':accept_review,'retry':retry_job}
