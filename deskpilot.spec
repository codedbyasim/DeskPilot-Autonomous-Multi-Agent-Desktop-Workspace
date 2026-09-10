# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Specification for DeskPilot — Multi-Agent Windows Desktop Assistant
AWS 'Agents for Humans' Hackathon Build
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Base path of the repository
ROOT_DIR = os.path.abspath(SPECPATH)

# Data files to bundle: frontend HTML/CSS/JS, agent JSON definitions, app icons, sample data
datas = [
    (os.path.join(ROOT_DIR, 'frontend'), 'frontend'),
    (os.path.join(ROOT_DIR, 'agents'), 'agents'),
    (os.path.join(ROOT_DIR, 'assets'), 'assets'),
    (os.path.join(ROOT_DIR, 'sample_data'), 'sample_data'),
]

# Explicit hidden imports for pywebview, strands, boto3, document tools, and Flask API
hiddenimports = [
    'flask',
    'flask_cors',
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'clr_loader',
    'pythonnet',
    'strands',
    'strands.agent',
    'strands.models',
    'strands.models.bedrock',
    'strands.tools',
    'boto3',
    'botocore',
    'docx',
    'openpyxl',
    'pdfplumber',
    'fitz',
    'reportlab',
    'requests',
    'bs4',
    'lxml',
    'duckduckgo_search',
    'PIL',
    'PIL.Image',
    'pydantic',
    'dotenv',
]

# Collect backend submodules
hiddenimports += collect_submodules('backend')

# Collect boto3 and botocore data files (endpoints, service models)
try:
    datas += collect_data_files('botocore')
except Exception:
    pass

a = Analysis(
    [os.path.join(ROOT_DIR, 'main.py')],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pytest',
        'IPython',
        'jupyter',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'django',
        'sqlalchemy',
        'pandas',
        'pyarrow',
        'numba',
        'llvmlite',
        'distributed',
        'dask',
        'torch',
        'tensorflow',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DeskPilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT_DIR, 'assets', 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DeskPilot',
)
