"""
Audio Transcription Tool v2.0
Modern Windows-only transcription with OpenAI, Groq, and Gemini support.
Includes WebRTC-VAD for intelligent silence detection.
"""

import os
import sys
import time
import json
import wave
import ctypes
import random
import tempfile
import threading
from pathlib import Path

import webrtcvad
import pyaudio
import keyboard
import pyautogui
import pyperclip
import pystray
import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageDraw
from pystray import MenuItem as item
from openai import OpenAI
from groq import Groq
import google.generativeai as genai

# Windows app ID for taskbar
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('audiotranscriptiontool.v2')

# Disable PyAutoGUI fail-safe
pyautogui.FAILSAFE = False

# -----------------------------------------------------
# Configuration
# -----------------------------------------------------

APP_ROOT = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

if getattr(sys, 'frozen', False):
    appdata_dir = os.getenv("APPDATA")
    if appdata_dir:
        BASE_DIR = os.path.join(appdata_dir, "AudioTranscriptionTool")
    else:
        BASE_DIR = APP_ROOT
else:
    BASE_DIR = APP_ROOT

os.makedirs(BASE_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# Audio constants
BATCH_DURATION_SECONDS = 180
RATE = 16000
VAD_FRAME_DURATION_MS = 30  # WebRTC-VAD frame duration (10, 20, or 30 ms)
CHUNK = int((RATE * VAD_FRAME_DURATION_MS) / 1000)  # 480 samples at 16kHz (~30 ms)
VAD_FRAME_SIZE_BYTES = CHUNK * 2  # 16-bit mono PCM -> 960 bytes
FRAMES_PER_BATCH = int((RATE * BATCH_DURATION_SECONDS) / CHUNK)
POST_STOP_EXTRA_CHUNKS = 4  # Capture a short tail after stopping to avoid clipped speech

# Hotkey options
HOTKEY_OPTIONS = [
    ("Alt+R", "alt+r"),
    ("Ctrl+R", "ctrl+r"),
    ("Ctrl+Alt+Shift+R", "ctrl+alt+shift+r"),
]

SERVICE_OPTIONS = [
    ("Auto (OpenAI -> Groq -> Gemini)", "auto"),
    ("OpenAI Only", "openai"),
    ("Groq Only", "groq"),
    ("Gemini Only", "gemini"),
]

# Global state
recording = False
transcribing = False
audio_frames = []
current_batch_frames = []
transcription_buffer = ""
transcription_lock = threading.Lock()
vad_model = None
post_stop_chunks = 0
stop_requested = False

# API keys (loaded from config)
OPENAI_API_KEY = None
GROQ_API_KEY = None
GEMINI_API_KEY = None
HOTKEY = "alt+r"
VAD_AGGRESSIVENESS = 2  # Default VAD aggressiveness (0-3, higher = more aggressive)
SELECTED_SERVICE = "auto"


def resource_path(filename):
    """Resolve resource path for bundled/frozen builds."""
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', APP_ROOT)
    else:
        base_path = APP_ROOT
    return os.path.join(base_path, filename)

# -----------------------------------------------------
# WebRTC-VAD Setup
# -----------------------------------------------------

def load_vad_model():
    """Initialize WebRTC-VAD."""
    global vad_model
    try:
        vad_model = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        return True
    except Exception as e:
        print(f"Failed to load VAD: {e}")
        return False

def is_speech(audio_chunk, aggressiveness=2):
    """
    Detect if audio chunk contains speech using WebRTC-VAD.
    Returns True if speech detected, False otherwise.
    """
    if vad_model is None or aggressiveness <= 0:
        return True  # If VAD not loaded, assume all audio is speech

    try:
        # WebRTC VAD expects specific frame sizes for 16kHz: 160, 320, or 480 samples
        # For 30ms at 16kHz, we expect 480 samples -> 960 bytes for int16 mono
        if len(audio_chunk) != VAD_FRAME_SIZE_BYTES:
            return True  # If wrong size, don't filter

        vad_model.set_mode(int(aggressiveness))

        return vad_model.is_speech(audio_chunk, RATE)
    except Exception:
        return True  # On error, don't filter

# -----------------------------------------------------
# Config Management
# -----------------------------------------------------

def load_config():
    """Load configuration from JSON file."""
    if not os.path.isfile(CONFIG_FILE):
        return {
            "OPENAI_API_KEY": "",
            "GROQ_API_KEY": "",
            "GEMINI_API_KEY": "",
            "HOTKEY": "alt+r",
            "VAD_AGGRESSIVENESS": 2,
            "SELECTED_SERVICE": "auto"
        }
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("OPENAI_API_KEY", "")
        data.setdefault("GROQ_API_KEY", "")
        data.setdefault("GEMINI_API_KEY", "")
        data.setdefault("HOTKEY", "alt+r")
        data.setdefault("SELECTED_SERVICE", "auto")
        try:
            data["VAD_AGGRESSIVENESS"] = int(data.get("VAD_AGGRESSIVENESS", 2))
        except (TypeError, ValueError):
            data["VAD_AGGRESSIVENESS"] = 2
        return data
    except Exception:
        return {
            "OPENAI_API_KEY": "",
            "GROQ_API_KEY": "",
            "GEMINI_API_KEY": "",
            "HOTKEY": "alt+r",
            "VAD_AGGRESSIVENESS": 2,
            "SELECTED_SERVICE": "auto"
        }

def save_config(openai_key, groq_key, gemini_key, hotkey_value, vad_aggressiveness, selected_service):
    """Save configuration to JSON file."""
    data = {
        "OPENAI_API_KEY": openai_key.strip(),
        "GROQ_API_KEY": groq_key.strip(),
        "GEMINI_API_KEY": gemini_key.strip(),
        "HOTKEY": hotkey_value,
        "VAD_AGGRESSIVENESS": int(vad_aggressiveness),
        "SELECTED_SERVICE": selected_service
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# Load initial config
config_data = load_config()
OPENAI_API_KEY = config_data["OPENAI_API_KEY"]
GROQ_API_KEY = config_data["GROQ_API_KEY"]
GEMINI_API_KEY = config_data["GEMINI_API_KEY"]
HOTKEY = config_data["HOTKEY"]
VAD_AGGRESSIVENESS = config_data["VAD_AGGRESSIVENESS"]
SELECTED_SERVICE = config_data.get("SELECTED_SERVICE", "auto")

# -----------------------------------------------------
# Tray Icon
# -----------------------------------------------------


def _hex_to_rgb(hex_color):
    """Convert HEX color string to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _generate_status_icon(color_hex):
    """Create a clean circular status icon in the requested solid color."""
    size = 64
    icon = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    rgb = _hex_to_rgb(color_hex)
    draw.ellipse((8, 8, 56, 56), fill=rgb + (255,))
    return icon


icon_idle = _generate_status_icon("#6c757d")        # muted gray
icon_recording = _generate_status_icon("#dc3545")   # recording red
icon_transcribing_icon = _generate_status_icon("#28a745")  # transcription green
tray_icon = None


def update_tray_icon(state='idle'):
    """Update system tray icon based on state."""
    if tray_icon is None:
        return
    if state == 'idle':
        tray_icon.icon = icon_idle
    elif state == 'recording':
        tray_icon.icon = icon_recording
    elif state == 'transcribing':
        tray_icon.icon = icon_transcribing_icon

def on_toggle_tray(icon, item):
    toggle_recording_action()

def on_quit_tray(icon, item):
    icon.stop()
    os._exit(0)

def setup_tray():
    """Setup system tray icon."""
    global tray_icon
    menu = pystray.Menu(
        item('Toggle Recording', on_toggle_tray),
        item('Quit', on_quit_tray)
    )
    tray_icon = pystray.Icon("AudioTranscriptionTool", icon_idle, "Audio Transcription Tool", menu)
    tray_icon.run()

# -----------------------------------------------------
# Recording with VAD
# -----------------------------------------------------

def record_audio():
    """
    Background thread that continuously records audio.
    Filters silent chunks using WebRTC-VAD before batching.
    """
    global recording, audio_frames, current_batch_frames, VAD_AGGRESSIVENESS
    global post_stop_chunks, stop_requested

    p = pyaudio.PyAudio()
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )
    except Exception as e:
        messagebox.showerror("Error", f"Failed to open audio stream: {e}")
        sys.exit(1)

    try:
        while True:
            try:
                if recording or (stop_requested and post_stop_chunks > 0):
                    data = stream.read(CHUNK, exception_on_overflow=False)

                    if is_speech(data, aggressiveness=VAD_AGGRESSIVENESS):
                        audio_frames.append(data)
                        current_batch_frames.append(data)

                    if len(current_batch_frames) >= FRAMES_PER_BATCH:
                        batch = current_batch_frames.copy()
                        current_batch_frames.clear()
                        threading.Thread(target=process_batch, args=(batch,), daemon=True).start()

                    if stop_requested and not recording:
                        post_stop_chunks = max(post_stop_chunks - 1, 0)
                        if post_stop_chunks == 0:
                            stop_requested = False
                            batch = current_batch_frames.copy()
                            current_batch_frames.clear()
                            threading.Thread(target=process_remaining_batches, args=(batch,), daemon=True).start()
                else:
                    if stop_requested:
                        stop_requested = False
                        batch = current_batch_frames.copy()
                        current_batch_frames.clear()
                        threading.Thread(target=process_remaining_batches, args=(batch,), daemon=True).start()
                    time.sleep(0.05)
            except Exception:
                time.sleep(0.05)
    finally:
        try:
            stream.stop_stream()
            stream.close()
        finally:
            p.terminate()

# -----------------------------------------------------
# Transcription Services
# -----------------------------------------------------

def save_audio_to_temp(batch_frames):
    """Save audio frames to temporary WAV file."""
    if not batch_frames:
        return None
    try:
        filename = tempfile.mktemp(suffix=".wav")
        wf = wave.open(filename, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(batch_frames))
        wf.close()
        return filename
    except Exception:
        return None

def transcribe_audio_openai(filename, api_key):
    """Transcribe using OpenAI gpt-4o-mini-transcribe."""
    try:
        client = OpenAI(api_key=api_key)
        with open(filename, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file,
                response_format="text",
                language="en"
            )
        return transcript, True
    except Exception as e:
        return f"OpenAI transcription failed: {str(e)}", False

def transcribe_audio_groq(filename, api_key):
    """Transcribe using Groq Whisper."""
    client = Groq(api_key=api_key)
    max_retries = 3
    max_delay = 60

    for attempt in range(max_retries):
        try:
            with open(filename, "rb") as file:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(filename), file.read()),
                    model="whisper-large-v3",
                    response_format="text",
                    language="en"
                )
            return transcription, True
        except Exception as e:
            if attempt < max_retries - 1:
                delay = min(2 ** attempt + random.uniform(0, 1), max_delay)
                time.sleep(delay)
            else:
                return f"Groq transcription failed: {str(e)}", False

def transcribe_audio_gemini(filename, api_key):
    """Transcribe using Gemini as final fallback."""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        with open(filename, "rb") as file:
            data = file.read()
        prompt = (
            "Generate a verbatim English transcript of the speech. "
            "Assume the speaker is using English even if you detect other cues. "
            "Capture all spoken words accurately without commentary."
        )
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/wav", "data": data}
        ])
        return response.text, True
    except Exception as e:
        return f"Gemini transcription failed: {str(e)}", False

def process_batch(batch_frames):
    """
    Process audio batch according to the selected transcription strategy.
    """
    global transcription_buffer, OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, SELECTED_SERVICE

    temp_audio_file = save_audio_to_temp(batch_frames)
    if not temp_audio_file:
        return

    transcription = ""
    success = False

    if SELECTED_SERVICE == "openai":
        service_sequence = [("openai", OPENAI_API_KEY, transcribe_audio_openai)]
    elif SELECTED_SERVICE == "groq":
        service_sequence = [("groq", GROQ_API_KEY, transcribe_audio_groq)]
    elif SELECTED_SERVICE == "gemini":
        service_sequence = [("gemini", GEMINI_API_KEY, transcribe_audio_gemini)]
    else:
        service_sequence = []
        if OPENAI_API_KEY:
            service_sequence.append(("openai", OPENAI_API_KEY, transcribe_audio_openai))
        if GROQ_API_KEY:
            service_sequence.append(("groq", GROQ_API_KEY, transcribe_audio_groq))
        if GEMINI_API_KEY:
            service_sequence.append(("gemini", GEMINI_API_KEY, transcribe_audio_gemini))

    for name, key, handler in service_sequence:
        if not key:
            continue
        transcription, success = handler(temp_audio_file, key)
        if success:
            break

    with transcription_lock:
        transcription_buffer += (transcription or "") + " "

    try:
        os.remove(temp_audio_file)
    except:
        pass

def process_remaining_batches(batch):
    """Process final batch when recording stops."""
    try:
        if batch:
            process_batch(batch)
    except Exception:
        pass
    finally:
        finalize_transcription()

def finalize_transcription():
    """Copy transcription to clipboard and paste."""
    global transcribing, transcription_buffer

    with transcription_lock:
        text_to_copy = transcription_buffer.strip()
        if text_to_copy:
            pyperclip.copy(text_to_copy)
            time.sleep(0.5)
            try:
                pyautogui.hotkey('ctrl', 'v')
            except:
                pass

    transcribing = False
    update_tray_icon('idle')
    update_status_label("Ready")

# -----------------------------------------------------
# UI Components
# -----------------------------------------------------

def update_status_label(text):
    """Update status label in UI."""
    status_label.config(text=text)
    root.update_idletasks()

def open_settings():
    """Open settings window."""
    settings_window = tk.Toplevel(root)
    settings_window.title("Settings")
    settings_window.geometry("540x520")
    settings_window.resizable(False, False)

    # Current values
    current_openai = OPENAI_API_KEY or ""
    current_groq = GROQ_API_KEY or ""
    current_gemini = GEMINI_API_KEY or ""
    current_hotkey = HOTKEY
    current_vad = VAD_AGGRESSIVENESS
    current_service = SELECTED_SERVICE

    # OpenAI API Key
    tk.Label(settings_window, text="OpenAI API Key (Primary):", font=("Arial", 10, "bold")).pack(pady=(10, 0))
    openai_entry = tk.Entry(settings_window, width=55)
    openai_entry.insert(0, current_openai)
    openai_entry.pack(pady=5)

    # Groq API Key
    tk.Label(settings_window, text="Groq API Key (Fallback):", font=("Arial", 10)).pack(pady=(10, 0))
    groq_entry = tk.Entry(settings_window, width=55)
    groq_entry.insert(0, current_groq)
    groq_entry.pack(pady=5)

    # Gemini API Key
    tk.Label(settings_window, text="Gemini API Key (Final Fallback):", font=("Arial", 10)).pack(pady=(10, 0))
    gemini_entry = tk.Entry(settings_window, width=55)
    gemini_entry.insert(0, current_gemini)
    gemini_entry.pack(pady=5)

    # Hotkey selection
    tk.Label(settings_window, text="Hotkey:", font=("Arial", 10)).pack(pady=(10, 0))
    hotkey_var = tk.StringVar(value="")
    hotkey_combobox = ttk.Combobox(settings_window, textvariable=hotkey_var, state='readonly', width=52)
    hotkey_combobox['values'] = [opt[0] for opt in HOTKEY_OPTIONS]
    selected_hotkey_label = HOTKEY_OPTIONS[0][0]
    for label, value in HOTKEY_OPTIONS:
        if value == current_hotkey:
            selected_hotkey_label = label
            break
    hotkey_combobox.set(selected_hotkey_label)
    hotkey_combobox.pack(pady=5)

    # Service selection
    tk.Label(settings_window, text="Transcription Service:", font=("Arial", 10)).pack(pady=(10, 0))
    service_var = tk.StringVar(value="")
    service_combobox = ttk.Combobox(settings_window, textvariable=service_var, state='readonly', width=52)
    service_combobox['values'] = [opt[0] for opt in SERVICE_OPTIONS]
    selected_service_label = SERVICE_OPTIONS[0][0]
    for label, value in SERVICE_OPTIONS:
        if value == current_service:
            selected_service_label = label
            break
    service_combobox.set(selected_service_label)
    service_combobox.pack(pady=5)

    # VAD Aggressiveness
    tk.Label(settings_window, text="Voice Detection Aggressiveness (0-3, 0=Off):", font=("Arial", 10)).pack(pady=(10, 0))
    tk.Label(settings_window, text="0=Off (no filtering) | 3=Strict (more filtering)", font=("Arial", 8), fg="gray").pack()
    vad_frame = tk.Frame(settings_window)
    vad_frame.pack(pady=5)
    vad_scale = tk.Scale(vad_frame, from_=0, to=3, resolution=1, orient=tk.HORIZONTAL, length=360)
    vad_scale.set(current_vad)
    vad_scale.pack(side=tk.LEFT)
    vad_label_text = "Off" if int(current_vad) == 0 else f"{int(current_vad)}"
    vad_label = tk.Label(vad_frame, text=vad_label_text)
    vad_label.pack(side=tk.LEFT, padx=5)

    def update_vad_label(val):
        level = int(float(val))
        vad_label.config(text="Off" if level == 0 else f"{level}")

    vad_scale.config(command=update_vad_label)

    def save_settings():
        new_openai = openai_entry.get().strip()
        new_groq = groq_entry.get().strip()
        new_gemini = gemini_entry.get().strip()

        selected_service_label = service_combobox.get()
        new_selected_service = "auto"
        for label, value in SERVICE_OPTIONS:
            if label == selected_service_label:
                new_selected_service = value
                break

        if new_selected_service == "openai" and not new_openai:
            messagebox.showerror("Error", "OpenAI API key is required for the selected transcription service.")
            return
        if new_selected_service == "groq" and not new_groq:
            messagebox.showerror("Error", "Groq API key is required for the selected transcription service.")
            return
        if new_selected_service == "gemini" and not new_gemini:
            messagebox.showerror("Error", "Gemini API key is required for the selected transcription service.")
            return
        if new_selected_service == "auto" and not any([new_openai, new_groq, new_gemini]):
            messagebox.showerror("Error", "Provide at least one API key when using Auto mode.")
            return

        selected_text = hotkey_combobox.get()
        new_hotkey = HOTKEY_OPTIONS[0][1]
        for opt in HOTKEY_OPTIONS:
            if opt[0] == selected_text:
                new_hotkey = opt[1]
                break

        new_vad_aggressiveness = int(vad_scale.get())

        save_config(new_openai, new_groq, new_gemini, new_hotkey, new_vad_aggressiveness, new_selected_service)
        load_new_keys()
        rebind_hotkey()

        settings_window.destroy()
        messagebox.showinfo("Success", "Settings saved successfully.")

    save_button = tk.Button(settings_window, text="Save", command=save_settings, font=("Arial", 10))
    save_button.pack(pady=15)

def load_new_keys():
    """Reload config after settings change."""
    global OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, HOTKEY, VAD_AGGRESSIVENESS, SELECTED_SERVICE
    data = load_config()
    OPENAI_API_KEY = data["OPENAI_API_KEY"]
    GROQ_API_KEY = data["GROQ_API_KEY"]
    GEMINI_API_KEY = data["GEMINI_API_KEY"]
    HOTKEY = data["HOTKEY"]
    VAD_AGGRESSIVENESS = int(data.get("VAD_AGGRESSIVENESS", 2))
    SELECTED_SERVICE = data.get("SELECTED_SERVICE", "auto")

def rebind_hotkey():
    """Rebind keyboard hotkey."""
    keyboard.unhook_all_hotkeys()
    keyboard.add_hotkey(HOTKEY, toggle_recording_action)

def toggle_recording_action():
    """Toggle recording on/off."""
    global recording, audio_frames, current_batch_frames, transcription_buffer, transcribing
    global stop_requested, post_stop_chunks

    if transcribing:
        messagebox.showinfo("Info", "Transcription in progress. Please wait.")
        return

    missing_key_message = None
    if SELECTED_SERVICE == "openai" and not OPENAI_API_KEY:
        missing_key_message = "OpenAI API key required for the selected transcription service."
    elif SELECTED_SERVICE == "groq" and not GROQ_API_KEY:
        missing_key_message = "Groq API key required for the selected transcription service."
    elif SELECTED_SERVICE == "gemini" and not GEMINI_API_KEY:
        missing_key_message = "Gemini API key required for the selected transcription service."
    elif SELECTED_SERVICE == "auto" and not any([OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY]):
        missing_key_message = "Provide at least one API key before recording."

    if missing_key_message:
        messagebox.showinfo("Info", missing_key_message)
        open_settings()
        return

    recording = not recording

    if recording:
        audio_frames.clear()
        current_batch_frames.clear()
        with transcription_lock:
            transcription_buffer = ""
        stop_requested = False
        post_stop_chunks = POST_STOP_EXTRA_CHUNKS
        update_status_label("Recording...")
        record_button.config(text="Stop Recording")
        update_tray_icon('recording')
    else:
        stop_requested = True
        post_stop_chunks = POST_STOP_EXTRA_CHUNKS
        update_status_label("Transcribing...")
        record_button.config(text="Record")
        transcribing = True
        update_tray_icon('transcribing')

def prompt_for_keys_if_needed():
    """Prompt for API keys on first run."""
    needs_prompt = False
    if SELECTED_SERVICE == "openai" and not OPENAI_API_KEY:
        needs_prompt = True
    elif SELECTED_SERVICE == "groq" and not GROQ_API_KEY:
        needs_prompt = True
    elif SELECTED_SERVICE == "gemini" and not GEMINI_API_KEY:
        needs_prompt = True
    elif SELECTED_SERVICE == "auto" and not any([OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY]):
        needs_prompt = True

    if needs_prompt:
        messagebox.showinfo("Setup Required", "Please configure API keys for the selected transcription service in Settings.")
        open_settings()

def on_close():
    """Clean shutdown."""
    root.destroy()
    os._exit(0)

# -----------------------------------------------------
# Main Window
# -----------------------------------------------------

root = tk.Tk()
root.title("Audio Transcription Tool v2.0")
root.geometry("400x220")
root.resizable(False, False)

icon_file = resource_path("recorder_icon.ico")
if os.path.exists(icon_file):
    try:
        root.iconbitmap(icon_file)
    except Exception as exc:
        print(f"Unable to set window icon: {exc}")

title_label = tk.Label(root, text="Audio Transcription Tool", font=("Arial", 14, "bold"))
title_label.pack(pady=10)

subtitle_label = tk.Label(root, text="OpenAI • Groq • Gemini | WebRTC-VAD", font=("Arial", 9), fg="gray")
subtitle_label.pack()

status_label = tk.Label(root, text="Ready", fg="blue", font=("Arial", 10))
status_label.pack(pady=10)

record_button = tk.Button(root, text="Record", width=18, command=toggle_recording_action,
                          font=("Arial", 11, "bold"), bg="#4CAF50", fg="white")
record_button.pack(pady=10)

settings_button = tk.Button(root, text="Settings", width=18, command=open_settings, font=("Arial", 10))
settings_button.pack(pady=5)

root.protocol("WM_DELETE_WINDOW", on_close)
root.after(500, prompt_for_keys_if_needed)

# -----------------------------------------------------
# Start Background Services
# -----------------------------------------------------

def start_threads():
    """Initialize all background threads."""
    # Load VAD
    print("Initializing WebRTC-VAD...")
    load_vad_model()

    # Start recording thread
    recording_thread = threading.Thread(target=record_audio, daemon=True)
    recording_thread.start()

    # Start tray icon
    tray_thread = threading.Thread(target=setup_tray, daemon=True)
    tray_thread.start()

    # Bind hotkey
    keyboard.add_hotkey(HOTKEY, toggle_recording_action)

start_threads()
root.mainloop()
