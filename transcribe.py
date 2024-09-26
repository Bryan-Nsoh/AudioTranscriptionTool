import os
import pyaudio
import wave
import tempfile
from groq import Groq
from dotenv import dotenv_values
import time
import sys
import keyboard
import pyperclip
from plyer import notification
import threading
import random
import pyautogui

# Load environment variables
print("Current working directory:", os.getcwd())
env_path = os.path.join(os.path.dirname(__file__), ".env")
print(f"Looking for .env file at: {env_path}")
env_vars = dotenv_values(env_path)

# Check for API key
GROQ_API_KEY = env_vars.get("GROQ_API_KEY")
print(f"GROQ_API_KEY found in .env: {'Yes' if GROQ_API_KEY else 'No'}")
if not GROQ_API_KEY:
    print("Error: GROQ_API_KEY not found in .env file.")
    print(
        "Make sure you have a .env file in the same directory as this script with the line:"
    )
    print("GROQ_API_KEY=your_api_key_here")
    sys.exit(1)
else:
    print(f"GROQ_API_KEY from .env (first 5 chars): {GROQ_API_KEY[:5]}...")

# Global variables
recording = False
audio_frames = []
hotkey = 'ctrl+alt+shift+r'  # Define a unique global hotkey

def record_audio():
    global recording, audio_frames
    chunk = 1024
    format = pyaudio.paInt16
    channels = 1
    rate = 16000

    p = pyaudio.PyAudio()
    stream = p.open(
        format=format, channels=channels, rate=rate, input=True, frames_per_buffer=chunk
    )

    while True:
        if recording:
            data = stream.read(chunk)
            audio_frames.append(data)
        else:
            time.sleep(0.1)  # Sleep to reduce CPU usage when not recording

def save_audio_to_temp():
    global audio_frames
    if not audio_frames:
        return None

    filename = tempfile.mktemp(suffix=".wav")
    wf = wave.open(filename, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
    wf.setframerate(16000)
    wf.writeframes(b"".join(audio_frames))
    wf.close()
    print(f"Audio saved to temporary file: {filename}")
    return filename

def transcribe_audio(filename):
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
            return transcription, True
        except Exception as e:
            if attempt < max_retries - 1:
                delay = min(2**attempt + random.uniform(0, 1), max_delay)
                print(
                    f"Transcription attempt {attempt + 1} failed. Retrying in {delay:.2f} seconds..."
                )
                print(f"Error details: {str(e)}")
                time.sleep(delay)
            else:
                print(f"All transcription attempts failed. Error details: {str(e)}")
                return f"Transcription failed after {max_retries} attempts: {str(e)}", False

def toggle_recording():
    global recording, audio_frames
    recording = not recording
    if recording:
        print("Recording started...")
        audio_frames = []  # Clear previous frames
        notification.notify(
            title="Recording Started",
            message="Audio recording has begun.",
            timeout=5,
        )
    else:
        print("Recording stopped. Transcribing...")
        notification.notify(
            title="Recording Stopped",
            message="Audio recording has stopped. Transcribing...",
            timeout=5,
        )
        temp_audio_file = save_audio_to_temp()
        if temp_audio_file:
            transcription, success = transcribe_audio(temp_audio_file)
            print("Transcription:")
            print(transcription)
            if success:
                pyperclip.copy(transcription)
                notification.notify(
                    title="Transcription Complete",
                    message="Transcription has been copied to clipboard.",
                    timeout=5,
                )
                # Simulate paste operation
                time.sleep(0.5)  # Brief pause to ensure clipboard is updated
                pyautogui.hotkey('ctrl', 'v')
                os.remove(temp_audio_file)
                print(f"Temporary audio file removed: {temp_audio_file}")
            else:
                # Optionally, handle failed transcription
                notification.notify(
                    title="Transcription Failed",
                    message="Failed to transcribe audio.",
                    timeout=5,
                )
                os.remove(temp_audio_file)
                print(f"Temporary audio file removed: {temp_audio_file}")

def main():
    # Start the recording thread
    recording_thread = threading.Thread(target=record_audio, daemon=True)
    recording_thread.start()

    # Register the global hotkey
    print(f"Registering global hotkey: {hotkey}")
    keyboard.add_hotkey(hotkey, toggle_recording)

    print("Transcription tool is running. Press the global hotkey to start/stop recording.")
    print(f"Hotkey: {hotkey}")
    print("Press 'Ctrl+C' in the console to exit.")

    try:
        keyboard.wait()  # Keep the main thread alive
    except KeyboardInterrupt:
        print("Exiting...")

if __name__ == "__main__":
    main()
