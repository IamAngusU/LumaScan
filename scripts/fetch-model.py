"""Explicit download of one versioned model; never called by the running server."""
import hashlib
from pathlib import Path
import urllib.request
from lumascan.detector import SHA256

target=Path(__file__).resolve().parents[1]/'models/docaligner-lcnet100.onnx'
url='https://github.com/DocsaidLab/DocAligner/releases/download/1.1.1/lcnet100_h_e_bifpn_256_fp32.onnx'
raw=urllib.request.urlopen(url,timeout=60).read(20*1024*1024)
if hashlib.sha256(raw).hexdigest()!=SHA256:raise SystemExit('Model checksum mismatch; nothing installed')
target.parent.mkdir(parents=True,exist_ok=True)
if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=SHA256:raise SystemExit('A different local model exists; refusing overwrite')
target.write_bytes(raw)
print('Verified DocAligner 1.1.1 installed; upstream Apache-2.0. Weights remain outside Git.')
