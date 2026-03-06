# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for FindWords backend server."""

import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
IS_WINDOWS = sys.platform.startswith('win')
USE_STRIP = not IS_WINDOWS
USE_UPX = not IS_WINDOWS

# Collect data files for packages that need them
opencc_datas = collect_data_files('opencc')
paddleocr_datas = collect_data_files('paddleocr')
paddle_datas = collect_data_files('paddle', include_py_files=True)
selenium_datas = collect_data_files('selenium')

a = Analysis(
    ['run_server.py'],
    pathex=['.'],
    binaries=[],
    datas=opencc_datas + paddleocr_datas + paddle_datas + selenium_datas,
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
        # --- OCR (PaddleOCR) ---
        'paddleocr',
        'paddle',
        'paddle.utils',
        'paddle.dataset',
        'paddle.reader',
        'paddle.fluid',
        'shapely',
        'pyclipper',
        'imgaug',
        'lmdb',
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
    runtime_hooks=['hooks/rthook_cv2.py'],
    excludes=[
        # --- ML frameworks not used ---
        'nltk',
        'scipy',
        'pandas',
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook',
        'tensorflow',
        'torch',
        'torchvision',
        'tokenizers',
        'sklearn',
        'pytest',
        'setuptools.tests',
        'huggingface_hub',
        'e2b',
        'ray',
        'transformers',
        'pyarrow',
        'llvmlite',
        'numba',
        'spacy',
        'lightgbm',
        'statsmodels',
        'plotly',
        'faiss',
        'h5py',
        'skimage',
        'jieba',
        'pdfminer',
        'pikepdf',
        'grpc',
        'rapidocr_onnxruntime',
        'onnxruntime',
        # --- browser / automation (playwright not needed) ---
        'playwright',
        # --- cloud SDKs ---
        'botocore',
        'boto3',
        's3transfer',
        # --- crypto / encoding not needed ---
        'cryptography',
        'Crypto',
        'pycryptodome',
        # --- data / NLP tools not needed ---
        'lxml',
        'rapidfuzz',
        'pypdfium2',
        'onnx',
        'emoji',
        'Cython',
        'timm',
        'tiktoken',
        'pi_heif',
        'langdetect',
        # --- GUI / Tk not needed ---
        'tkinter',
        '_tkinter',
        'tcl',
        'tcl8',
        # --- telemetry / monitoring ---
        'opentelemetry',
        'sentry_sdk',
        # --- misc not needed ---
        'datasets',
        'altair',
        'pyecharts',
        'pycocotools',
        'flask',
        'werkzeug',
        'lightning',
        'fvcore',
        'redis',
        'pymilvus',
        'mcp',
        'ollama',
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
    strip=USE_STRIP,
    upx=USE_UPX,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=USE_STRIP,
    upx=USE_UPX,
    name='findwords-server',
)
