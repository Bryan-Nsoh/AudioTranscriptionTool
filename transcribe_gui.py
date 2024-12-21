import os
import sys
import time
import threading
import wave
import json
import tempfile
import traceback
import random
from pathlib import Path

import pyaudio
import pyautogui
import pyperclip
import requests
import keyboard
import google.generativeai as genai
from groq import Groq
import tkinter as tk
from tkinter import messagebox, ttk
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw

# -----------------------------------------------------
# Configuration
# -----------------------------------------------------

# Disable PyAutoGUI fail-safe (optional, but as in original code)
pyautogui.FAILSAFE = False

# Paths for PyInstaller vs. normal Python
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# Global variables
recording = False
transcribing = False
audio_frames = []
current_batch_frames = []
transcription_buffer = ""
transcription_lock = threading.Lock()

# Audio constants
BATCH_DURATION_SECONDS = 180
RATE = 16000
CHUNK = 1024
FRAMES_PER_BATCH = int((RATE * BATCH_DURATION_SECONDS) / CHUNK)

# Default hotkey choices
HOTKEY_OPTIONS = [
    ("Ctrl+Alt+Shift+R", "ctrl+alt+shift+r"),
    ("Alt+R", "alt+r"),
    ("Ctrl+R", "ctrl+r"),
]

# API keys and hotkey will be loaded from config.json
GROQ_API_KEY = None
GEMINI_API_KEY = None
HOTKEY = "ctrl+alt+shift+r"

# -----------------------------------------------------
# Load/Save Config
# -----------------------------------------------------

def load_config():
    """
    Loads config from config.json. If it doesn't exist or is invalid,
    returns a dict with empty keys.
    """
    if not os.path.isfile(CONFIG_FILE):
        return {"GROQ_API_KEY": "", "GEMINI_API_KEY": "", "HOTKEY": "ctrl+alt+shift+r"}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data.setdefault("GROQ_API_KEY", "")
    data.setdefault("GEMINI_API_KEY", "")
    data.setdefault("HOTKEY", "ctrl+alt+shift+r")
    return data

def save_config(groq_key, gemini_key, hotkey_value):
    """
    Saves the given config to config.json.
    """
    data = {
        "GROQ_API_KEY": groq_key.strip(),
        "GEMINI_API_KEY": gemini_key.strip(),
        "HOTKEY": hotkey_value
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# -----------------------------------------------------
# Set up initial config
# -----------------------------------------------------

config_data = load_config()
GROQ_API_KEY = config_data["GROQ_API_KEY"]
GEMINI_API_KEY = config_data["GEMINI_API_KEY"]
HOTKEY = config_data["HOTKEY"]

# -----------------------------------------------------
# Tray icon creation
# -----------------------------------------------------

def create_icon(color):
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return image

icon_idle = create_icon('grey')
icon_recording = create_icon('red')
icon_transcribing_icon = create_icon('green')

tray_icon = None

def update_tray_icon(state='idle'):
    """
    Updates the system tray icon based on state.
    """
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
    global tray_icon
    menu = pystray.Menu(
        item('Toggle Recording', on_toggle_tray),
        item('Quit', on_quit_tray)
    )
    tray_icon = pystray.Icon("AudioTranscriptionTool", icon_idle, "Audio Transcription Tool", menu)
    tray_icon.run()

# -----------------------------------------------------
# Recording Thread
# -----------------------------------------------------

def record_audio():
    """
    Background thread that continuously reads audio when 'recording' is True.
    Batches audio frames every ~3 minutes into a separate transcription job.
    """
    global recording, audio_frames, current_batch_frames
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
            if recording:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    audio_frames.append(data)
                    current_batch_frames.append(data)

                    # If we've collected enough frames for one batch (~3 minutes)
                    if len(current_batch_frames) >= FRAMES_PER_BATCH:
                        batch = current_batch_frames.copy()
                        current_batch_frames.clear()
                        threading.Thread(target=process_batch, args=(batch,), daemon=True).start()
                except Exception:
                    recording = False
            else:
                time.sleep(0.1)
    except Exception:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

# -----------------------------------------------------
# Audio & Transcription
# -----------------------------------------------------

def save_audio_to_temp(batch_frames):
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

def transcribe_audio_groq(filename, groq_key):
    client = Groq(api_key=groq_key)
    max_retries = 5
    max_delay = 120
    for attempt in range(max_retries):
        try:
            with open(filename, "rb") as file:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(filename), file.read()),
                    model="whisper-large-v3",
                    response_format="text",
                )
            return transcription, True
        except Exception as e:
            if attempt < max_retries - 1:
                delay = min(2 ** attempt + random.uniform(0, 1), max_delay)
                time.sleep(delay)
            else:
                return f"Groq transcription failed: {str(e)}", False

