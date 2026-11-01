"""Isolated local reference-client QA, never the family archive."""
from pathlib import Path
import uvicorn
from lumascan.app import create_app
root=Path(__file__).resolve().parents[1]/'runtime/qa'
app=create_app(root,phone_origin='http://127.0.0.1:8774')
uvicorn.run(app,host='127.0.0.1',port=8774,access_log=False)
