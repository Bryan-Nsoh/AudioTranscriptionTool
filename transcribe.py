import os
import sys
import time
import threading
import pyaudio
import wave
import tempfile
import pyperclip
import pyautogui
import keyboard
from dotenv import dotenv_values
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import random
import traceback
import google.generativeai as genai

# -------------------------------
# Configuration and Initialization
# -------------------------------

# Disable PyAutoGUI's fail-safe feature
pyautogui.FAILSAFE = False  # WARNING: Disabling fail-safe is not recommended as it removes a safety mechanism.

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), ".env")
env_vars = dotenv_values(env_path)

# Check for Gemini API key
GEMINI_API_KEY = env_vars.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in .env file.")
    print("Make sure you have a .env file in the same directory as this script with the line:")
    print("GEMINI_API_KEY=your_gemini_api_key_here")
    sys.exit(1)
else:
    print("GEMINI_API_KEY loaded successfully.")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

# Initialize Gemini Model
model = genai.GenerativeModel("gemini-1.5-flash")

# Global variables
recording = False
transcribing = False
audio_frames = []
current_batch_frames = []
transcription_buffer = ""
transcription_lock = threading.Lock()
hotkey = 'ctrl+alt+shift+r'  # Define a unique global hotkey

# Batch configuration
BATCH_DURATION_SECONDS = 180  # 3 minutes
RATE = 16000  # Sample rate
CHUNK = 1024  # Frames per buffer
FRAMES_PER_BATCH = int((RATE * BATCH_DURATION_SECONDS) / CHUNK)

# -------------------------------
# Icon Creation Functions
# -------------------------------

def create_icon(color):
    """
    Creates a simple circular icon of the specified color.
    """
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return image

icon_idle = create_icon('grey')         # Idle state
icon_recording = create_icon('red')     # Recording state
icon_transcribing = create_icon('green') # Transcribing state

tray_icon = None

# -------------------------------
# Audio Recording Functions
# -------------------------------