def transcribe_audio_gemini(filename, gemini_key):
    # Configure generative AI each time for safety
    genai.configure(api_key=gemini_key)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")
    try:
        with open(filename, "rb") as file:
            data = file.read()
        prompt = (
            "Generate a verbatim transcript of the speech. "
            "Ensure the transcription captures all spoken words accurately. "
            "Avoid adding commentary or interpretation."
        )
        response = gemini_model.generate_content([
            prompt,
            {"mime_type": "audio/wav", "data": data}
        ])
        return response.text, True
    except Exception as e:
        return f"Gemini transcription failed: {str(e)}", False

def process_batch(batch_frames):
    """
    Called in a separate thread whenever ~3 minutes of audio is collected.
    Attempts Groq, then falls back to Gemini if needed.
    """
    global transcription_buffer, GROQ_API_KEY, GEMINI_API_KEY
    temp_audio_file = save_audio_to_temp(batch_frames)
    if temp_audio_file:
        # Attempt Groq
        transcription, success = transcribe_audio_groq(temp_audio_file, GROQ_API_KEY)
        if not success:
            # Fallback to Gemini
            transcription, success = transcribe_audio_gemini(temp_audio_file, GEMINI_API_KEY)
        with transcription_lock:
            transcription_buffer += transcription + " "
        os.remove(temp_audio_file)

def process_remaining_batches(batch):
    """
    Called once recording is stopped to finalize any leftover frames that
    didn't quite reach 3 minutes.
    """
    try:
        process_batch(batch)
    except Exception:
        pass
    finally:
        finalize_transcription()

def finalize_transcription():
    """
    Final step: copy all accumulated transcripts to clipboard, then simulate a paste.
    """
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
# Tkinter UI
# -----------------------------------------------------

def update_status_label(text):
    status_label.config(text=text)
    root.update_idletasks()

def open_settings():
    """
    Opens a small settings window to update GROQ_API_KEY, GEMINI_API_KEY, and hotkey.
    """
    settings_window = tk.Toplevel(root)
    settings_window.title("Settings")
    settings_window.geometry("400x250")
    settings_window.resizable(False, False)

    # Get current config values
    current_groq = GROQ_API_KEY if GROQ_API_KEY else ""
    current_gemini = GEMINI_API_KEY if GEMINI_API_KEY else ""
    current_hotkey = HOTKEY

    tk.Label(settings_window, text="GROQ_API_KEY:", font=("Arial", 10)).pack(pady=(10, 0))
    groq_entry = tk.Entry(settings_window, width=50)
    groq_entry.insert(0, current_groq)
    groq_entry.pack(pady=5)

    tk.Label(settings_window, text="GEMINI_API_KEY:", font=("Arial", 10)).pack(pady=(10, 0))
    gemini_entry = tk.Entry(settings_window, width=50)
    gemini_entry.insert(0, current_gemini)
    gemini_entry.pack(pady=5)

    tk.Label(settings_window, text="Select Hotkey:", font=("Arial", 10)).pack(pady=(10, 0))
    hotkey_var = tk.StringVar(value=current_hotkey)
    hotkey_combobox = ttk.Combobox(settings_window, textvariable=hotkey_var, state='readonly')
    hotkey_combobox['values'] = [opt[0] for opt in HOTKEY_OPTIONS]
    # Set the combobox to the current hotkey
    for i, opt in enumerate(HOTKEY_OPTIONS):
        if opt[1] == current_hotkey:
            hotkey_combobox.current(i)
            break
    hotkey_combobox.pack(pady=5)

    def save_settings():
        new_groq = groq_entry.get().strip()
        new_gemini = gemini_entry.get().strip()

        if not new_groq or not new_gemini:
            messagebox.showerror("Error", "Both GROQ_API_KEY and GEMINI_API_KEY must be provided.")
            return

        selected_text = hotkey_combobox.get()
        new_hotkey = "ctrl+alt+shift+r"
        for opt in HOTKEY_OPTIONS:
            if opt[0] == selected_text:
                new_hotkey = opt[1]
                break

        save_config(new_groq, new_gemini, new_hotkey)

        # Reload into global variables
        load_new_keys()
        rebind_hotkey()

        settings_window.destroy()
        messagebox.showinfo("Info", "Settings saved successfully.")

    save_button = tk.Button(settings_window, text="Save", command=save_settings)
    save_button.pack(pady=10)

