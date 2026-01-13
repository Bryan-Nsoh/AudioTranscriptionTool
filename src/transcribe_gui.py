"""
Voice Transcribe - Simple audio transcription tool
Gemini 3 Flash | Deepgram Nova-3 | OpenAI GPT-4o
"""

import os
import sys
import time
import json
import wave
import ctypes
import tempfile
import threading
from pathlib import Path
from datetime import datetime

import pyaudio
import keyboard
import pyautogui
import pyperclip
import pystray
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw
from pystray import MenuItem as item
from dotenv import load_dotenv

# Transcription providers
from deepgram import DeepgramClient
from openai import OpenAI

# Windows app ID
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('voicetranscribe.v3')
pyautogui.FAILSAFE = False

# -----------------------------------------------------
# Paths & Config
# -----------------------------------------------------

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE)

# Config storage
if getattr(sys, 'frozen', False):
    CONFIG_DIR = Path(os.getenv("APPDATA", PROJECT_ROOT)) / "VoiceTranscribe"
else:
    CONFIG_DIR = PROJECT_ROOT

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
TRANSCRIPTS_FILE = CONFIG_DIR / "transcripts.log"

# Audio settings
RATE = 16000
CHUNK = 1024

# Available models
MODELS = {
    "openai-mini": ("GPT-4o-mini-transcribe", "OPENAI_API_KEY"),
    "openai": ("GPT-4o-transcribe", "OPENAI_API_KEY"),
    "deepgram": ("Deepgram Nova-3", "DEEPGRAM_API_KEY"),
}

# -----------------------------------------------------
# Global State
# -----------------------------------------------------

recording = False
transcribing = False
audio_frames = []
transcription_buffer = ""
transcription_lock = threading.Lock()
tray_icon = None

# Config (loaded from file, keys from .env)
current_model = "openai-mini"
hotkey = "ctrl+space"

# -----------------------------------------------------
# Config Management
# -----------------------------------------------------

def load_config():
    global current_model, hotkey
    if CONFIG_FILE.is_file():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            saved_model = data.get("model", "openai-mini")
            # Validate model exists, fallback to default
            current_model = saved_model if saved_model in MODELS else "openai-mini"
            hotkey = data.get("hotkey", "ctrl+space")
        except:
            pass

def save_config():
    data = {"model": current_model, "hotkey": hotkey}
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_api_key(key_name):
    """Get API key from environment."""
    return os.getenv(key_name, "")

load_config()

# -----------------------------------------------------
# Tray Icon
# -----------------------------------------------------

def make_icon(color):
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img

icon_idle = make_icon((108, 117, 125, 255))      # gray
icon_recording = make_icon((220, 53, 69, 255))   # red
icon_transcribing = make_icon((40, 167, 69, 255)) # green

def update_tray(state='idle'):
    if tray_icon is None:
        return
    icons = {'idle': icon_idle, 'recording': icon_recording, 'transcribing': icon_transcribing}
    tray_icon.icon = icons.get(state, icon_idle)

def on_tray_toggle(icon, item):
    toggle_recording()

def on_tray_quit(icon, item):
    icon.stop()
    os._exit(0)

def setup_tray():
    global tray_icon
    menu = pystray.Menu(
        item('Toggle Recording', on_tray_toggle),
        item('Quit', on_tray_quit)
    )
    tray_icon = pystray.Icon("VoiceTranscribe", icon_idle, "Voice Transcribe", menu)
    tray_icon.run()

# -----------------------------------------------------
# Transcription Services
# -----------------------------------------------------

def save_audio_to_temp(frames):
    if not frames:
        return None
    try:
        filename = tempfile.mktemp(suffix=".wav")
        wf = wave.open(filename, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
        wf.close()
        return filename
    except:
        return None

def transcribe_openai_mini(filename):
    """OpenAI GPT-4o-mini transcription."""
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        return "OPENAI_API_KEY not set in .env", False
    try:
        client = OpenAI(api_key=api_key)
        with open(filename, "rb") as f:
            response = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=f,
                response_format="text",
                language="en"
            )
        return response, True
    except Exception as e:
        return f"OpenAI mini error: {e}", False

def transcribe_deepgram(filename):
    """Deepgram Nova-3 transcription."""
    api_key = get_api_key("DEEPGRAM_API_KEY")
    if not api_key:
        return "DEEPGRAM_API_KEY not set in .env", False
    try:
        client = DeepgramClient(api_key=api_key)
        with open(filename, "rb") as f:
            audio_data = f.read()

        response = client.listen.v1.media.transcribe_file(
            request=audio_data,
            model="nova-3",
            smart_format=True,
            language="en",
            punctuate=True,
        )
        return response.results.channels[0].alternatives[0].transcript, True
    except Exception as e:
        return f"Deepgram error: {e}", False

def transcribe_openai(filename):
    """OpenAI GPT-4o transcription."""
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        return "OPENAI_API_KEY not set in .env", False
    try:
        client = OpenAI(api_key=api_key)
        with open(filename, "rb") as f:
            response = client.audio.transcriptions.create(
                model="gpt-4o-transcribe",
                file=f,
                response_format="text",
                language="en"
            )
        return response, True
    except Exception as e:
        return f"OpenAI error: {e}", False

