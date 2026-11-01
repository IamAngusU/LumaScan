# LumaScan

Local-first digitisation of family photographs, Polaroids and documents. A standalone Python backend with a replaceable desktop reference client and a small phone capture client. English and German. No mat required. No account, cloud processing, remote model downloads during scanning, or private ContextBridge runtime dependency.

**Status: 0.1 engineering preview.** The persistence, receipts and capture flow are tested; image-quality thresholds are heuristics, not calibrated guarantees of archival quality. A green check means the requested processing and storage completed without an outstanding review condition. It cannot prove colour accuracy, OCR correctness or restoration fidelity. Validate the workflow on your own printed photographs and physical iPhone before scanning an irreplaceable collection.

## Run

Python 3.11–3.13:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[ocr,dev]"
python scripts/fetch-model.py
lumascan --root . --lan-ip YOUR_PRIVATE_LAN_IPV4
```

Open `http://127.0.0.1:8772/scanner.html` on the computer. Choose a collection, treatment, OCR and destination, then **Connect iPhone**. Open its QR code on the same Wi-Fi and start the camera on the phone. The phone page is served at `https://YOUR_PRIVATE_LAN_IPV4:8773`. Camera access on a physical phone requires trusting this server's local CA; download `/certificate.cer`, install it and enable certificate trust yourself. Do not publish the CA key. Without `--lan-ip`, the service is loopback-only. Windows service helper: `scripts/manage.ps1 -Action start -LanIP YOUR_PRIVATE_LAN_IPV4` (also `status`, `stop`). The bind ports are fixed and configurable, not chosen randomly.

The server creates `data/digitize/journal.sqlite3` and a disk archive. Originals, tokens, keys, output, downloaded models and local paths are ignored by Git. This repository was extracted into a fresh history; the private Keyring repository and its scans were not made public.

The committed `requirements-lock.txt` records the tested Python 3.11 environment; use `pip install -c requirements-lock.txt -e ".[ocr,dev]"` for those versions. Run one service process per data root; the CLI's two listeners share that process and queue. Do not start multiple independent Uvicorn workers against the same archive.

## Capture contract

Place one original, or several separated originals. The server examines preview frames, crop-level focus, stability and content replacement. After at least 1.6 seconds and three stable observations it issues one capture intent. The phone sends its best available photograph. `ImageCapture.takePhoto` is used when supported; otherwise a full-resolution camera-stream frame is explicitly labelled `video-frame`. iOS Safari does not turn a browser stream into the native camera's full-resolution still sensor output. Use original-file import when that extra detail is required.

The phone displays a waiting animation while the backend processes and saves. A green check comes only from the backend's final receipt. Unchanged originals do not trigger repeatedly. Replacing the original rearms capture; clearing the surface for three observations also permits the same photograph again. Auto and manual triggering use the same intent and receipt contract.

Each intent freezes its destination, OCR, treatment and resolution floor. Changing the collection settings affects subsequent intents. Original bytes are SHA-256 hashed and fsynced before an upload is accepted. Reusing a request ID with different bytes returns 409; a retry of the same original returns its existing job. SQLite WAL with FULL synchronous writes journals each transition. Queued/processing jobs replay from their retained original after a restart, into a fresh attempt directory. Partial attempts are never treated as completed results.

The backend keeps raw originals, untouched perspective crops, processed PNGs, searchable PDFs, text, quality results and a SHA-256 manifest. Output files are flushed before completion. A separately chosen server folder is confirmed after all its copies finish. Errors there leave the local archive intact and block the green check. Existing changed destination files are not silently overwritten. A database is not a backup: include the complete `data` folder in your own backup, and keep a second copy on a separate device.

Low resolution, blank/low-texture crops, conflicting boundaries, requested-but-failed OCR and failed destination writes require review. The phone shows amber or red. A deliberate review acceptance is recorded; it does not hide the original quality reasons. OCR text remains inspectable. The thresholds can be changed through the session settings API.

