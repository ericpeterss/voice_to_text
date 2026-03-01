#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VoiceInput — 免安裝語音轉文字輸入工具
支援 Mac & Windows，中英文混合辨識
按住右 Command（Mac）/ 右 Ctrl（Windows）錄音，放開自動貼上到目前應用程式
"""

import sys
import os
import io
import wave
import threading
import time
import platform
import json
import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np

# ════════════════════════════════════════════════════════
#  常數
# ════════════════════════════════════════════════════════

IS_MAC     = platform.system() == 'Darwin'
IS_WINDOWS = platform.system() == 'Windows'

CONFIG_DIR  = os.path.join(os.path.expanduser('~'), '.voiceinput')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')

APP_VERSION = '1.0.0'

DEFAULT_CONFIG = {
    'openai_api_key':     '',
    'anthropic_api_key':  '',
    'sample_rate':        16000,
    'language':           'zh',          # whisper 以中文為主，英文自動辨識
    'post_process':       True,          # 啟用 LLM 後處理
    'whisper_model':      'whisper-1',
    'whisper_backend':    'local',       # 'local'（mlx-whisper）| 'cloud'（OpenAI API）
    'local_whisper_repo': 'mlx-community/whisper-medium-mlx-q4',
    'llm_backend':        'anthropic',   # 'anthropic' | 'openai'
    'custom_dict':        [],            # 自訂字典：指定特殊字詞的正確寫法
}

CLEANUP_SYSTEM_PROMPT = """你是專業的語音辨識文字後處理助手。
請整理使用者提供的語音辨識原始文字，並嚴格遵守以下規則：