TRANSCRIBERS = {
    "openai-mini": transcribe_openai_mini,
    "openai": transcribe_openai,
    "deepgram": transcribe_deepgram,
}

# -----------------------------------------------------
# Recording & Processing
# -----------------------------------------------------

def record_audio():
    global recording, audio_frames

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)

    try:
        while True:
            if recording:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_frames.append(data)
            else:
                time.sleep(0.05)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

def process_audio():
    global transcribing, audio_frames, transcription_buffer

    frames = audio_frames.copy()
    audio_frames.clear()

    if not frames:
        transcribing = False
        update_tray('idle')
        update_status("Ready")
        return

    temp_file = save_audio_to_temp(frames)
    if not temp_file:
        transcribing = False
        update_tray('idle')
        update_status("Ready")
        return

    # Transcribe
    transcriber = TRANSCRIBERS.get(current_model, transcribe_openai_mini)
    text, success = transcriber(temp_file)

    # Cleanup
    try:
        os.remove(temp_file)
    except:
        pass

    if success and text:
        # Log transcript
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with TRANSCRIPTS_FILE.open("a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [{MODELS[current_model][0]}]\n{text}\n\n")
        except:
            pass

        # Paste
        pyperclip.copy(text)
        time.sleep(0.3)
        try:
            pyautogui.hotkey('ctrl', 'v')
        except:
            pass

    transcribing = False
    update_tray('idle')
    update_status("Ready")

def toggle_recording():
    global recording, transcribing, audio_frames

    if transcribing:
        return

    # Check API key
    key_name = MODELS[current_model][1]
    if not get_api_key(key_name):
        update_status(f"Missing {key_name} in .env")
        return

    recording = not recording

    if recording:
        audio_frames.clear()
        update_status("Recording...")
        record_btn.config(text="Stop", bg="#dc3545")
        update_tray('recording')
    else:
        update_status("Transcribing...")
        record_btn.config(text="Record", bg="#28a745")
        update_tray('transcribing')
        transcribing = True
        threading.Thread(target=process_audio, daemon=True).start()

# -----------------------------------------------------
# UI
# -----------------------------------------------------

def update_status(text):
    status_label.config(text=text)
    root.update_idletasks()

def change_model(event=None):
    global current_model
    selection = model_combo.get()
    for key, (name, _) in MODELS.items():
        if name == selection:
            current_model = key
            save_config()
            update_model_display()
            break

def update_model_display():
    model_name = MODELS[current_model][0]
    key_name = MODELS[current_model][1]
    has_key = bool(get_api_key(key_name))

    if has_key:
        model_status.config(text=f"Using: {model_name}", fg="#28a745")
    else:
        model_status.config(text=f"{model_name} - KEY MISSING", fg="#dc3545")

def on_close():
    root.destroy()
    os._exit(0)

# -----------------------------------------------------
# Main Window
# -----------------------------------------------------

root = tk.Tk()
root.title("Voice Transcribe")
root.geometry("320x200")
root.resizable(False, False)
root.configure(bg="#1a1a2e")

# Title
title = tk.Label(root, text="Voice Transcribe", font=("Segoe UI", 16, "bold"),
                 bg="#1a1a2e", fg="#eef")
title.pack(pady=(15, 5))

# Model selector
model_frame = tk.Frame(root, bg="#1a1a2e")
model_frame.pack(pady=5)

model_combo = ttk.Combobox(model_frame, values=[v[0] for v in MODELS.values()],
                           state="readonly", width=20, font=("Segoe UI", 10))
model_combo.set(MODELS[current_model][0])
model_combo.bind("<<ComboboxSelected>>", change_model)
model_combo.pack()

# Model status
model_status = tk.Label(root, text="", font=("Segoe UI", 9), bg="#1a1a2e")
model_status.pack(pady=(2, 10))
update_model_display()

# Record button
record_btn = tk.Button(root, text="Record", width=15, font=("Segoe UI", 12, "bold"),
                       bg="#28a745", fg="white", activebackground="#218838",
                       command=toggle_recording, relief="flat", cursor="hand2")
record_btn.pack(pady=5)

# Status
status_label = tk.Label(root, text="Ready", font=("Segoe UI", 10),
                        bg="#1a1a2e", fg="#888")
status_label.pack(pady=5)

# Hotkey hint
hotkey_label = tk.Label(root, text=f"Hotkey: {hotkey.replace('+', ' + ').title()}",
                        font=("Segoe UI", 8), bg="#1a1a2e", fg="#555")
hotkey_label.pack(pady=(5, 10))

root.protocol("WM_DELETE_WINDOW", on_close)

# -----------------------------------------------------
# Start
# -----------------------------------------------------

def start_app():
    # Recording thread
    threading.Thread(target=record_audio, daemon=True).start()

    # Tray
    threading.Thread(target=setup_tray, daemon=True).start()

    # Hotkey
    keyboard.add_hotkey(hotkey, toggle_recording)

start_app()
root.mainloop()
