# Third-party notices

LumaScan code is MIT licensed. It originated from the scanner component authored in IamAngusU/ContextBridge-Keyring; no private repository history or captured objects are included.

`static/luma-transfer.js` retains the MIT-licensed LumaDrop transfer implementation from https://github.com/IamAngusU/liquid-camera-widget . Copyright (c) 2026 Angus Uelsmann. The MIT permission and warranty terms in this repository's LICENSE also apply to this retained implementation. The direct HTTPS phone client does not require PeerJS or external signaling.

DocAligner source and model releases: https://github.com/DocsaidLab/DocAligner , Apache-2.0. No upstream source implementation or weights are bundled here. The inference adapter implements the published input/output contract. The model is downloaded explicitly from the official release and checked against `model-catalog.json`.

RapidOCR: https://github.com/RapidAI/RapidOCR , Apache-2.0. Installed as a pinned optional dependency; the wheel's own license and bundled model notices apply. We verify its model files before inference and do not copy its source or weights into this repository. PP-OCR models originate from PaddleOCR/PaddleX and retain their upstream conditions.

OpenCV, ONNX Runtime, Pillow, reportlab, FastAPI, cryptography and other dependencies retain their own licenses. Installing a dependency does not change its license. Research candidates linked from README are not bundled or installed. Private family use does not waive redistribution obligations.
