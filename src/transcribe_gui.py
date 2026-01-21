"""
Voice Transcribe - Audio transcription with modern UI
CustomTkinter + floating waveform popup
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
import struct
import shutil
from pathlib import Path
from datetime import datetime
from collections import deque

import pyaudio
import keyboard
import pyautogui
import pyperclip
import pystray
import customtkinter as ctk
from PIL import Image, ImageDraw
from pystray import MenuItem as item
from dotenv import load_dotenv

from deepgram import DeepgramClient
from openai import OpenAI

# Windows app ID
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('voicetranscribe.v3')
pyautogui.FAILSAFE = False

# CustomTkinter setup
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# -----------------------------------------------------
# Paths & Config
# -----------------------------------------------------

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "VoiceTranscribe"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
TRANSCRIPTS_FILE = CONFIG_DIR / "transcripts.log"
ENV_FILE = CONFIG_DIR / ".env"
FAILED_AUDIO_DIR = CONFIG_DIR / "failed_recordings"
FAILED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

if not ENV_FILE.exists():
    source_env = PROJECT_ROOT / ".env"
    if source_env.exists():
        import shutil
        shutil.copy(source_env, ENV_FILE)

load_dotenv(ENV_FILE)

# Audio settings
RATE = 16000
CHUNK = 1024
PRE_ROLL_CHUNKS = int(0.5 * RATE / CHUNK)
MAX_CHUNK_SECONDS = 7 * 60
MAX_CHUNK_FRAMES = int(MAX_CHUNK_SECONDS * RATE / CHUNK)
CHUNK_OVERLAP_CHUNKS = int(1.0 * RATE / CHUNK)
MAX_RECORDING_SECONDS = 30 * 60

# Silence detection - adaptive threshold
SILENCE_THRESHOLD = 150  # Lower base threshold
SILENCE_WARNING_SECONDS = 8  # Warning after 8s silence
SILENCE_ABORT_SECONDS = 30  # Auto-abort after 30s of TOTAL silence (not just pause)
SOUND_HYSTERESIS_FRAMES = 8  # Frames of sound needed to confirm "has audio"

# Waveform
WAVEFORM_POINTS = 150

# Models
MODELS = {
    "openai-mini": ("GPT-4o-mini", "OPENAI_API_KEY"),
    "openai": ("GPT-4o", "OPENAI_API_KEY"),
    "deepgram": ("Deepgram Nova-3", "DEEPGRAM_API_KEY"),
}

# -----------------------------------------------------
# Global State
# -----------------------------------------------------

recording = False
transcribing = False
chunking = False
recording_start_time = 0
audio_frames = []
pre_roll_buffer = []
full_transcript = []
transcription_lock = threading.Lock()
tray_icon = None

# Silence detection
max_amplitude_seen = 0
last_sound_time = 0
silence_warned = False
current_amplitude = 0
smoothed_amplitude = 0  # For stable color display
sound_frames_count = 0  # Count consecutive frames with sound

# Waveform buffer
waveform_data = deque(maxlen=WAVEFORM_POINTS)

# Config
current_model = "openai-mini"
hotkey = "ctrl+space"
current_device_index = None

# Audio stream
audio_stream = None
audio_pyaudio = None
stream_lock = threading.Lock()
last_device_check = 0
known_devices = set()

# UI refs
root = None
settings_window = None
popup_window = None
waveform_canvas = None

# -----------------------------------------------------
# Config
# -----------------------------------------------------

def load_config():
    global current_model, hotkey, current_device_index
    if CONFIG_FILE.is_file():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            current_model = data.get("model", "openai-mini")
            if current_model not in MODELS:
                current_model = "openai-mini"
            hotkey = data.get("hotkey", "ctrl+space")
            current_device_index = data.get("device_index")
        except:
            pass

def save_config():
    CONFIG_FILE.write_text(json.dumps({
        "model": current_model,
        "hotkey": hotkey,
        "device_index": current_device_index
    }, indent=2))

def get_api_key(key_name):
    return os.getenv(key_name, "")

load_config()

# -----------------------------------------------------
# Sound Effects (wav files from Mixkit)
# -----------------------------------------------------

SOUNDS_DIR = Path(__file__).parent / "sounds"

def _play_sound(name):
    """Play a sound file asynchronously."""
    try:
        path = SOUNDS_DIR / f"{name}.wav"
        if path.exists():
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except:
        pass  # Fail silently if sound can't play

def sound_success():
    """Chime - transcription complete."""
    _play_sound("success")

def sound_warning():
    """Bell - low audio warning."""
    _play_sound("warning")

def sound_error():
    """Fail tone - transcription error."""
    _play_sound("error")

def sound_abort():
    """Back sound - recording cancelled."""
    _play_sound("abort")

def sound_empty():
    """Select sound - nothing detected."""
    _play_sound("empty")

def sound_device():
    """Hardware sound - device change."""
    _play_sound("device")

# -----------------------------------------------------
# Device Management
# -----------------------------------------------------

def get_input_devices():
    devices = []
    try:
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                devices.append((i, info['name'].strip()))
        p.terminate()
    except:
        pass
    return devices

def get_current_device_name():
    if current_device_index is None:
        return "System Default"
    for idx, name in get_input_devices():
        if idx == current_device_index:
            return name
    return "System Default"

def check_device_changes():
    """Check for new/removed audio devices."""
    global known_devices, last_device_check

    now = time.time()
    if now - last_device_check < 2:  # Check every 2 seconds max
        return False
    last_device_check = now

    current_devices = set(get_input_devices())
    if current_devices != known_devices:
        new_devices = current_devices - known_devices
        removed_devices = known_devices - current_devices
        known_devices = current_devices

        if new_devices:
            # New mic plugged in - notify
            for idx, name in new_devices:
                root.after(0, lambda n=name: show_device_notification(f"Mic connected: {n}"))
            return True
        if removed_devices:
            for idx, name in removed_devices:
                root.after(0, lambda n=name: show_device_notification(f"Mic removed: {n}"))
            return True
    return False

def show_device_notification(msg):
    """Show brief notification about device change."""
    sound_device()
    if settings_window and settings_window.winfo_exists():
        refresh_device_list()

# -----------------------------------------------------
# Tray Icon
# -----------------------------------------------------

def make_icon(color):
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img

icon_idle = make_icon((108, 117, 125, 255))
icon_recording = make_icon((220, 53, 69, 255))
icon_transcribing = make_icon((40, 167, 69, 255))

def update_tray(state='idle'):
    if tray_icon:
        tray_icon.icon = {'idle': icon_idle, 'recording': icon_recording,
                         'transcribing': icon_transcribing}.get(state, icon_idle)

def setup_tray():
    global tray_icon
    menu = pystray.Menu(
        item('Record', lambda: root.after(0, toggle_recording)),
        item('Settings', lambda: root.after(0, show_settings)),
        item('Quit', lambda: os._exit(0))
    )
    tray_icon = pystray.Icon("VoiceTranscribe", icon_idle, "Voice Transcribe", menu)
    tray_icon.run()

# -----------------------------------------------------
# Transcription
# -----------------------------------------------------

def save_audio_file(frames, permanent=False):
    """Save audio frames to file. If permanent=True, saves to failed_recordings folder."""
    if not frames:
        return None
    try:
        if permanent:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = str(FAILED_AUDIO_DIR / f"recording_{timestamp}.wav")
        else:
            filename = tempfile.mktemp(suffix=".wav")

        wf = wave.open(filename, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
        wf.close()
        return filename
    except Exception as e:
        print(f"Failed to save audio: {e}")
        return None

def move_to_failed(temp_path):
    """Move a temp file to the failed recordings folder."""
    if not temp_path or not os.path.exists(temp_path):
        return None
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = FAILED_AUDIO_DIR / f"recording_{timestamp}.wav"
        shutil.move(temp_path, dest)
        return str(dest)
    except:
        return temp_path  # Return original if move fails

def transcribe_openai_mini(filename):
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        return "Missing OPENAI_API_KEY", False
    try:
        # Check file size - OpenAI limit is 25MB
        file_size = os.path.getsize(filename)
        if file_size > 25 * 1024 * 1024:
            return f"File too large ({file_size // 1024 // 1024}MB > 25MB limit)", False

        client = OpenAI(api_key=api_key, timeout=120.0)  # 2 min timeout
        with open(filename, "rb") as f:
            response = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe", file=f,
                response_format="text", language="en")
        return response, True
    except Exception as e:
        error_str = str(e)
        # Log error for debugging
        try:
            with (CONFIG_DIR / "error.log").open("a") as f:
                f.write(f"[{datetime.now()}] OpenAI Mini Error: {error_str}\n")
        except:
            pass
        return f"OpenAI error: {error_str[:200]}", False

def transcribe_openai(filename):
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        return "Missing OPENAI_API_KEY", False
    try:
        file_size = os.path.getsize(filename)
        if file_size > 25 * 1024 * 1024:
            return f"File too large ({file_size // 1024 // 1024}MB > 25MB limit)", False

        client = OpenAI(api_key=api_key, timeout=180.0)  # 3 min timeout for larger model
        with open(filename, "rb") as f:
            response = client.audio.transcriptions.create(
                model="gpt-4o-transcribe", file=f,
                response_format="text", language="en")
        return response, True
    except Exception as e:
        error_str = str(e)
        try:
            with (CONFIG_DIR / "error.log").open("a") as f:
                f.write(f"[{datetime.now()}] OpenAI Error: {error_str}\n")
        except:
            pass
        return f"OpenAI error: {error_str[:200]}", False

def transcribe_deepgram(filename):
    api_key = get_api_key("DEEPGRAM_API_KEY")
    if not api_key:
        return "Missing DEEPGRAM_API_KEY", False
    try:
        client = DeepgramClient(api_key=api_key)
        with open(filename, "rb") as f:
            audio_data = f.read()
        response = client.listen.v1.media.transcribe_file(
            request=audio_data, model="nova-3",
            smart_format=True, language="en", punctuate=True)
        return response.results.channels[0].alternatives[0].transcript, True
    except Exception as e:
        error_str = str(e)
        try:
            with (CONFIG_DIR / "error.log").open("a") as f:
                f.write(f"[{datetime.now()}] Deepgram Error: {error_str}\n")
        except:
            pass
        return f"Deepgram error: {error_str[:200]}", False

TRANSCRIBERS = {
    "openai-mini": transcribe_openai_mini,
    "openai": transcribe_openai,
    "deepgram": transcribe_deepgram,
}

# -----------------------------------------------------
# Audio Recording
# -----------------------------------------------------

def get_amplitude(data):
    try:
        samples = struct.unpack('<' + 'h' * (len(data) // 2), data)
        return max(abs(s) for s in samples) if samples else 0
    except:
        return 0

def check_audio_has_sound(frames):
    if not frames:
        return False
    for i in [0, len(frames)//2, -1]:
        try:
            if get_amplitude(frames[i]) > SILENCE_THRESHOLD:
                return True
        except:
            pass
    return False

def open_audio_stream():
    global audio_pyaudio, audio_stream
    with stream_lock:
        if audio_stream:
            try:
                audio_stream.stop_stream()
                audio_stream.close()
            except:
                pass
        if audio_pyaudio:
            try:
                audio_pyaudio.terminate()
            except:
                pass

        audio_pyaudio = pyaudio.PyAudio()
        kwargs = {'format': pyaudio.paInt16, 'channels': 1, 'rate': RATE,
                  'input': True, 'frames_per_buffer': CHUNK}
        if current_device_index is not None:
            kwargs['input_device_index'] = current_device_index
        audio_stream = audio_pyaudio.open(**kwargs)
        return audio_stream

def record_audio():
    global recording, audio_frames, pre_roll_buffer, chunking, recording_start_time
    global max_amplitude_seen, last_sound_time, silence_warned, current_amplitude
    global known_devices, smoothed_amplitude, sound_frames_count

    known_devices = set(get_input_devices())
    stream = open_audio_stream()

    while True:
        try:
            # Check for device changes periodically
            check_device_changes()

            data = stream.read(CHUNK, exception_on_overflow=False)
            amplitude = get_amplitude(data)

            if recording:
                audio_frames.append(data)
                current_amplitude = amplitude

                # Smooth amplitude for stable UI (exponential moving average)
                smoothed_amplitude = smoothed_amplitude * 0.7 + amplitude * 0.3

                # Waveform data
                try:
                    samples = struct.unpack('<' + 'h' * (len(data) // 2), data)
                    step = max(1, len(samples) // 4)
                    for i in range(0, len(samples), step):
                        waveform_data.append(samples[i])
                except:
                    pass

                if amplitude > max_amplitude_seen:
                    max_amplitude_seen = amplitude

                # Track consecutive frames with sound for hysteresis
                if amplitude > SILENCE_THRESHOLD:
                    sound_frames_count = min(sound_frames_count + 1, SOUND_HYSTERESIS_FRAMES * 2)
                    last_sound_time = time.time()
                    silence_warned = False
                else:
                    sound_frames_count = max(sound_frames_count - 1, 0)

                silence_duration = time.time() - (last_sound_time or recording_start_time)

                # Only warn if we've NEVER seen good audio
                if silence_duration >= SILENCE_WARNING_SECONDS and not silence_warned and max_amplitude_seen < SILENCE_THRESHOLD * 2:
                    silence_warned = True
                    sound_warning()
                    root.after(0, lambda: update_popup_status("Low audio - check mic!"))

                # Only abort if truly no audio ever detected
                if silence_duration >= SILENCE_ABORT_SECONDS and max_amplitude_seen < SILENCE_THRESHOLD:
                    sound_abort()
                    root.after(0, abort_recording)
                    continue

                if (time.time() - recording_start_time) >= MAX_RECORDING_SECONDS:
                    sound_warning()
                    root.after(0, toggle_recording)
                    continue

                if len(audio_frames) >= MAX_CHUNK_FRAMES and not chunking:
                    chunking = True
                    frames_to_process = audio_frames[:-CHUNK_OVERLAP_CHUNKS]
                    audio_frames = audio_frames[-CHUNK_OVERLAP_CHUNKS:]
                    threading.Thread(target=process_chunk, args=(frames_to_process,), daemon=True).start()
            else:
                pre_roll_buffer.append(data)
                if len(pre_roll_buffer) > PRE_ROLL_CHUNKS:
                    pre_roll_buffer.pop(0)

        except Exception:
            time.sleep(0.5)
            try:
                stream = open_audio_stream()
            except:
                pass

def abort_recording():
    global recording, audio_frames
    if not recording:
        return
    recording = False
    audio_frames.clear()
    waveform_data.clear()
    update_tray('idle')
    hide_popup()

def process_chunk(frames):
    """Process a chunk during long recording. Keeps audio on failure."""
    global chunking, full_transcript

    temp_file = save_audio_file(frames)
    if not temp_file:
        chunking = False
        return

    text, success = TRANSCRIBERS.get(current_model, transcribe_openai_mini)(temp_file)

    if success and text and text.strip():
        with transcription_lock:
            full_transcript.append(text.strip())
        # Only delete on success
        try:
            os.remove(temp_file)
        except:
            pass
    else:
        # KEEP THE AUDIO - move to failed folder
        saved_path = move_to_failed(temp_file)
        root.after(0, lambda: show_error_notification(f"Chunk failed! Audio saved: {saved_path}"))

    chunking = False

def process_audio():
    """Process final recording. NEVER loses audio."""
    global transcribing, audio_frames, full_transcript

    frames = audio_frames.copy()
    audio_frames.clear()

    # Even if "silent", save audio first before any processing
    if not frames:
        transcribing = False
        update_tray('idle')
        hide_popup()
        return

    # Save to temp file FIRST - this is our backup
    temp_file = save_audio_file(frames)
    if not temp_file:
        transcribing = False
        update_tray('idle')
        hide_popup()
        root.after(0, lambda: show_error_notification("Failed to save audio!"))
        return

    # ALWAYS attempt transcription if user recorded something
    # The silence check was too aggressive - trust the user's intent

    # Attempt transcription
    text, success = TRANSCRIBERS.get(current_model, transcribe_openai_mini)(temp_file)
    final_text = text.strip() if success and text else ""

    # Handle failure - KEEP THE AUDIO
    if not success or not final_text:
        saved_path = move_to_failed(temp_file)
        error_msg = text if text else "Unknown error"
        transcribing = False
        update_tray('idle')
        hide_popup()
        root.after(0, lambda: show_error_notification(
            f"Transcription FAILED!\nAudio saved: {saved_path}\nError: {error_msg[:100]}"))
        sound_error()
        return

    # SUCCESS - now we can delete temp file
    try:
        os.remove(temp_file)
    except:
        pass

    # Combine with any chunks from long recording
    with transcription_lock:
        if final_text:
            full_transcript.append(final_text)
        combined = " ".join(full_transcript).strip()
        full_transcript.clear()

    if combined:
        # Log transcript
        try:
            with TRANSCRIPTS_FILE.open("a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{MODELS[current_model][0]}]\n{combined}\n\n")
        except:
            pass

        # Copy and paste
        pyperclip.copy(combined)
        time.sleep(0.3)
        try:
            pyautogui.hotkey('ctrl', 'v')
        except:
            pass

        sound_success()
    else:
        sound_empty()

    transcribing = False
    update_tray('idle')
    hide_popup()

def show_error_notification(msg):
    """Show error message to user."""
    import tkinter.messagebox as mb
    mb.showerror("Voice Transcribe Error", msg)

def toggle_recording():
    global recording, transcribing, audio_frames, pre_roll_buffer, full_transcript
    global recording_start_time, max_amplitude_seen, last_sound_time, silence_warned

    if transcribing:
        return

    if not get_api_key(MODELS[current_model][1]):
        sound_error()
        return

    recording = not recording

    if recording:
        global smoothed_amplitude, sound_frames_count
        audio_frames.clear()
        full_transcript.clear()
        waveform_data.clear()
        audio_frames.extend(pre_roll_buffer)
        pre_roll_buffer.clear()
        recording_start_time = time.time()
        max_amplitude_seen = 0
        last_sound_time = time.time()
        silence_warned = False
        smoothed_amplitude = 0
        sound_frames_count = 0
        update_tray('recording')
        show_popup()
    else:
        update_popup_status("Transcribing...")
        def do_transcribe():
            global transcribing
            time.sleep(0.3)
            update_tray('transcribing')
            transcribing = True
            process_audio()
        threading.Thread(target=do_transcribe, daemon=True).start()

# -----------------------------------------------------
# Popup Window (Recording Overlay)
# -----------------------------------------------------

POPUP_W, POPUP_H = 440, 100
CORNER_R = 18
BG_DARK = "#12131a"
BG_BORDER = "#2d2f3d"
TRANSPARENT_COLOR = "#010101"  # Used for transparency trick

def create_popup():
    global popup_window, waveform_canvas

    import tkinter as tk

    # Use regular Toplevel for transparency support
    popup_window = tk.Toplevel(root)
    popup_window.overrideredirect(True)
    popup_window.attributes('-topmost', True)
    popup_window.attributes('-transparentcolor', TRANSPARENT_COLOR)
    popup_window.configure(bg=TRANSPARENT_COLOR)

    # Center bottom of screen
    screen_w = popup_window.winfo_screenwidth()
    screen_h = popup_window.winfo_screenheight()
    x = (screen_w - POPUP_W) // 2
    y = screen_h - POPUP_H - 70
    popup_window.geometry(f"{POPUP_W}x{POPUP_H}+{x}+{y}")

    # Canvas for everything (rounded rect + waveform + text)
    canvas = tk.Canvas(popup_window, width=POPUP_W, height=POPUP_H,
                       bg=TRANSPARENT_COLOR, highlightthickness=0)
    canvas.pack()

    # Draw rounded rectangle background
    def rounded_rect(x1, y1, x2, y2, r, **kwargs):
        points = [
            x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
            x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
            x1, y2, x1, y2-r, x1, y1+r, x1, y1
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    # Border/shadow
    rounded_rect(0, 0, POPUP_W, POPUP_H, CORNER_R, fill=BG_BORDER, outline="")
    # Inner background
    rounded_rect(2, 2, POPUP_W-2, POPUP_H-2, CORNER_R-2, fill=BG_DARK, outline="")

    # Store canvas reference for waveform drawing
    waveform_canvas = canvas

    # Create text items - proper layout:
    # [Recording dot] [Status...] -------- [Model] [Time]
    global popup_status_id, popup_time_id, popup_model_id, popup_dot_id

    # Recording dot - far left
    popup_dot_id = canvas.create_oval(18, POPUP_H - 24, 30, POPUP_H - 12,
                                       fill="#ef4444", outline="")

    # Status text - after dot
    popup_status_id = canvas.create_text(38, POPUP_H - 18, anchor='w',
                                          text="Recording...", font=("Segoe UI", 12),
                                          fill="#9ca3af")

    # Time - far right
    popup_time_id = canvas.create_text(POPUP_W - 18, POPUP_H - 18, anchor='e',
                                        text="0:00", font=("Segoe UI Semibold", 13),
                                        fill="#ffffff")

    # Model name - left of time
    popup_model_id = canvas.create_text(POPUP_W - 70, POPUP_H - 18, anchor='e',
                                         text=MODELS[current_model][0],
                                         font=("Segoe UI", 10), fill="#6b7280")

    popup_window.withdraw()

def show_popup():
    if popup_window:
        waveform_canvas.itemconfig(popup_model_id, text=MODELS[current_model][0])
        waveform_canvas.itemconfig(popup_status_id, text="Recording...")
        waveform_canvas.itemconfig(popup_dot_id, fill="#ef4444")
        popup_window.deiconify()
        popup_window.lift()
        update_popup()

def hide_popup():
    if popup_window:
        popup_window.withdraw()

def update_popup_status(text):
    if waveform_canvas and popup_status_id:
        waveform_canvas.itemconfig(popup_status_id, text=text)

def update_popup():
    if not popup_window or not popup_window.winfo_viewable():
        return

    if recording or transcribing:
        # Update time
        if recording and recording_start_time:
            elapsed = int(time.time() - recording_start_time)
            waveform_canvas.itemconfig(popup_time_id, text=f"{elapsed // 60}:{elapsed % 60:02d}")

        # Draw waveform
        if waveform_canvas and recording:
            # Clear old waveform (keep background elements)
            waveform_canvas.delete("waveform")

            # Waveform area - more space, don't overlap status bar
            wf_x1, wf_y1 = 18, 12
            wf_x2, wf_y2 = POPUP_W - 18, POPUP_H - 35
            wf_w = wf_x2 - wf_x1
            wf_h = wf_y2 - wf_y1
            mid_y = wf_y1 + wf_h // 2

            # Center line
            waveform_canvas.create_line(wf_x1, mid_y, wf_x2, mid_y,
                                        fill="#2a2b3a", width=1, tags="waveform")

            data = list(waveform_data)
            if len(data) > 1:
                # Use smoothed amplitude for color (prevents flickering)
                # Green if we have consistent sound, red if mostly silence
                has_sound = sound_frames_count >= SOUND_HYSTERESIS_FRAMES
                color = "#22c55e" if has_sound else "#ef4444"

                # Update recording dot color to match
                waveform_canvas.itemconfig(popup_dot_id, fill=color)

                # Draw waveform
                points = []
                x_step = wf_w / max(len(data) - 1, 1)
                for i, sample in enumerate(data):
                    x = wf_x1 + int(i * x_step)
                    # Normalize and scale
                    norm = max(-1, min(1, sample / 20000))  # Adjusted for lower signals
                    y = mid_y - int(norm * (wf_h // 2 - 2))
                    points.extend([x, y])

                if len(points) >= 4:
                    waveform_canvas.create_line(points, fill=color, width=2,
                                                smooth=True, tags="waveform")

        # Pulse the dot when transcribing
        if transcribing:
            waveform_canvas.itemconfig(popup_dot_id, fill="#3b82f6")
            waveform_canvas.itemconfig(popup_status_id, text="Transcribing...")

        root.after(40, update_popup)

# -----------------------------------------------------
# Settings Window
# -----------------------------------------------------

device_dropdown = None

def refresh_device_list():
    global device_dropdown
    if device_dropdown:
        devices = get_input_devices()
        names = ["System Default"] + [n for _, n in devices]
        device_dropdown.configure(values=names)

def show_settings():
    global settings_window, device_dropdown

    if settings_window and settings_window.winfo_exists():
        settings_window.lift()
        settings_window.focus_force()
        return

    settings_window = ctk.CTkToplevel(root)
    settings_window.title("Voice Transcribe")
    settings_window.geometry("380x480")
    settings_window.resizable(False, False)
    settings_window.attributes('-topmost', True)
    settings_window.after(100, lambda: settings_window.attributes('-topmost', False))

    # Title
    ctk.CTkLabel(settings_window, text="Voice Transcribe",
                 font=("Segoe UI", 18, "bold")).pack(pady=(20, 5))
    ctk.CTkLabel(settings_window, text=f"Hotkey: {hotkey.replace('+', ' + ').title()}",
                 font=("Segoe UI", 11), text_color="#7a7b8a").pack(pady=(0, 15))

    # Microphone
    mic_frame = ctk.CTkFrame(settings_window, fg_color="transparent")
    mic_frame.pack(fill='x', padx=25, pady=5)
    ctk.CTkLabel(mic_frame, text="Microphone", font=("Segoe UI", 12, "bold")).pack(anchor='w')

    devices = get_input_devices()
    device_names = ["System Default"] + [n for _, n in devices]
    device_map = {"System Default": None}
    device_map.update({n: i for i, n in devices})

    device_var = ctk.StringVar(value=get_current_device_name())
    device_dropdown = ctk.CTkOptionMenu(mic_frame, values=device_names, variable=device_var,
                                         width=300, height=32, font=("Segoe UI", 11))
    device_dropdown.pack(pady=(5, 0), anchor='w')

    def on_device_change(choice):
        global current_device_index
        current_device_index = device_map.get(choice)
        save_config()
        try:
            open_audio_stream()
        except:
            pass
    device_var.trace_add('write', lambda *_: on_device_change(device_var.get()))

    ctk.CTkButton(mic_frame, text="Refresh", width=80, height=28,
                  command=refresh_device_list).pack(pady=(8, 0), anchor='w')

    # Model
    model_frame = ctk.CTkFrame(settings_window, fg_color="transparent")
    model_frame.pack(fill='x', padx=25, pady=(15, 5))
    ctk.CTkLabel(model_frame, text="Model", font=("Segoe UI", 12, "bold")).pack(anchor='w')

    model_names = [v[0] for v in MODELS.values()]
    model_var = ctk.StringVar(value=MODELS[current_model][0])
    model_dropdown = ctk.CTkOptionMenu(model_frame, values=model_names, variable=model_var,
                                        width=300, height=32, font=("Segoe UI", 11))
    model_dropdown.pack(pady=(5, 0), anchor='w')

    def on_model_change(choice):
        global current_model
        for k, (n, _) in MODELS.items():
            if n == choice:
                current_model = k
                save_config()
                update_key_status()
                break
    model_var.trace_add('write', lambda *_: on_model_change(model_var.get()))

    # API Key status
    key_status_label = ctk.CTkLabel(model_frame, text="", font=("Segoe UI", 10))
    key_status_label.pack(anchor='w', pady=(5, 0))

    def update_key_status():
        has_key = bool(get_api_key(MODELS[current_model][1]))
        key_status_label.configure(
            text="API Key: OK" if has_key else "API Key: Missing",
            text_color="#4ade80" if has_key else "#f87171")
    update_key_status()

    # Quick Access section
    access_frame = ctk.CTkFrame(settings_window, fg_color="transparent")
    access_frame.pack(fill='x', padx=25, pady=(15, 5))
    ctk.CTkLabel(access_frame, text="Quick Access", font=("Segoe UI", 12, "bold")).pack(anchor='w')

    # Button row 1: Transcripts and API Keys
    row1 = ctk.CTkFrame(access_frame, fg_color="transparent")
    row1.pack(fill='x', pady=(8, 0))

    ctk.CTkButton(row1, text="Transcripts", width=140, height=32,
                  fg_color="#3b82f6", hover_color="#2563eb",
                  command=lambda: os.startfile(TRANSCRIPTS_FILE) if TRANSCRIPTS_FILE.exists()
                          else os.startfile(CONFIG_DIR)).pack(side='left', padx=(0, 8))

    ctk.CTkButton(row1, text="API Keys (.env)", width=140, height=32,
                  fg_color="#8b5cf6", hover_color="#7c3aed",
                  command=lambda: os.startfile(ENV_FILE) if ENV_FILE.exists()
                          else os.startfile(CONFIG_DIR)).pack(side='left')

    # Button row 2: Failed Recordings and Config
    row2 = ctk.CTkFrame(access_frame, fg_color="transparent")
    row2.pack(fill='x', pady=(8, 0))

    failed_count = len(list(FAILED_AUDIO_DIR.glob("*.wav")))
    failed_text = f"Failed Audio ({failed_count})" if failed_count > 0 else "Failed Audio"
    failed_color = "#ef4444" if failed_count > 0 else "#6b7280"
    failed_hover = "#dc2626" if failed_count > 0 else "#525252"

    ctk.CTkButton(row2, text=failed_text, width=140, height=32,
                  fg_color=failed_color, hover_color=failed_hover,
                  command=lambda: os.startfile(FAILED_AUDIO_DIR)).pack(side='left', padx=(0, 8))

    ctk.CTkButton(row2, text="Config Folder", width=140, height=32,
                  fg_color="#6b7280", hover_color="#525252",
                  command=lambda: os.startfile(CONFIG_DIR)).pack(side='left')

    # Close button
    ctk.CTkButton(settings_window, text="Close", width=100, height=32,
                  command=settings_window.destroy).pack(pady=(15, 20))

# -----------------------------------------------------
# Main
# -----------------------------------------------------

root = ctk.CTk()
root.withdraw()

def start_app():
    create_popup()
    threading.Thread(target=record_audio, daemon=True).start()
    threading.Thread(target=setup_tray, daemon=True).start()
    keyboard.add_hotkey(hotkey, lambda: root.after(0, toggle_recording))

start_app()
root.mainloop()
