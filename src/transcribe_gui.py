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
import winsound
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

# Config storage - ALWAYS use AppData for consistency
CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "VoiceTranscribe"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
TRANSCRIPTS_FILE = CONFIG_DIR / "transcripts.log"

# Load .env from CONFIG_DIR (fixed location)
ENV_FILE = CONFIG_DIR / ".env"

# If .env doesn't exist in CONFIG_DIR, try to copy from project root
if not ENV_FILE.exists():
    source_env = PROJECT_ROOT / ".env"
    if source_env.exists():
        import shutil
        shutil.copy(source_env, ENV_FILE)

load_dotenv(ENV_FILE)

# Audio settings
RATE = 16000
CHUNK = 1024
PRE_ROLL_CHUNKS = int(0.5 * RATE / CHUNK)  # ~0.5s pre-buffer
POST_ROLL_CHUNKS = int(0.3 * RATE / CHUNK)  # ~0.3s post-buffer
MAX_CHUNK_SECONDS = 7 * 60  # 7 minutes - auto-transcribe to avoid API limits
MAX_CHUNK_FRAMES = int(MAX_CHUNK_SECONDS * RATE / CHUNK)
CHUNK_OVERLAP_CHUNKS = int(1.0 * RATE / CHUNK)  # ~1s overlap between chunks
MAX_RECORDING_SECONDS = 30 * 60  # 30 min safety limit - auto-stop to prevent runaway costs

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
chunking = False  # True when auto-transcribing a chunk mid-recording
recording_start_time = 0  # Track when recording started
audio_frames = []
pre_roll_buffer = []  # Always captures last ~0.5s for seamless start
full_transcript = []  # Accumulates chunks for long recordings
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
    global recording, audio_frames, pre_roll_buffer, chunking, recording_start_time

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)

    try:
        while True:
            # Always read audio to keep pre-roll buffer fresh
            data = stream.read(CHUNK, exception_on_overflow=False)

            if recording:
                audio_frames.append(data)

                # Safety: auto-stop at 30 minutes to prevent runaway costs
                if recording_start_time and (time.time() - recording_start_time) >= MAX_RECORDING_SECONDS:
                    # Loud alert - 3 beeps
                    for _ in range(3):
                        winsound.Beep(1000, 300)
                        time.sleep(0.1)
                    # Trigger stop from main thread
                    root.after(0, toggle_recording)
                    continue

                # Auto-chunk at 7 minutes to avoid API limits
                if len(audio_frames) >= MAX_CHUNK_FRAMES and not chunking:
                    chunking = True
                    # Keep overlap for seamless chunk boundaries
                    overlap = audio_frames[-CHUNK_OVERLAP_CHUNKS:]
                    frames_to_process = audio_frames[:-CHUNK_OVERLAP_CHUNKS] if CHUNK_OVERLAP_CHUNKS else audio_frames.copy()
                    audio_frames.clear()
                    audio_frames.extend(overlap)  # Start next chunk with overlap
                    threading.Thread(target=process_chunk, args=(frames_to_process,), daemon=True).start()
            else:
                # Keep circular pre-roll buffer
                pre_roll_buffer.append(data)
                if len(pre_roll_buffer) > PRE_ROLL_CHUNKS:
                    pre_roll_buffer.pop(0)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

def process_chunk(frames):
    """Transcribe a chunk mid-recording without stopping."""
    global chunking, full_transcript

    temp_file = save_audio_to_temp(frames)
    if not temp_file:
        chunking = False
        return

    transcriber = TRANSCRIBERS.get(current_model, transcribe_openai_mini)
    text, success = transcriber(temp_file)

    try:
        os.remove(temp_file)
    except:
        pass

    if success and text:
        with transcription_lock:
            full_transcript.append(text)

    chunking = False

def process_audio():
    global transcribing, audio_frames, full_transcript

    frames = audio_frames.copy()
    audio_frames.clear()

    # Transcribe final chunk if any
    final_text = ""
    if frames:
        temp_file = save_audio_to_temp(frames)
        if temp_file:
            transcriber = TRANSCRIBERS.get(current_model, transcribe_openai_mini)
            text, success = transcriber(temp_file)
            try:
                os.remove(temp_file)
            except:
                pass
            if success and text:
                final_text = text

    # Combine all chunks
    with transcription_lock:
        if final_text:
            full_transcript.append(final_text)
        combined_text = " ".join(full_transcript)
        full_transcript.clear()

    if combined_text:
        # Log transcript
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with TRANSCRIPTS_FILE.open("a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [{MODELS[current_model][0]}]\n{combined_text}\n\n")
        except:
            pass

        # Paste
        pyperclip.copy(combined_text)
        time.sleep(0.3)
        try:
            pyautogui.hotkey('ctrl', 'v')
        except:
            pass

    transcribing = False
    update_tray('idle')
    update_status("Ready")

def toggle_recording():
    global recording, transcribing, audio_frames, pre_roll_buffer, full_transcript, recording_start_time

    if transcribing:
        return

    # Check API key
    key_name = MODELS[current_model][1]
    if not get_api_key(key_name):
        update_status(f"Missing {key_name} in .env")
        return

    recording = not recording

    if recording:
        # Start recording: prepend pre-roll buffer for seamless start
        audio_frames.clear()
        full_transcript.clear()  # Clear any previous chunks
        audio_frames.extend(pre_roll_buffer)
        pre_roll_buffer.clear()
        recording_start_time = time.time()  # Track start for 30-min safety limit
        update_status("Recording...")
        record_btn.config(text="Stop", bg="#dc3545")
        update_tray('recording')
    else:
        # Stop recording: wait a bit for trailing audio (post-roll)
        update_status("Capturing...")
        record_btn.config(text="Record", bg="#28a745")

        def delayed_process():
            global transcribing
            time.sleep(0.3)  # Post-roll delay
            update_tray('transcribing')
            update_status("Transcribing...")
            transcribing = True
            process_audio()

        threading.Thread(target=delayed_process, daemon=True).start()

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
root.geometry("320x220")
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
hotkey_label.pack(pady=(5, 2))

# Show config location (clickable to open folder)
def open_config_folder(event=None):
    os.startfile(CONFIG_DIR)

env_exists = ENV_FILE.exists()
env_status = "OK" if env_exists else "MISSING"
config_path_label = tk.Label(root, text=f"Keys: .../{ENV_FILE.parent.name}/{ENV_FILE.name} [{env_status}]",
                             font=("Segoe UI", 7), bg="#1a1a2e",
                             fg="#28a745" if env_exists else "#dc3545",
                             cursor="hand2")
config_path_label.pack(pady=(0, 5))
config_path_label.bind("<Button-1>", open_config_folder)

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