def record_audio():
    """
    Continuously records audio in the background when the 'recording' flag is True.
    Handles batching of audio frames every 3 minutes.
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
        print(f"Failed to open audio stream: {e}")
        sys.exit(1)

    try:
        while True:
            if recording:
                try:
                    data = stream.read(CHUNK)
                    audio_frames.append(data)
                    current_batch_frames.append(data)

                    if len(current_batch_frames) >= FRAMES_PER_BATCH:
                        # Extract the batch
                        batch = current_batch_frames.copy()
                        current_batch_frames.clear()
                        # Start a new thread for transcription
                        threading.Thread(target=process_batch, args=(batch,), daemon=True).start()
                except Exception as e:
                    print(f"Error reading audio stream: {e}")
                    recording = False
                    update_tray_icon(state='idle')
            else:
                time.sleep(0.1)
    except Exception as e:
        print(f"Exception in record_audio thread: {e}")
        traceback.print_exc()
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

# -------------------------------
# Audio Processing Functions
# -------------------------------

def save_audio_to_temp(batch_frames):
    """
    Saves the provided audio frames to a temporary WAV file.
    """
    if not batch_frames:
        print("No audio frames to save.")
        return None

    try:
        filename = tempfile.mktemp(suffix=".wav")
        wf = wave.open(filename, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(batch_frames))
        wf.close()
        print(f"Audio batch saved to temporary file: {filename}")
        return filename
    except Exception as e:
        print(f"Failed to save audio: {e}")
        traceback.print_exc()
        return None

def transcribe_audio(filename):
    """
    Sends the audio file to the Gemini API for transcription.
    """
    try:
        with open(filename, "rb") as file:
            data = file.read()

        prompt = "Generate a verbatim transcript of the speech. Ensure the transcription captures all spoken words and accurately represents the content of the audio. Focus on transcribing the speech clearly and avoid adding any additional commentary or interpretation."
        response = model.generate_content([
            prompt,
            {
                "mime_type": "audio/wav",
                "data": data
            }
        ])
        print("Transcription successful.")
        return response.text, True
    except Exception as e:
        print(f"Transcription failed: {e}")
        traceback.print_exc()
        return f"Transcription failed: {str(e)}", False

def process_batch(batch_frames):
    """
    Processes a batch of audio frames: saves to temp file, transcribes, and appends to transcription buffer.
    """
    global transcription_buffer

    try:
        temp_audio_file = save_audio_to_temp(batch_frames)
        if temp_audio_file:
            transcription, success = transcribe_audio(temp_audio_file)
            if success:
                with transcription_lock:
                    transcription_buffer += transcription + " "
                print("Batch transcription appended to buffer.")
            else:
                with transcription_lock:
                    transcription_buffer += transcription + " "
                print("Batch transcription failed.")
            os.remove(temp_audio_file)
        else:
            print("Failed to process audio batch.")
    except Exception as e:
        print(f"Exception in process_batch: {e}")
        traceback.print_exc()

# -------------------------------
# Tray Icon and UI Functions
# -------------------------------

def toggle_recording():
    """
    Toggles the recording state. Starts recording if idle, stops and finalizes transcription if recording.
    """
    global recording, audio_frames, current_batch_frames, transcription_buffer, transcribing

    if transcribing:
        print("Transcription in progress. Please wait.")
        return

    recording = not recording
    if recording:
        print("Recording started.")
        audio_frames = []
        current_batch_frames = []
        with transcription_lock:
            transcription_buffer = ""
        update_tray_icon(state='recording')
    else:
        print("Recording stopped. Processing remaining audio frames.")
        transcribing = True
        update_tray_icon(state='transcribing')

        if current_batch_frames:
            batch = current_batch_frames.copy()
            current_batch_frames.clear()
            threading.Thread(target=process_remaining_batches, args=(batch,), daemon=True).start()
        else:
            threading.Thread(target=finalize_transcription, daemon=True).start()

def process_remaining_batches(batch):
    """
    Processes any remaining audio frames after recording is stopped.
    """
    try:
        process_batch(batch)
    except Exception as e:
        print(f"Exception in process_remaining_batches: {e}")
        traceback.print_exc()
    finally:
        finalize_transcription()

def finalize_transcription():
    """
    Finalizes the transcription process by copying the transcription buffer to the clipboard.
    """
    global transcribing
    with transcription_lock:
        if transcription_buffer.strip():
            pyperclip.copy(transcription_buffer.strip())
            # Simulate paste operation
            time.sleep(0.5)
            try:
                pyautogui.hotkey('ctrl', 'v')
                print("Transcription copied to clipboard and pasted.")
            except pyautogui.FailSafeException:
                print("PyAutoGUI fail-safe triggered. Paste operation skipped.")
            except Exception as e:
                print(f"An unexpected error occurred during paste operation: {e}")
                traceback.print_exc()
        else:
            print("No transcription available to copy.")
    transcribing = False
    update_tray_icon(state='idle')
    print("Transcription process completed.")

def update_tray_icon(state='idle'):
    """
    Updates the tray icon based on the current state.
    """
    if tray_icon is None:
        return

    if state == 'idle':
        tray_icon.icon = icon_idle
    elif state == 'recording':
        tray_icon.icon = icon_recording
    elif state == 'transcribing':
        tray_icon.icon = icon_transcribing

def on_toggle(icon, item):
    toggle_recording()

def on_quit(icon, item):
    icon.stop()
    os._exit(0)

def setup_tray():
    menu = pystray.Menu(
        item('Toggle Recording', on_toggle),
        item('Quit', on_quit)
    )
    global tray_icon
    tray_icon = pystray.Icon("AudioTranscriptionTool", icon_idle, "Audio Transcription Tool", menu)
    tray_icon.run()

# -------------------------------
# Main Function
# -------------------------------

def main():
    try:
        # Start the recording thread
        recording_thread = threading.Thread(target=record_audio, daemon=True)
        recording_thread.start()
        print("Recording thread started.")

        # Setup the system tray icon in a separate thread
        tray_thread = threading.Thread(target=setup_tray, daemon=True)
        tray_thread.start()
        print("System tray icon setup complete.")

        # Register the global hotkey
        try:
            keyboard.add_hotkey(hotkey, toggle_recording)
            print(f"Global hotkey '{hotkey}' registered.")
        except Exception as e:
            print(f"Failed to register hotkey '{hotkey}': {e}")
            sys.exit(1)

        print("Audio Transcription Tool is running in the background.")
        print(f"Press the global hotkey '{hotkey}' to start/stop recording.")
        print("Right-click the tray icon and select 'Toggle Recording' to start/stop recording.")
        print("Right-click the tray icon and select 'Quit' to exit the application.")

        while True:
            time.sleep(1)
    except Exception as e:
        print(f"Exception in main thread: {e}")
        traceback.print_exc()
    except KeyboardInterrupt:
        print("Exiting Audio Transcription Tool.")
        sys.exit(0)

if __name__ == "__main__":
    main()