1. **移除語助詞與填充詞**：嗯、哦、啊、欸、那個、這個、就是、然後、對對對、好那、所以說 等口語廢話
2. **修正明顯錯字**：根據語意修正語音辨識誤判的字詞
3. **整理句子流暢度**：把口語化的斷句、重複改寫為通順書面語，但**完全保留原意與語氣**
4. **保留英文**：英文專有名詞、技術術語、縮寫維持原樣，不翻譯
5. **繁體中文輸出**：所有中文使用繁體字
6. **只輸出結果**：不要加任何前言、說明、標籤或符號，直接給整理後的文字"""


# ════════════════════════════════════════════════════════
#  設定管理
# ════════════════════════════════════════════════════════

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                stored = json.load(f)
                return {**DEFAULT_CONFIG, **stored}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════
#  系統列圖示生成
# ════════════════════════════════════════════════════════

def create_icon(state: str = 'idle'):
    """
    state: 'idle' | 'recording' | 'processing'
    動態產生系統列麥克風圖示
    """
    from PIL import Image, ImageDraw

    SIZE  = 64
    img   = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(img)

    COLORS = {
        'idle':       (70,  145, 255, 255),   # 藍
        'recording':  (255,  55,  55, 255),   # 紅
        'processing': (255, 175,  30, 255),   # 橙
    }
    c = COLORS.get(state, COLORS['idle'])

    # 麥克風本體（圓角矩形）
    draw.rounded_rectangle([22, 4, 42, 34], radius=9, fill=c)

    # 底座弧線
    for w in range(3, 6):
        draw.arc([13, 20, 51, 50], start=0, end=180, fill=c, width=w)

    # 支柱
    draw.rectangle([30, 48, 34, 57], fill=c)

    # 底座橫條
    draw.rounded_rectangle([19, 57, 45, 62], radius=3, fill=c)

    return img


# ════════════════════════════════════════════════════════
#  音訊錄製
# ════════════════════════════════════════════════════════

class AudioRecorder:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._recording  = False
        self._frames     = []
        self._lock       = threading.Lock()
        self._stream     = None

    def start(self):
        import sounddevice as sd
        with self._lock:
            self._recording = True
            self._frames    = []
        self._stream = sd.InputStream(
            samplerate = self.sample_rate,
            channels   = 1,
            dtype      = 'float32',
            callback   = self._callback,
            blocksize  = 1024,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())

    def stop(self) -> 'io.BytesIO | None':
        with self._lock:
            self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._lock:
            if not self._frames:
                return None
            audio = np.concatenate(self._frames, axis=0).flatten()

        return self._encode_wav(audio)

    def _encode_wav(self, audio: np.ndarray) -> io.BytesIO:
        buf = io.BytesIO()
        pcm = (audio * 32767).astype(np.int16)
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm.tobytes())
        buf.seek(0)
        buf.name = 'audio.wav'
        return buf


# ════════════════════════════════════════════════════════
#  API 呼叫
# ════════════════════════════════════════════════════════

def transcribe(wav_buf: 'io.BytesIO', config: dict) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=config['openai_api_key'])
    result = client.audio.transcriptions.create(
        model          = config['whisper_model'],
        file           = ('audio.wav', wav_buf, 'audio/wav'),
        language       = config['language'],
        response_format = 'text',
    )
    return str(result).strip()


def post_process(raw_text: str, config: dict) -> str:
    """使用 Anthropic Claude 或 OpenAI GPT 整理辨識文字"""
    backend = config.get('llm_backend', 'anthropic')

    if backend == 'anthropic' and config.get('anthropic_api_key'):
        import anthropic as ant
        client  = ant.Anthropic(api_key=config['anthropic_api_key'])
        message = client.messages.create(
            model      = 'claude-haiku-4-5-20251001',
            max_tokens = 1024,
            system     = CLEANUP_SYSTEM_PROMPT,
            messages   = [{'role': 'user', 'content': raw_text}],
        )
        return message.content[0].text.strip()

    elif config.get('openai_api_key'):
        from openai import OpenAI
        client   = OpenAI(api_key=config['openai_api_key'])
        response = client.chat.completions.create(
            model       = 'gpt-4o-mini',
            temperature = 0.2,
            messages    = [
                {'role': 'system', 'content': CLEANUP_SYSTEM_PROMPT},
                {'role': 'user',   'content': raw_text},
            ],
        )
        return response.choices[0].message.content.strip()

    return raw_text   # fallback：不後處理


# ════════════════════════════════════════════════════════
#  剪貼簿注入
# ════════════════════════════════════════════════════════

def inject_text(text: str):
    """
    把文字寫入剪貼簿，然後模擬 Cmd+V / Ctrl+V
    貼到目前焦點應用程式的文字框
    """
    import pyperclip
    from pynput.keyboard import Controller, Key

    pyperclip.copy(text)
    time.sleep(0.15)   # 確保剪貼簿已更新

    kbd       = Controller()
    paste_key = Key.cmd if IS_MAC else Key.ctrl

    with kbd.pressed(paste_key):
        kbd.tap('v')


# ════════════════════════════════════════════════════════
#  狀態提示（macOS: 音效＋通知；Windows: Tkinter 浮動視窗）
# ════════════════════════════════════════════════════════

def _as_str(s: str) -> str:
    """將字串轉為 AppleScript 安全格式"""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


class StatusOverlay:
    """
    macOS — 使用系統音效＋通知中心，不產生任何視窗，
            徹底避免全螢幕 Space 切換問題。
    Windows — 使用 Tkinter 浮動視窗（子程序）。
    """

    def __init__(self):
        self._proc = None          # Windows Tkinter overlay 子程序

    def start(self):
        if not IS_MAC:
            import subprocess
            script = os.path.abspath(sys.modules[__name__].__file__)
            self._proc = subprocess.Popen(
                [sys.executable, script, '--overlay'],
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

    def update(self, state: str, text: str = ''):
        """state: 'recording' | 'processing' | 'result' | 'error' | 'idle'"""
        if IS_MAC:
            self._update_mac(state, text)
        elif self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(f'{state}|{text}\n')
                self._proc.stdin.flush()
            except Exception:
                pass

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write('quit|\n')
                self._proc.stdin.flush()
            except Exception:
                pass
            self._proc = None

    # ── macOS 原生提示 ─────────────────────────────────

    def _update_mac(self, state: str, text: str):
        import subprocess as sp
        if state == 'recording':
            sp.Popen(['afplay', '/System/Library/Sounds/Morse.aiff'])
        elif state == 'processing':
            sp.Popen(['afplay', '/System/Library/Sounds/Pop.aiff'])
        elif state == 'result':
            sp.Popen(['afplay', '/System/Library/Sounds/Glass.aiff'])
            display = text[:120]
            sp.Popen([
                'osascript', '-e',
                f'display notification {_as_str(display)} '
                f'with title "✅ VoiceInput" subtitle "已貼上"',
            ])
        elif state == 'error':
            sp.Popen(['afplay', '/System/Library/Sounds/Basso.aiff'])
            display = str(text)[:120]
            sp.Popen([
                'osascript', '-e',
                f'display notification {_as_str(display)} '
                f'with title "❌ VoiceInput" subtitle "錯誤"',
            ])


def _run_overlay():
    """Windows 用子程序入口：顯示浮動狀態提示條"""
    import queue as _queue

    root = tk.Tk()
    root.title('')
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.withdraw()

    frame = tk.Frame(root, bg='#333333', highlightthickness=0)
    frame.pack(padx=0, pady=0)
    label = tk.Label(
        frame, text='', font=('', 16), fg='white', bg='#333333',
        padx=24, pady=10,
    )
    label.pack()

    screen_w = root.winfo_screenwidth()
    msg_q    = _queue.Queue()
    hide_job = [None]

    def _read_stdin():
        try:
            for line in sys.stdin:
                msg_q.put(line.strip())
        except Exception:
            pass
        msg_q.put('quit|')

    threading.Thread(target=_read_stdin, daemon=True).start()

    def _reposition():
        root.update_idletasks()
        w = root.winfo_width()
        x = (screen_w - w) // 2
        root.geometry(f'+{x}+50')

    def _poll():
        try:
            while True:
                msg = msg_q.get_nowait()
                parts = msg.split('|', 1)
                state = parts[0]
                text  = parts[1] if len(parts) > 1 else ''

                if state == 'quit':
                    root.destroy()
                    return

                if hide_job[0]:
                    root.after_cancel(hide_job[0])
                    hide_job[0] = None

                if state == 'recording':
                    label.config(text='  🎙 錄音中...  ', bg='#cc2222')
                    frame.config(bg='#cc2222')
                    root.deiconify()
                    _reposition()
                elif state == 'processing':
                    label.config(text='  ⏳ 處理中...  ', bg='#cc8800')
                    frame.config(bg='#cc8800')
                    root.deiconify()
                    _reposition()
                elif state == 'result':
                    display = text[:50] + '...' if len(text) > 50 else text
                    label.config(text=f'  ✅ {display}  ', bg='#2d8a4e')
                    frame.config(bg='#2d8a4e')
                    root.deiconify()
                    _reposition()
                    hide_job[0] = root.after(3000, root.withdraw)
                elif state == 'error':
                    display = text[:50] + '...' if len(text) > 50 else text
                    label.config(text=f'  ❌ {display}  ', bg='#cc2222')
                    frame.config(bg='#cc2222')
                    root.deiconify()
                    _reposition()
                    hide_job[0] = root.after(4000, root.withdraw)
                elif state == 'idle':
                    root.withdraw()
        except _queue.Empty:
            pass
        root.after(50, _poll)

    root.after(100, _poll)
    root.mainloop()


# ════════════════════════════════════════════════════════
#  快捷鍵管理（按住錄音 / 放開停止）
# ════════════════════════════════════════════════════════

class HotkeyManager:
    """
    監聽右 Command 鍵（Mac）/ 右 Ctrl 鍵（Windows）
    按住 → on_start；放開 → on_stop
    """

    def __init__(self, on_start, on_stop):
        self.on_start    = on_start
        self.on_stop     = on_stop
        self._active     = False
        self._lock       = threading.Lock()
        self._listener   = None

    def start(self):
        from pynput import keyboard as kb
        self._listener = kb.Listener(
            on_press   = self._press,
            on_release = self._release,
            suppress   = False,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()

    # ── 內部 ──────────────────────────────────────────

    def _is_hotkey(self, key) -> bool:
        from pynput.keyboard import Key
        if IS_MAC:
            return key == Key.cmd_r
        else:
            return key == Key.ctrl_r

    def _press(self, key):
        with self._lock:
            if self._is_hotkey(key) and not self._active:
                self._active = True
                threading.Thread(target=self.on_start, daemon=True).start()

    def _release(self, key):
        with self._lock:
            if self._is_hotkey(key) and self._active:
                self._active = False
                threading.Thread(target=self.on_stop, daemon=True).start()


# ════════════════════════════════════════════════════════
#  設定視窗
# ════════════════════════════════════════════════════════

class SettingsWindow:
    """
    設定視窗（以獨立程序模式執行，避免 macOS 上 Tkinter 與 pystray 的主執行緒衝突）
    使用方式：python voice_input.py --settings
    """

    def __init__(self, config: dict, on_save=None):
        self.config   = config
        self.on_save  = on_save or (lambda c: None)
        self._win     = None

    def show(self):
        self._win = tk.Tk()
        self._win.title('VoiceInput 設定')
        self._win.geometry('500x680')
        self._win.resizable(False, False)
        self._saved = False   # 追蹤是否已儲存

        if IS_MAC:
            try:
                style = ttk.Style()
                style.theme_use('aqua')
            except Exception:
                pass

        self._build_ui()
        self._win.protocol('WM_DELETE_WINDOW', self._on_close)
        self._win.mainloop()

    def _on_close(self):
        """視窗關閉時，若尚未儲存則提醒"""
        if not self._saved:
            answer = messagebox.askyesnocancel(
                'VoiceInput',
                '尚未儲存設定，要先儲存嗎？',
            )
            if answer is True:       # 「是」→ 先儲存再關閉
                self._save()
                return
            elif answer is None:     # 「取消」→ 不關閉
                return
            # answer is False →「否」→ 直接關閉
        self._win.destroy()

    # ── UI ────────────────────────────────────────────

    def _build_ui(self):
        root = self._win
        pad  = dict(padx=24, pady=6)

        # ─ 按鈕（先 pack 到底部，確保不被擠出畫面）─
        btn_frame = ttk.Frame(root)
        btn_frame.pack(side='bottom', fill='x', padx=20, pady=12)
        ttk.Button(btn_frame, text='❌ 取消',
                   command=self._on_close).pack(side='right', padx=(8, 0))
        ttk.Button(btn_frame, text='💾 儲存設定',
                   command=self._save).pack(side='right')

        # ─ 快捷鍵說明（底部第二層）─
        hotkey = '右 Command' if IS_MAC else '右 Ctrl'
        ttk.Label(root, text=f'⌨  快捷鍵：按住 {hotkey} 說話，放開後自動貼上',
                  foreground='#666').pack(side='bottom', anchor='w', padx=24, pady=(0, 8))
        ttk.Separator(root, orient='horizontal').pack(side='bottom', fill='x', padx=20, pady=(4, 4))

        # ─ 標題 ─
        ttk.Label(root, text='🎙 VoiceInput 設定',
                  font=('', 16, 'bold')).pack(anchor='w', padx=24, pady=(20, 4))
        ttk.Label(root, text=f'v{APP_VERSION}',
                  foreground='gray').pack(anchor='w', padx=24, pady=(0, 8))
        ttk.Separator(root, orient='horizontal').pack(fill='x', padx=20, pady=(0, 12))

        # ─ 語音辨識引擎 ─
        self._whisper_var = tk.StringVar(value=self.config.get('whisper_backend', 'local'))
        whisper_frame = ttk.Frame(root)
        whisper_frame.pack(anchor='w', padx=24, pady=(0, 8))
        ttk.Label(whisper_frame, text='語音辨識：').pack(side='left')
        ttk.Radiobutton(whisper_frame, text='💻 本地（mlx-whisper）',
                        variable=self._whisper_var, value='local').pack(side='left', padx=6)
        ttk.Radiobutton(whisper_frame, text='☁️ 雲端（OpenAI API）',
                        variable=self._whisper_var, value='cloud').pack(side='left', padx=6)

        # ─ OpenAI Key ─
        ttk.Label(root, text='OpenAI API Key（雲端辨識或 GPT 後處理時需要）：').pack(anchor='w', **pad)
        self._openai_var = tk.StringVar(value=self.config.get('openai_api_key', ''))
        self._openai_entry = ttk.Entry(root, textvariable=self._openai_var,
                                        width=52, show='•')
        self._openai_entry.pack(anchor='w', padx=24, pady=(0, 4))
        ttk.Button(root, text='顯示 / 隱藏',
                   command=lambda: self._toggle_show(self._openai_entry)
                   ).pack(anchor='w', padx=24, pady=(0, 8))

        # ─ Anthropic Key ─
        ttk.Label(root, text='Anthropic API Key（Claude 後處理時需要）：').pack(anchor='w', **pad)
        self._ant_var = tk.StringVar(value=self.config.get('anthropic_api_key', ''))
        self._ant_entry = ttk.Entry(root, textvariable=self._ant_var,
                                     width=52, show='•')
        self._ant_entry.pack(anchor='w', padx=24, pady=(0, 4))
        ttk.Button(root, text='顯示 / 隱藏',
                   command=lambda: self._toggle_show(self._ant_entry)
                   ).pack(anchor='w', padx=24, pady=(0, 8))

        # ─ 後處理開關 ─
        self._pp_var = tk.BooleanVar(value=self.config.get('post_process', True))
        ttk.Checkbutton(root,
            text='✅ 啟用智慧後處理（移除語助詞・整理句子）',
            variable=self._pp_var).pack(anchor='w', padx=24, pady=(0, 4))

        # ─ 後處理模型 ─
        self._backend_var = tk.StringVar(value=self.config.get('llm_backend', 'anthropic'))
        backend_frame = ttk.Frame(root)
        backend_frame.pack(anchor='w', padx=24, pady=(0, 8))
        ttk.Label(backend_frame, text='後處理模型：').pack(side='left')
        ttk.Radiobutton(backend_frame, text='Claude（Anthropic）',
                        variable=self._backend_var, value='anthropic').pack(side='left', padx=6)
        ttk.Radiobutton(backend_frame, text='GPT-4o mini（OpenAI）',
                        variable=self._backend_var, value='openai').pack(side='left', padx=6)

        # ─ 自訂字典（填滿剩餘空間）─
        ttk.Label(root, text='自訂字典（一行一個詞，如人名、專有名詞）：').pack(anchor='w', **pad)
        dict_frame = ttk.Frame(root)
        dict_frame.pack(anchor='w', padx=24, pady=(0, 8), fill='both', expand=True)
        self._dict_text = tk.Text(dict_frame, height=4, width=50, font=('', 12))
        dict_scroll = ttk.Scrollbar(dict_frame, orient='vertical',
                                     command=self._dict_text.yview)
        self._dict_text.configure(yscrollcommand=dict_scroll.set)
        self._dict_text.pack(side='left', fill='both', expand=True)
        dict_scroll.pack(side='right', fill='y')
        # 載入現有字典
        existing = self.config.get('custom_dict', [])
        if existing:
            self._dict_text.insert('1.0', '\n'.join(existing))

    def _toggle_show(self, entry: ttk.Entry):
        entry.config(show='' if entry['show'] == '•' else '•')

    def _save(self):
        # 解析字典文字框：每行一個詞，去掉空行和前後空白
        dict_raw = self._dict_text.get('1.0', 'end-1c')
        custom_dict = [w.strip() for w in dict_raw.splitlines() if w.strip()]

        self.config.update({
            'openai_api_key':    self._openai_var.get().strip(),
            'anthropic_api_key': self._ant_var.get().strip(),
            'whisper_backend':   self._whisper_var.get(),
            'post_process':      self._pp_var.get(),
            'llm_backend':       self._backend_var.get(),
            'custom_dict':       custom_dict,
        })
        save_config(self.config)
        self._saved = True
        self.on_save(self.config)
        messagebox.showinfo('VoiceInput', '✅ 設定已儲存！')
        self._win.destroy()


# ════════════════════════════════════════════════════════
#  主應用程式
# ════════════════════════════════════════════════════════

class VoiceInputApp:
    def __init__(self):
        self.config      = load_config()
        self.recorder    = AudioRecorder(sample_rate=self.config['sample_rate'])
        self.tray        = None
        self._state      = 'idle'
        self._state_lock = threading.Lock()
        self._openai_client    = None
        self._anthropic_client = None
        self._settings_proc    = None       # 設定視窗子程序
        self._overlay          = StatusOverlay()
        self._frontmost_bundle = None       # 錄音前的焦點 App（macOS）

    # ── 啟動 ──────────────────────────────────────────

    def run(self):
        import pystray

        # 啟動浮動狀態指示器
        self._overlay.start()

        # 第一次啟動，自動開啟設定（子程序）
        if not self._has_required_keys():
            self._open_settings()

        # 建立快捷鍵監聽
        self._hotkey = HotkeyManager(
            on_start = self._on_record_start,
            on_stop  = self._on_record_stop,
        )
        self._hotkey.start()

        # 建立系統列（在主執行緒執行）
        hotkey_label = '右 Command' if IS_MAC else '右 Ctrl'
        menu = pystray.Menu(
            pystray.MenuItem('🎙 VoiceInput', None, enabled=False),
            pystray.MenuItem(f'快捷鍵：按住{hotkey_label}錄音', None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('⚙️  設定 / API Key', self._menu_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('❌  結束', self._menu_quit),
        )

        self.tray = pystray.Icon(
            name    = 'VoiceInput',
            icon    = create_icon('idle'),
            title   = f'🎙 VoiceInput — 按住{hotkey_label}錄音',
            menu    = menu,
        )

        print(f'[VoiceInput] v{APP_VERSION} 啟動完成')
        print(f'[VoiceInput] 按住{"右 Command" if IS_MAC else "右 Ctrl"}開始說話')
        self.tray.run()

    # ── 錄音回呼 ──────────────────────────────────────

    def _on_record_start(self):
        if not self._has_required_keys():
            self._warn_no_key()
            return

        with self._state_lock:
            if self._state != 'idle':
                # 上一次還在處理中，忽略本次
                print('[VoiceInput] ⏳ 上一次尚在處理，請稍候...')
                return
            self._state = 'recording'

        # ❶ 先播音效（非阻塞，立即聽到）
        self._overlay.update('recording')
        if self.tray:
            self.tray.icon = create_icon('recording')
        print('[VoiceInput] 🎙 錄音中...')

        # ❷ 記住當前焦點 App（osascript 阻塞約 0.3s，放在音效後面）
        self._save_frontmost_app()

        # ❸ 開始錄音
        self.recorder.start()

    def _on_record_stop(self):
        with self._state_lock:
            if self._state != 'recording':
                return
            self._state = 'processing'

        if self.tray:
            self.tray.icon = create_icon('processing')
        self._overlay.update('processing')
        print('[VoiceInput] ⏹ 停止錄音，處理中...')

        wav_buf = self.recorder.stop()
        if wav_buf is None or wav_buf.getbuffer().nbytes < 5000:
            # 太短 / 無聲，忽略
            self._overlay.update('idle')
            self._set_state('idle')
            return

        try:
            # ① Whisper 辨識
            raw = self._transcribe(wav_buf)
            print(f'[VoiceInput] 📝 原始辨識：{raw}')

            if not raw.strip():
                self._set_state('idle')
                return

            # ② LLM 後處理
            if self.config.get('post_process'):
                final = self._post_process(raw)
            else:
                final = raw
            print(f'[VoiceInput] ✨ 最終文字：{final}')

            # ③ 切回原本的 App 再貼上
            self._restore_frontmost_app()
            inject_text(final)
            self._overlay.update('result', final)
            print('[VoiceInput] 📋 已貼上！')

        except Exception as e:
            self._overlay.update('error', str(e))
            print(f'[VoiceInput] ❌ 錯誤：{e}')

        finally:
            self._set_state('idle')

    # ── 輔助 ──────────────────────────────────────────

    def _has_required_keys(self) -> bool:
        """檢查是否有足夠的 API Key"""
        whisper_ok = True
        llm_ok     = True

        # 語音辨識需要 key 嗎？
        if self.config.get('whisper_backend') == 'cloud':
            whisper_ok = bool(self.config.get('openai_api_key'))

        # 後處理需要 key 嗎？
        if self.config.get('post_process'):
            backend = self.config.get('llm_backend', 'anthropic')
            if backend == 'anthropic':
                llm_ok = bool(self.config.get('anthropic_api_key'))
            else:
                llm_ok = bool(self.config.get('openai_api_key'))

        return whisper_ok and llm_ok

    def _set_state(self, state: str):
        with self._state_lock:
            self._state = state
        if self.tray:
            self.tray.icon = create_icon(state)

    def _save_frontmost_app(self):
        """記住目前最前方 App 的 bundle ID（macOS 專用）"""
        if IS_MAC:
            import subprocess
            try:
                result = subprocess.run(
                    ['osascript', '-e',
                     'tell application "System Events" to get bundle '
                     'identifier of first application process whose '
                     'frontmost is true'],
                    capture_output=True, text=True, timeout=2,
                )
                self._frontmost_bundle = result.stdout.strip()
            except Exception:
                self._frontmost_bundle = None

    def _restore_frontmost_app(self):
        """將焦點切回錄音前的 App（確保貼上到正確位置）"""
        if IS_MAC and self._frontmost_bundle:
            import subprocess
            try:
                subprocess.run(
                    ['osascript', '-e',
                     f'tell application id "{self._frontmost_bundle}" '
                     f'to activate'],
                    timeout=2,
                )
                time.sleep(0.3)   # 等 App 完成切回
            except Exception:
                pass

    def _get_openai_client(self):
        if self._openai_client is None:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self.config['openai_api_key'])
        return self._openai_client

    def _get_anthropic_client(self):
        if self._anthropic_client is None:
            import anthropic as ant
            self._anthropic_client = ant.Anthropic(api_key=self.config['anthropic_api_key'])
        return self._anthropic_client

    def _reset_clients(self):
        self._openai_client    = None
        self._anthropic_client = None

    def _transcribe(self, wav_buf: 'io.BytesIO') -> str:
        backend = self.config.get('whisper_backend', 'local')

        if backend == 'local':
            return self._transcribe_local(wav_buf)
        else:
            return self._transcribe_cloud(wav_buf)

    def _transcribe_cloud(self, wav_buf: 'io.BytesIO') -> str:
        """雲端辨識：OpenAI Whisper API"""
        client = self._get_openai_client()

        kwargs = dict(
            model           = self.config['whisper_model'],
            file            = ('audio.wav', wav_buf, 'audio/wav'),
            language        = self.config['language'],
            response_format = 'text',
        )
        custom_dict = self.config.get('custom_dict', [])
        if custom_dict:
            kwargs['prompt'] = '、'.join(custom_dict)

        result = client.audio.transcriptions.create(**kwargs)
        return str(result).strip()

    def _transcribe_local(self, wav_buf: 'io.BytesIO') -> str:
        """本地辨識：mlx-whisper（Apple Silicon GPU 加速）"""
        import tempfile
        import mlx_whisper

        # mlx_whisper 需要檔案路徑，將 BytesIO 寫入暫存檔
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            f.write(wav_buf.read())
            temp_path = f.name

        try:
            repo = self.config.get(
                'local_whisper_repo',
                'mlx-community/whisper-medium-mlx-q4',
            )

            kwargs = dict(
                path_or_hf_repo = repo,
                language        = self.config['language'],
                verbose         = False,
            )
            custom_dict = self.config.get('custom_dict', [])
            if custom_dict:
                kwargs['initial_prompt'] = '、'.join(custom_dict)

            result = mlx_whisper.transcribe(temp_path, **kwargs)
            return result.get('text', '').strip()
        finally:
            os.unlink(temp_path)

    def _build_system_prompt(self) -> str:
        """根據自訂字典動態組合 system prompt"""
        prompt = CLEANUP_SYSTEM_PROMPT
        custom_dict = self.config.get('custom_dict', [])
        if custom_dict:
            terms = '、'.join(custom_dict)
            prompt += (
                f'\n7. **專有名詞字典**：以下字詞是使用者指定的正確寫法，'
                f'遇到同音或近音詞時必須替換為指定用字：{terms}'
            )
        return prompt

    def _post_process(self, raw_text: str) -> str:
        backend = self.config.get('llm_backend', 'anthropic')
        system_prompt = self._build_system_prompt()

        if backend == 'anthropic' and self.config.get('anthropic_api_key'):
            client  = self._get_anthropic_client()
            message = client.messages.create(
                model      = 'claude-haiku-4-5-20251001',
                max_tokens = 1024,
                system     = system_prompt,
                messages   = [{'role': 'user', 'content': raw_text}],
            )
            return message.content[0].text.strip()

        elif self.config.get('openai_api_key'):
            client   = self._get_openai_client()
            response = client.chat.completions.create(
                model       = 'gpt-4o-mini',
                temperature = 0.2,
                messages    = [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user',   'content': raw_text},
                ],
            )
            return response.choices[0].message.content.strip()

        return raw_text

    def _warn_no_key(self):
        """顯示警告：未設定 API Key"""
        print('[VoiceInput] ⚠️ 尚未設定 OpenAI API Key！請右鍵點擊系統列圖示 → 設定')
        if IS_MAC:
            os.system(
                'osascript -e \'display notification '
                '"請右鍵點擊系統列圖示 → 設定 / API Key" '
                'with title "VoiceInput" subtitle "尚未設定 API Key"\''
            )

    def _open_settings(self):
        """以子程序啟動設定視窗（避免 macOS 上 Tkinter 與 pystray 主執行緒衝突）"""
        import subprocess

        # 如果設定子程序已在執行，不重複開啟
        if self._settings_proc and self._settings_proc.poll() is None:
            return

        script = os.path.abspath(__file__)
        self._settings_proc = subprocess.Popen(
            [sys.executable, script, '--settings']
        )

        # 背景等待子程序結束，然後重新載入設定
        def _wait():
            self._settings_proc.wait()
            self.config = load_config()
            self._reset_clients()
            print('[VoiceInput] ✅ 設定已重新載入')
        threading.Thread(target=_wait, daemon=True).start()

    def _menu_settings(self, icon=None, item=None):
        self._open_settings()

    def _menu_quit(self, icon=None, item=None):
        self._overlay.stop()
        self._hotkey.stop()
        if self.tray:
            self.tray.stop()
        sys.exit(0)


# ════════════════════════════════════════════════════════
#  入口點
# ════════════════════════════════════════════════════════

if __name__ == '__main__':
    if '--settings' in sys.argv:
        # 獨立設定視窗模式（由主程序以子程序啟動）
        config = load_config()
        SettingsWindow(config).show()
    elif '--overlay' in sys.argv:
        # 浮動狀態指示器模式（由主程序以子程序啟動）
        _run_overlay()
    else:
        app = VoiceInputApp()
        app.run()
