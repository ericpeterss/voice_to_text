#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — 一鍵打包 VoiceInput 成可攜式執行檔
Mac:     python build.py  →  產生 dist/VoiceInput.app
Windows: python build.py  →  產生 dist/VoiceInput.exe
"""

import sys
import os
import platform
import subprocess
import shutil

IS_MAC     = platform.system() == 'Darwin'
IS_WINDOWS = platform.system() == 'Windows'

MAIN_SCRIPT = 'voice_input.py'
APP_NAME    = 'VoiceInput'


def check_pyinstaller():
    try:
        import PyInstaller
        print(f'[build] PyInstaller {PyInstaller.__version__} 已安裝')
    except ImportError:
        print('[build] 安裝 PyInstaller...')
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)


def build():
    check_pyinstaller()

    # 清理舊的 build 目錄
    for d in ('build', 'dist', f'{APP_NAME}.spec'):
        if os.path.exists(d):
            if os.path.isdir(d):
                shutil.rmtree(d)
            else:
                os.remove(d)

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--clean',
        f'--name={APP_NAME}',
        '--windowed',          # 不顯示終端機視窗
        '--onefile',           # Mac 打包成單一二進制；Windows 打包成 .exe
    ]

    # ── macOS 額外設定 ──────────────────────────────
    if IS_MAC:
        # 單一 .app bundle
        cmd.remove('--onefile')
        cmd += [
            '--onedir',
            '--osx-bundle-identifier', 'com.voiceinput.app',
        ]
        # 如果有 .icns 圖示
        if os.path.exists('icon.icns'):
            cmd += ['--icon', 'icon.icns']

    # ── Windows 額外設定 ────────────────────────────
    if IS_WINDOWS:
        if os.path.exists('icon.ico'):
            cmd += ['--icon', 'icon.ico']
        # 隱藏 console
        cmd += ['--hide-console', 'hide-early']

    cmd.append(MAIN_SCRIPT)

    print(f'[build] 執行：{" ".join(cmd)}')
    result = subprocess.run(cmd)

    if result.returncode == 0:
        if IS_MAC:
            out = f'dist/{APP_NAME}.app'
        else:
            out = f'dist/{APP_NAME}.exe'
        print(f'\n✅ 打包完成！輸出：{out}')
        print('直接雙擊即可執行，不需要安裝任何環境。')
    else:
        print('\n❌ 打包失敗，請檢查上方錯誤訊息。')
        sys.exit(1)


if __name__ == '__main__':
    build()
