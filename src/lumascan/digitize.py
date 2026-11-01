"""Local flat-artwork detection, perspective crops and reversible photo treatments."""
from __future__ import annotations

import io
import os
import subprocess
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, ImageCms
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

MAT_ID = "lumascan-a4-v1"
MARKERS = {40: (7, 30), 41: (187, 30), 42: (7, 139),
           43: (187, 139), 44: (7, 248), 45: (187, 248)}
AREA = (29, 32, 181, 264)


def mat_pdf(language="de"):
    if language not in {"de", "en"}:
        raise ValueError("language must be de or en")
    de = language == "de"
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(210*72/25.4, 297*72/25.4))
    c.setTitle("LumaScan A4 - " + ("Fotos & Dokumente" if de else "Photos & documents"))
    c.scale(72/25.4, 72/25.4)

    def text(x, y, value, size=2.7, bold=False):
        c.setFillGray(.15)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, 297-y, value)

    text(9, 13, "LumaScan", 7, True)
    text(9, 20, "Fotos und Dokumente digitalisieren" if de else "Digitise photos and documents", 3.5)
    text(9, 25, "A4 / 100 % / flach auflegen" if de else "A4 / 100% / keep flat", 2.6)
    c.setFillGray(.76)
    c.rect(AREA[0], 297-AREA[3], AREA[2]-AREA[0], AREA[3]-AREA[1], fill=1, stroke=0)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for mid, (x, y) in MARKERS.items():
        bits = cv2.aruco.generateImageMarker(dictionary, mid, 6)
        c.setFillGray(0)
        for row in range(6):
            for col in range(6):
                if bits[row, col] == 0:
                    c.rect(x+col*16/6, 297-y-(row+1)*16/6, 16/6, 16/6, fill=1, stroke=0)
        text(x+3, y+20, str(mid), 2.2)
    text(29, 272, "152 x 232 mm frei / Abstand zwischen Vorlagen lassen" if de else "152 x 232 mm clear / leave space between items", 2.5)
    text(9, 280, "Polaroid-Rahmen behalten. Marker frei halten. Licht ohne Spiegelung." if de else "Keep Polaroid borders. Keep markers clear. Avoid glare.", 2.6)
    text(9, 285, "Grosse Dokumente: ohne Matte auf kontrastreichem Tisch aufnehmen." if de else "Large documents: capture without mat on a contrasting table.", 2.6)
    text(9, 291, MAT_ID + " / ArUco 4x4_50 / IDs 40-45", 2.2)
    c.setFont("Helvetica", 2.3)
    c.drawRightString(201, 6, "powered by angusu.de")
    c.showPage()
    c.save()
    return out.getvalue()


def decode(raw, max_pixels=60_000_000):
    with Image.open(io.BytesIO(raw)) as im:
        if im.width*im.height > max_pixels or min(im.size) < 32:
            raise ValueError("Unsupported image dimensions / Bildabmessungen nicht geeignet.")
        oriented=ImageOps.exif_transpose(im)
        if im.info.get('icc_profile'):
            try:
                oriented=ImageCms.profileToProfile(oriented,ImageCms.ImageCmsProfile(io.BytesIO(im.info['icc_profile'])),ImageCms.createProfile('sRGB'),outputMode='RGB')
            except (ImageCms.PyCMSError,OSError,ValueError) as exc:
                raise ValueError('Invalid embedded colour profile; original retained, review colour conversion') from exc
        return np.asarray(oriented.convert("RGB"))


def ordered_quad(points):
    p = np.asarray(points, np.float32)
    if p.shape != (4, 2) or not np.isfinite(p).all():
        raise ValueError("Four finite corners required / Vier gültige Ecken nötig.")
    # Convex hull + angular ordering also works for rotated diamonds.
    hull = cv2.convexHull(p).reshape(-1, 2)
    if len(hull) != 4 or abs(cv2.contourArea(hull)) < 64:
        raise ValueError("Corners must form a convex rectangle / Konvexe Eckpunkte nötig.")
    center = hull.mean(axis=0)
    hull = hull[np.argsort(np.arctan2(hull[:, 1]-center[1], hull[:, 0]-center[0]))]
    return np.roll(hull, -np.argmin(hull.sum(axis=1)), axis=0)


