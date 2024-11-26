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
from groq import Groq
from dotenv import dotenv_values
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import random  # Added import for random module

# -------------------------------
# Configuration and Initialization
# -------------------------------

# Disable PyAutoGUI's fail-safe feature
pyautogui.FAILSAFE = False  # WARNING: Disabling fail-safe is not recommended as it removes a safety mechanism.

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), ".env")
env_vars = dotenv_values(env_path)

# Check for API key
GROQ_API_KEY = env_vars.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("Error: GROQ_API_KEY not found in .env file.")
    print("Make sure you have a .env file in the same directory as this script with the line:")
    print("GROQ_API_KEY=your_api_key_here")
    sys.exit(1)
else:
    print("GROQ_API_KEY loaded successfully.")

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

    Args:
        color (str): Color of the circle (e.g., 'grey', 'red', 'green').

    Returns:
        PIL.Image.Image: The created icon image.
    """
    # Create a 64x64 image with transparent background
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Draw a filled circle
    draw.ellipse((8, 8, 56, 56), fill=color)
    return image

# Define tray icons for different states
icon_idle = create_icon('grey')         # Idle state
icon_recording = create_icon('red')     # Recording state
icon_transcribing = create_icon('green')  # Transcribing state

# Initialize tray icon with idle state
tray_icon = None

# -------------------------------
# Audio Recording Functions
# -------------------------------

def record_audio():
    """
    Continuously records audio in the background when the 'recording' flag is True.
    Handles batching of audio frames every 3 minutes.
    """
    global recording, audio_frames, current_batch_frames, transcription_buffer

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
            time.sleep(0.1)  # Sleep to reduce CPU usage when not recording

    stream.stop_stream()
    stream.close()
    p.terminate()

# -------------------------------
# Audio Processing Functions
# -------------------------------

def save_audio_to_temp(batch_frames):
    """
    Saves the provided audio frames to a temporary WAV file.

    Args:
        batch_frames (list): List of audio frame data.

    Returns:
        str or None: Path to the temporary WAV file, or None if saving failed.
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
        return None

def transcribe_audio(filename):
    """
    Sends the audio file to the Groq API for transcription.

    Args:
        filename (str): Path to the WAV audio file.

    Returns:
        tuple: (transcription text or error message, success flag)
    """
    client = Groq(api_key=GROQ_API_KEY)
    max_retries = 5
    max_delay = 120  # 2 minutes in seconds

    for attempt in range(max_retries):
        try:
            with open(filename, "rb") as file:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(filename), file.read()),
                    model="whisper-large-v3",
                    response_format="text",
                )
            print("Transcription successful.")
            return transcription, True
        except Exception as e:
            print(f"Transcription attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                delay = min(2 ** attempt + random.uniform(0, 1), max_delay)
                print(f"Retrying in {delay:.2f} seconds...")
                time.sleep(delay)
            else:
                print(f"All transcription attempts failed: {e}")
                return f"Transcription failed after {max_retries} attempts: {str(e)}", False

def process_batch(batch_frames):
    """
    Processes a batch of audio frames: saves to temp file, transcribes, and appends to transcription buffer.

    Args:
        batch_frames (list): List of audio frame data.
    """
    global transcription_buffer, transcribing

    with transcription_lock:
        transcribing = True
        update_tray_icon(state='transcribing')

    temp_audio_file = save_audio_to_temp(batch_frames)
    if temp_audio_file:
        transcription, success = transcribe_audio(temp_audio_file)
        if success:
            with transcription_lock:
                transcription_buffer += transcription + " "
            # Optionally, you can provide immediate feedback for each batch
            print("Batch transcription appended to buffer.")
        else:
            with transcription_lock:
                transcription_buffer += transcription + " "
            print("Batch transcription failed.")
        os.remove(temp_audio_file)
    else:
        print("Failed to process audio batch.")

    with transcription_lock:
        transcribing = False
        update_tray_icon(state='idle')

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
        audio_frames = []  # Clear previous frames
        current_batch_frames = []
        with transcription_lock:
            transcription_buffer = ""
        update_tray_icon(state='recording')
    else:
        print("Recording stopped. Processing remaining audio frames.")
        update_tray_icon(state='transcribing')
        transcribing = True

        # Process any remaining frames that did not complete a full batch
        if current_batch_frames:
            batch = current_batch_frames.copy()
            current_batch_frames.clear()
            process_batch(batch)

        # Wait until all transcription threads have finished
        while transcribing:
            time.sleep(0.5)

        # Copy the complete transcription buffer to clipboard
        with transcription_lock:
            if transcription_buffer.strip():
                pyperclip.copy(transcription_buffer.strip())
                # Simulate paste operation
                time.sleep(0.5)  # Brief pause to ensure clipboard is updated
                try:
                    pyautogui.hotkey('ctrl', 'v')
                    print("Transcription copied to clipboard and pasted.")
                except pyautogui.FailSafeException:
                    print("PyAutoGUI fail-safe triggered. Paste operation skipped.")
                except Exception as e:
                    print(f"An unexpected error occurred during paste operation: {e}")
            else:
                print("No transcription available to copy.")

        update_tray_icon(state='idle')
        print("Transcription process completed.")

def update_tray_icon(state='idle'):
    """
    Updates the tray icon based on the current state.

    Args:
        state (str): One of 'idle', 'recording', 'transcribing'.
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
    """
    Handler for the 'Toggle Recording' menu item.

    Args:
        icon (pystray.Icon): The tray icon instance.
        item (pystray.MenuItem): The menu item clicked.
    """
    toggle_recording()

def on_quit(icon, item):
    """
    Handler for the 'Quit' menu item to exit the application.

    Args:
        icon (pystray.Icon): The tray icon instance.
        item (pystray.MenuItem): The menu item clicked.
    """
    icon.stop()
    os._exit(0)  # Force exit all threads

def setup_tray():
    """
    Sets up the system tray icon with menu options.
    """
    global tray_icon
    menu = pystray.Menu(
        item('Toggle Recording', on_toggle),
        item('Quit', on_quit)
    )
    tray_icon = pystray.Icon("AudioTranscriptionTool", icon_idle, "Audio Transcription Tool", menu)
    tray_icon.run()

# -------------------------------
# Main Function
# -------------------------------

def main():
    """
    Main function to start the application.
    """
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

    try:
        while True:
            time.sleep(1)  # Keep the main thread alive
    except KeyboardInterrupt:
        print("Exiting Audio Transcription Tool.")
        sys.exit(0)

if __name__ == "__main__":
    main()
