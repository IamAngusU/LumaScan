import io
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lumascan.app import create_app
from lumascan import digitize


def scene():
    rgb = np.full((900, 1100, 3), 125, np.uint8)
    cv2.rectangle(rgb, (70, 90), (440, 650), (249, 249, 247), -1)
    cv2.rectangle(rgb, (95, 120), (414, 490), (68, 111, 164), -1)
    cv2.putText(rgb, 'POLAROID', (110, 580), cv2.FONT_HERSHEY_SIMPLEX, .8, (30, 30, 30), 2)
    cv2.fillConvexPoly(rgb, np.int32([[630, 140], [1000, 210], [920, 740], [560, 670]]), (242, 240, 235))
    cv2.putText(rgb, 'ARCHIVE 2026', (650, 400), cv2.FONT_HERSHEY_SIMPLEX, .6, (20, 20, 20), 2)
    return rgb


def png(rgb):
    b = io.BytesIO(); Image.fromarray(rgb).save(b, format='PNG'); return b.getvalue()


def test_multi_detection_keeps_polaroid_outer_border_and_rectifies():
    result = digitize.inspect(scene())
    assert len(result['quads']) == 2
    crops = [digitize.rectify(scene(), p) for p in result['quads']]
    assert min(crops[0].shape[:2]) > 350  # white border, not inner art
    assert result['mat'] is None
    assert not digitize.inspect(np.full((500, 500, 3), 180, np.uint8))['quads']
    assert np.array_equal(digitize.rectify(scene(),[[0,0],[1099,0],[1099,899],[0,899]]),scene())


def test_treatments_preserve_input_and_repair_only_marked_pixels():
    rgb = scene(); original = rgb.copy()
    fixed = digitize.treatment(rgb, 'original', strokes=[[[.1, .1], [.2, .15]]])
    assert np.array_equal(rgb, original)
    assert np.array_equal(fixed[600:], rgb[600:])
    assert digitize.treatment(rgb, rotation=90).shape[:2] == (1100, 900)
    with pytest.raises(ValueError):
        digitize.treatment(rgb, strokes=[[[float('nan'), 0]]])


def wait_ready(client, sid):
    for _ in range(100):
        data = client.get(f'/api/digitize/sessions/{sid}').json()
        if all(j['receipt']['state'] not in {'processing'} for j in data['jobs']):
            return data
        time.sleep(.03)
    pytest.fail('job did not finish')


def test_archive_counter_idempotency_frozen_folder_and_versions(tmp_path):
    client = TestClient(create_app(tmp_path, token='test'))
    client.headers['Authorization'] = 'Bearer test'
    sid = client.post('/api/digitize/sessions', json={'name': 'Album'}).json()['id']
    dest = client.post('/api/digitize/destinations', json={'path': str(tmp_path/'album')}).json()
    options = '{"destination":"'+dest['id']+'","request_id":"'+'a'*32+'"}'
    response = client.post(f'/api/digitize/sessions/{sid}/capture', files={'file': ('photo.png', png(scene()), 'image/png')}, data={'options': options})
    assert response.status_code == 202
    jid = response.json()['id']
    retry = client.post(f'/api/digitize/sessions/{sid}/capture', files={'file': ('photo.png', png(scene()), 'image/png')}, data={'options': options})
    assert retry.json()['id'] == jid
    data = wait_ready(client, sid)
    job = data['jobs'][0]
    assert job['status'] == 'ready', job
    assert len(job['pages']) == 2
    assert len(data['jobs']) == 1
    assert job['export_status'] == 'saved'
    assert list((tmp_path/'album').glob('*/page-001/scan.pdf'))
    prefix = f'/api/digitize/sessions/{sid}/jobs/{jid}'
    before = client.get(prefix+'/files/page-001/crop.png').content
    result = client.post(prefix+'/pages/page-001/versions', json={'mode': 'gray', 'rotation': 90})
    assert result.status_code == 200
    assert client.get(prefix+'/files/page-001/crop.png').content == before
    assert client.get(prefix+'/archive').headers['content-type'] == 'application/zip'
    assert client.get('/api/digitize/sessions', headers={'Authorization': ''}).status_code == 401
    assert client.post('/api/digitize/destinations', json={'path': 'relative'}).status_code == 422


def test_invalid_corners_fail_job_without_claiming_saved_pages(tmp_path):
    client=TestClient(create_app(tmp_path,token='test'));client.headers['Authorization']='Bearer test'
    sid=client.post('/api/digitize/sessions',json={}).json()['id']
    client.post(f'/api/digitize/sessions/{sid}/capture',files={'file':('photo.png',png(scene()),'image/png')},data={'options':'{"quads":[[[0,0],[9000,0],[100,200],[0,200]]]}'} )
    job=wait_ready(client,sid)['jobs'][0]
    assert job['status']=='failed'
    assert job['pages']==[]