def load_new_keys():
    """
    Loads the updated config.json data into global variables.
    """
    global GROQ_API_KEY, GEMINI_API_KEY, HOTKEY
    data = load_config()
    GROQ_API_KEY = data["GROQ_API_KEY"]
    GEMINI_API_KEY = data["GEMINI_API_KEY"]
    HOTKEY = data["HOTKEY"]

def rebind_hotkey():
    keyboard.unhook_all_hotkeys()
    keyboard.add_hotkey(HOTKEY, toggle_recording_action)

def toggle_recording_action():
    """
    Called when user clicks 'Record' or hits the configured hotkey.
    """
    global recording, audio_frames, current_batch_frames, transcription_buffer, transcribing

    # If transcription is currently processing, do not allow new toggles
    if transcribing:
        messagebox.showinfo("Info", "Transcription in progress. Please wait.")
        return

    # If keys are missing, remind user to set them
    if not GROQ_API_KEY or not GEMINI_API_KEY:
        messagebox.showinfo("Info", "API keys not configured. Please set them in Settings.")
        return

    recording = not recording
    if recording:
        audio_frames.clear()
        current_batch_frames.clear()
        with transcription_lock:
            transcription_buffer = ""
        update_status_label("Recording...")
        record_button.config(text="Stop Recording")
        update_tray_icon('recording')
    else:
        # Stop
        update_status_label("Transcribing...")
        record_button.config(text="Record")
        transcribing = True
        update_tray_icon('transcribing')
        if current_batch_frames:
            batch = current_batch_frames.copy()
            current_batch_frames.clear()
            threading.Thread(target=process_remaining_batches, args=(batch,), daemon=True).start()
        else:
            threading.Thread(target=finalize_transcription, daemon=True).start()

def prompt_for_keys_if_needed():
    """
    If keys are missing on startup, prompt user to open settings right away.
    """
    if not GROQ_API_KEY or not GEMINI_API_KEY:
        messagebox.showinfo("Keys Required", "API keys not found. Please provide them in the Settings.")
        open_settings()

def on_close():
    root.destroy()
    os._exit(0)

# -----------------------------------------------------
# Main TK Window
# -----------------------------------------------------

root = tk.Tk()
root.title("Audio Transcription Tool")
root.geometry("350x200")
root.resizable(False, False)

title_label = tk.Label(root, text="Audio Transcription Tool", font=("Arial", 14, "bold"))
title_label.pack(pady=10)

status_label = tk.Label(root, text="Ready", fg="blue", font=("Arial", 10))
status_label.pack(pady=5)

record_button = tk.Button(root, text="Record", width=15, command=toggle_recording_action, font=("Arial", 10))
record_button.pack(pady=10)

settings_button = tk.Button(root, text="Settings", width=15, command=open_settings, font=("Arial", 10))
settings_button.pack(pady=5)

root.protocol("WM_DELETE_WINDOW", on_close)
root.after(500, prompt_for_keys_if_needed)

# Start background threads
def start_threads():
    recording_thread = threading.Thread(target=record_audio, daemon=True)
    recording_thread.start()

    tray_thread = threading.Thread(target=setup_tray, daemon=True)
    tray_thread.start()

    # Bind global hotkey
    keyboard.add_hotkey(HOTKEY, toggle_recording_action)

start_threads()
root.mainloop()
