# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


# 현재 프로젝트의 최상위 폴더입니다.
PROJECT_ROOT = Path.cwd()

# Python 패키지가 들어 있는 src 폴더입니다.
SRC_DIR = PROJECT_ROOT / "src"

# 이미지, 아이콘 등의 프로그램 리소스가 들어 있는 폴더입니다.
ASSETS_DIR = PROJECT_ROOT / "assets"


a = Analysis(
    ["MemoMindAI.py"],

    # memomind 패키지가 src 안에 있으므로
    # PyInstaller가 src를 Python 모듈 검색 경로로 사용하도록 합니다.
    pathex=[str(SRC_DIR)],

    binaries=[],

    datas=[
        # assets 폴더 전체를 앱에 포함합니다.
        (str(ASSETS_DIR), "assets"),
    ],

    hiddenimports=[
        "memomind",
        "memomind.main",
        "memomind.config",
        "memomind.repository",
        "memomind.llm_client",
        "memomind.context_service",
        "memomind.handover",
        "memomind.logging_utils",
        "memomind.ui",
        "memomind.ui.app",
    ],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MemoMind_v1.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

app = BUNDLE(
    exe,
    name="MemoMind_v1.0.app",
    icon=str(ASSETS_DIR / "yang.ico"),
    bundle_identifier="com.memomind.ai",
)
