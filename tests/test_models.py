"""Offline adapters: exact input contracts, colour preservation and real OCR smoke."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import json
import numpy as np
import pytest
from PIL import Image,ImageCms,ImageDraw,ImageFont
from lumascan import digitize

def test_embedded_srgb_conversion_and_bad_profile():
    rgb=Image.new('RGB',(100,80),(60,120,200));profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    out=io.BytesIO();rgb.save(out,format='PNG',icc_profile=profile)
    decoded=digitize.decode(out.getvalue());assert np.max(np.abs(decoded.astype(int)-np.asarray(rgb).astype(int)))<=1
    out=io.BytesIO();rgb.save(out,format='PNG',icc_profile=b'invalid profile')
    with pytest.raises(ValueError,match='colour profile'):digitize.decode(out.getvalue())

@pytest.mark.skipif(importlib.util.find_spec('rapidocr') is None,reason='optional OCR extra not installed')
def test_real_offline_ocr_and_orientation(tmp_path):
    image=Image.new('RGB',(1300,900),'white');d=ImageDraw.Draw(image);font=ImageFont.load_default(size=52)
    for i,line in enumerate(['Family archive 2026','Original photographs','Document digitisation']):d.text((80,160+i*180),line,fill='black',font=font)
    image.rotate(90,expand=True).save(tmp_path/'rotated.png')
    result=digitize.run_ocr(tmp_path,tmp_path/'rotated.png',tmp_path/'ocr')
    assert result['status']=='ready',result
    assert result['orientation']['clockwise']==90
    assert 'Family' in result['text']

@pytest.mark.skipif(not (Path(__file__).resolve().parents[1]/'models/docaligner-lcnet100.onnx').is_file(),reason='explicit optional model not installed')
def test_real_document_model_blank_negative_and_conservative_fallback():
    from lumascan.detector import detect,inspect
    root=Path(__file__).resolve().parents[1]
    assert detect(np.full((600,800,3),120,np.uint8),root) is None
    image=Image.new('RGB',(1200,900),'#707b80');d=ImageDraw.Draw(image);d.rectangle((180,100,1000,800),fill='white');font=ImageFont.load_default(size=35)
    for i in range(7):d.text((220,160+i*80),'FAMILY ALBUM 2026',fill='black',font=font)
    # The learned model may decline an artificial page. CV must remain usable.
    result=inspect(np.asarray(image),root);assert len(result['quads'])==1
    p=np.asarray(result['quads'][0]);assert np.linalg.norm(p.mean(axis=0)-[590,450])<120