## Vision and model choices

[DocAligner](https://github.com/DocsaidLab/DocAligner), release 1.1.1, LCNet-100 ONNX, supplies a single-document corner candidate. The loader checks its SHA-256 and uses CPU ONNX Runtime. It does not replace the multiple-item OpenCV detector: a single-document model can join several photos into one incorrect quadrilateral. On a single item, detector disagreement is an explicit review signal. We do not report a heatmap confidence as crop accuracy. Model source, license and hash are in `model-catalog.json`; weights are fetched explicitly and not redistributed here.

[RapidOCR](https://github.com/RapidAI/RapidOCR) 3.9.2 runs PP-OCRv6 and line-orientation classification in an offline subprocess. The three wheel-bundled ONNX hashes are pinned. No private Arsenal scripts are required. A strong line-classifier vote can orient text by 0/90/180/270 degrees; photos without text can be turned manually. Embedded ICC profiles are converted to sRGB for working images; original bytes and their embedded profiles are kept unchanged. Working images are 8-bit RGB. The PDF's nominal 300 dpi is a layout convention, not a measured capture resolution.

We also examined [PaddleOCR document preprocessing](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/doc_preprocessor.html), [UVDoc](https://github.com/tanguymagne/UVDoc) and its [Apache-2.0 Paddle model](https://huggingface.co/PaddlePaddle/UVDoc), [DocRes](https://github.com/ZZZHANG-jx/DocRes), [Docling](https://github.com/docling-project/docling), [SwinIR](https://github.com/JingyunLiang/SwinIR), and [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN). They are not installed or claimed as working features in this release. UVDoc is a suitable optional document-unwarping stage, but must not warp historical photos. Generative restoration can invent detail; it does not belong in the faithful archival master. Public distribution still requires complying with licenses, including separate model/dataset conditions.

## Existing processing tools

Multiple rectangular originals, manual corners, perspective correction, full-image import, JPEG/PNG/WebP/HEIC/TIFF decoding, colour/gray/document B&W modes, mild denoising/levels, manual scratch inpainting and immutable edit versions. Polaroid outer borders are retained. The optional vector A4 mat is served at `/print/lumascan-a4-v1.pdf?language=de` (or `en`), with a 152 × 232 mm grey area. Larger originals use a contrasting table without a mat. Overlap, severe curvature, reflection and poorly visible edges can require manual corners. No automatic missing-face reconstruction, photo colourisation or book dewarping is advertised.

The desktop reference client supports explicit server folders or File System Access where the browser provides it; Safari users can download/share a ZIP through Files. Direct phone capture uses the local HTTPS service, independently of the desktop tab. Legacy LumaDrop transport code is retained for compatibility but is not needed by the direct phone path.

## Backend integration and verification

The API is the product surface; the clients are examples. See [API contract](docs/api.md), the self-hosted reference at `/api.html` (also `/docs` after starting this version), and `/openapi.json`. No CDN is needed. A session-bound, expiring phone credential cannot list other collections, read archive files, change the PC's destinations or obtain an admin token. Pairing codes are single-use and expire after ten minutes. Device credentials expire after a day or on server restart. Re-pairing never loses completed jobs. ContextBridge resource discovery can use `resource-pack.json` and stable ID `iamangusu.lumascan`.

```sh
python -m pytest -q
```

Tests cover multi-item crops, preserved originals, edits, quality review, destination freezing, idempotent uploads, changed-request rejection, SQLite replay, manifest checks, device scope, pairing expiry/reuse, revocation and cross-origin blocking. The optional browser test uses an isolated `scripts/qa-server.py` and `scripts/verify-phone.cjs`, with `LUMASCAN_NODE_MODULES` pointing to an existing Playwright installation and `LUMASCAN_CHROME` to its browser. It uses generated originals, not family photographs. Generated test data stay in ignored `runtime/qa`. A browser simulation is not a physical iPhone test.