def rectify(rgb, points):
    p = ordered_quad(points)
    h, w = rgb.shape[:2]
    if np.any(p < 0) or np.any(p[:, 0] > w-1) or np.any(p[:, 1] > h-1):
        raise ValueError("Corners outside image / Ecken außerhalb des Fotos.")
    if np.allclose(p, [[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]], atol=.001):
        return rgb.copy()
    widths = [np.linalg.norm(p[1]-p[0]), np.linalg.norm(p[2]-p[3])]
    heights = [np.linalg.norm(p[3]-p[0]), np.linalg.norm(p[2]-p[1])]
    dw, dh = int(round(max(widths)))+1, int(round(max(heights)))+1
    if min(dw, dh) < 16 or dw*dh > 60_000_000:
        raise ValueError("Crop dimensions unsuitable / Ausschnitt nicht geeignet.")
    matrix = cv2.getPerspectiveTransform(p, np.float32([[0, 0], [dw-1, 0], [dw-1, dh-1], [0, dh-1]]))
    return cv2.warpPerspective(rgb, matrix, (dw, dh), flags=cv2.INTER_CUBIC)


def inspect(rgb):
    """Return all non-nested rectangles and marker locations in ORIGINAL pixels."""
    height, width = rgb.shape[:2]
    scale = min(1, 1280/max(width, height))
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
    corners, ids, _ = detector.detectMarkers(gray)
    markers = []
    if ids is not None:
        for p, mid in zip(corners, ids.ravel()):
            if int(mid) in MARKERS:
                markers.append({"id": int(mid), "points": (p.reshape(4, 2)/scale).tolist()})
    homography = None
    if len(markers) >= 4 and len({m["id"] for m in markers}) == len(markers):
        paper, image = [], []
        for m in markers:
            x, y = MARKERS[m["id"]]
            paper.extend([[x, y], [x+16, y], [x+16, y+16], [x, y+16]])
            image.extend(m["points"])
        homography, _ = cv2.findHomography(np.float32(image), np.float32(paper), 0)
        if homography is not None:
            fit = cv2.perspectiveTransform(np.float32(image).reshape(-1, 1, 2), homography).reshape(-1, 2)
            if np.sqrt(np.mean(np.square(fit-np.asarray(paper)))) > 1.0:
                homography = None
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 35, 100)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    candidates = []
    # Edges recover both light/dark prints; thresholds recover weak white borders.
    for mask in [edges, cv2.threshold(blur, 218, 255, cv2.THRESH_BINARY)[1],
                 cv2.threshold(blur, 95, 255, cv2.THRESH_BINARY_INV)[1]]:
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if cv2.contourArea(contour) < sw*sh*.007:
                continue
            q = cv2.approxPolyDP(contour, .018*cv2.arcLength(contour, True), True)
            if len(q) != 4 or not cv2.isContourConvex(q):
                continue
            p = ordered_quad(q.reshape(4, 2))/scale
            if cv2.contourArea(p) > width*height*.96:
                continue
            if np.any(p[:, 0] < 2/scale) or np.any(p[:, 1] < 2/scale) or np.any(p[:, 0] > width-3/scale) or np.any(p[:, 1] > height-3/scale):
                continue
            if homography is not None:
                world = cv2.perspectiveTransform(p.reshape(-1, 1, 2), homography).reshape(-1, 2)
                if np.any(world < np.array(AREA[:2])+.7) or np.any(world > np.array(AREA[2:])-.7):
                    continue
            else:
                # Never classify a decoded calibration marker as a photograph.
                if any(cv2.pointPolygonTest(p, tuple(np.mean(m["points"], axis=0)), False) >= 0 for m in markers):
                    continue
            sides = np.linalg.norm(p-np.roll(p, 1, axis=0), axis=1)
            if sides.max()/max(1, sides.min()) > 12:
                continue
            candidates.append(p)
    # Keep the outside border (including the Polaroid frame), discard inner art/text.
    selected = []
    for p in sorted(candidates, key=cv2.contourArea, reverse=True):
        if any(cv2.pointPolygonTest(q, tuple(p.mean(axis=0)), True) >= -4/scale for q in selected):
            continue
        selected.append(p)
        if len(selected) >= 24:
            break
    selected.sort(key=lambda p: (round(float(p.mean(axis=0)[1])/(height*.1)), float(p.mean(axis=0)[0])))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {"width": width, "height": height, "quads": [p.tolist() for p in selected],
            "markers": markers, "mat": MAT_ID if homography is not None else None,
            "sharpness": round(sharpness, 2), "glare_fraction": round(float((gray > 252).mean()), 3)}


