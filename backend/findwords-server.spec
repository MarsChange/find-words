# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for FindWords backend server."""

import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Collect data files for packages that need them
opencc_datas = collect_data_files('opencc')
rapidocr_datas = collect_data_files('rapidocr_onnxruntime')
onnxruntime_datas = collect_data_files('onnxruntime')
selenium_datas = collect_data_files('selenium')

a = Analysis(
    ['run_server.py'],
    pathex=['.'],
    binaries=[],
    datas=opencc_datas + rapidocr_datas + onnxruntime_datas + selenium_datas,
    hiddenimports=[
        # --- uvicorn ---
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # --- web framework ---
        'fastapi',
        'starlette',
        'starlette.responses',
        'starlette.staticfiles',
        'pydantic',
        'pydantic_settings',
        'multipart',
        'aiofiles',
        'websockets',
        # --- http ---
        'httpx',
        'anyio',
        'sniffio',
        'httpcore',
        'h11',
        'certifi',
        'idna',
        # --- AI / LLM ---
        'langgraph',
        'openai',
        # --- document processing ---
        'opencc',
        'fitz',
        'pymupdf',
        # --- OCR (try/except import in pdf_processor.py) ---
        'rapidocr_onnxruntime',
        'rapidocr_onnxruntime.ch_ppocr_v3_det',
        'rapidocr_onnxruntime.ch_ppocr_v3_det.text_detect',
        'rapidocr_onnxruntime.ch_ppocr_v2_cls',
        'rapidocr_onnxruntime.ch_ppocr_v2_cls.text_cls',
        'rapidocr_onnxruntime.ch_ppocr_v3_rec',
        'rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize',
        'onnxruntime',
        'onnxruntime.capi',
        'onnxruntime.capi._pybind_state',
        'onnxruntime.capi._ld_preload',
        # --- selenium browser drivers (deferred imports in cbeta_scraper.py) ---
        'selenium',
        'selenium.webdriver',
        'selenium.webdriver.common',
        'selenium.webdriver.common.by',
        'selenium.webdriver.common.keys',
        'selenium.webdriver.common.action_chains',
        'selenium.webdriver.support',
        'selenium.webdriver.support.ui',
        'selenium.webdriver.support.wait',
        'selenium.webdriver.support.expected_conditions',
        'selenium.webdriver.chrome',
        'selenium.webdriver.chrome.webdriver',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.firefox',
        'selenium.webdriver.firefox.webdriver',
        'selenium.webdriver.firefox.options',
        'selenium.webdriver.firefox.service',
        'selenium.webdriver.edge',
        'selenium.webdriver.edge.webdriver',
        'selenium.webdriver.edge.options',
        'selenium.webdriver.edge.service',
        'selenium.webdriver.safari',
        'selenium.webdriver.safari.webdriver',
        'selenium.webdriver.safari.service',
        'selenium.webdriver.remote',
        'selenium.webdriver.remote.webdriver',
        'selenium.webdriver.remote.webelement',
        'selenium.common',
        'selenium.common.exceptions',
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_cv2.py', 'hooks/rthook_rapidocr.py'],
    excludes=[
        'nltk',
        'scipy',
        'pandas',
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook',
        'tensorflow',
        'torch',
        'sklearn',
        'pytest',
        'setuptools.tests',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ----------  ONE-DIR mode  ----------
# Binaries / data stay on disk alongside the executable instead of being
# packed into a single archive.  This eliminates the ~40 s extraction
# overhead that one-file mode causes on every launch.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='findwords-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=True,
    name='findwords-server',
)
