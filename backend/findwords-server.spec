# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for FindWords backend server."""

import os
import sys

block_cipher = None

# Collect all app source files
app_datas = []
for root, dirs, files in os.walk('app'):
    for f in files:
        if f.endswith('.py'):
            src = os.path.join(root, f)
            dst = root
            app_datas.append((src, dst))

a = Analysis(
    ['run_server.py'],
    pathex=['.'],
    binaries=[],
    datas=app_datas,
    hiddenimports=[
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
        'fastapi',
        'starlette',
        'starlette.responses',
        'starlette.staticfiles',
        'pydantic',
        'pydantic_settings',
        'langchain',
        'langchain_openai',
        'langgraph',
        'opencc',
        'fitz',
        'pymupdf',
        'multipart',
        'httpx',
        'anyio',
        'sniffio',
        'httpcore',
        'h11',
        'certifi',
        'idna',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='findwords-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