def treatment(rgb, mode="original", rotation=0, strokes=(), radius=5):
    result = rgb.copy()
    if mode in {"photo", "mono"}:
        result = cv2.fastNlMeansDenoisingColored(result, None, 3, 3, 7, 21)
        low = np.percentile(result, .4, axis=(0, 1))
        high = np.percentile(result, 99.6, axis=(0, 1))
        result = np.clip((result.astype(float)-low)*255/np.maximum(high-low, 32), 0, 255).astype(np.uint8)
    if mode in {"mono", "gray", "document"}:
        gray = cv2.cvtColor(result, cv2.COLOR_RGB2GRAY)
        if mode == "document":
            bg = cv2.GaussianBlur(gray, (0, 0), max(8, min(gray.shape)/35))
            gray = cv2.divide(gray, bg, scale=255)
            gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 14)
        result = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    if strokes:
        mask = np.zeros(result.shape[:2], np.uint8)
        for line in strokes:
            points = np.asarray(line, np.float64)
            if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all() or np.any(points < 0) or np.any(points > 1):
                raise ValueError("Invalid repair mask / Ungültige Reparaturmaske.")
            pts = (points*np.array([result.shape[1]-1, result.shape[0]-1])).astype(np.int32)
            cv2.polylines(mask, [pts], False, 255, radius*2)
            for point in pts:
                cv2.circle(mask, tuple(point), radius, 255, -1)
        if np.count_nonzero(mask) > mask.size*.25:
            raise ValueError("Repair mask exceeds 25% / Reparatur auf kleine Schäden begrenzen.")
        result = cv2.inpaint(result, mask, 3, cv2.INPAINT_TELEA)
    return np.rot90(result, -(rotation//90)).copy()


def ocr_runtime(root):
    config = root/"runtime"/"local-config.json"
    cfg = json.loads(config.read_text("utf-8-sig")) if config.exists() else {}
    python = Path(cfg.get("ocr_python",sys.executable))
    script = Path(__file__).with_name("digitize_ocr_worker.py")
    return python, script


def run_ocr(root, image, output):
    python, script = ocr_runtime(root)
    if not python.is_file() or not script.is_file():
        return {"status": "unavailable", "text": "", "lines": []}
    env = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    try:
        process = subprocess.run([str(python), str(script), str(image), str(output)],
                                 capture_output=True, text=True, encoding="utf-8", env=env, timeout=90,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if process.returncode:
            return {"status": "failed", "text": "", "lines": [], "error": process.stderr[-800:]}
        report = json.loads((output/"ocr.json").read_text("utf-8"))
        return {"status": "ready", "text": report["text"], "lines": report["lines"], "models": report["models"], "orientation": report["orientation"]}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"status": "failed", "text": "", "lines": [], "error": str(exc)[:300]}


def page_pdf(rgb, ocr=None):
    """Image-sized searchable PDF, 300dpi nominal; OCR stays a separate invisible layer."""
    h, w = rgb.shape[:2]
    pw, ph = w*72/300, h*72/300
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(pw, ph))
    c.drawImage(ImageReader(Image.fromarray(rgb)), 0, 0, pw, ph)
    # DejaVu gives a Unicode text layer, including German umlauts.
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font = "Helvetica"
    for path in [Path(os.environ.get("WINDIR", "C:/Windows"))/"Fonts/arial.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]:
        if path.is_file():
            if "ScanUnicode" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("ScanUnicode", str(path)))
            font = "ScanUnicode"
            break
    for line in (ocr or {}).get("lines", []):
        p = np.asarray(line["polygon"])
        x, y = p.min(axis=0); right, bottom = p.max(axis=0)
        text = c.beginText(x*72/300, (h-bottom)*72/300)
        text.setTextRenderMode(3)
        size = max(1, (bottom-y)*72/300*.8)
        text.setFont(font, size)
        length = pdfmetrics.stringWidth(line["text"], font, size)
        if length:
            text.setHorizScale((right-x)*72/300/length*100)
        text.textOut(line["text"])
        c.drawText(text)
    c.showPage(); c.save()
    return out.getvalue()
