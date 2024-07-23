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

# Explicitly read .env file
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

    print("Press 'Ctrl+Shift+R' to start/stop recording...")

    while True:
        if recording:
            data = stream.read(chunk)
            audio_frames.append(data)
        else:
            time.sleep(0.1)  # Sleep to reduce CPU usage when not recording


def save_audio():
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
            return transcription
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
                return f"Transcription failed after {max_retries} attempts: {str(e)}"


def toggle_recording():
    global recording, audio_frames
    recording = not recording
    if recording:
        print("Recording started...")
        audio_frames = []  # Clear previous frames
    else:
        print("Recording stopped. Transcribing...")
        audio_file = save_audio()
        if audio_file:
            transcription = transcribe_audio(audio_file)
            print("Transcription:")
            print(transcription)
            pyperclip.copy(transcription)
            notification.notify(
                title="Transcription Complete",
                message="Transcription has been copied to clipboard.",
                timeout=10,
            )
            os.remove(audio_file)
            print(f"Temporary audio file removed: {audio_file}")


def main():
    keyboard.add_hotkey("ctrl+shift+r", toggle_recording)

    # Start the recording thread
    recording_thread = threading.Thread(target=record_audio)
    recording_thread.start()

    print("Transcription tool is running. Press 'Ctrl+C' to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting...")


if __name__ == "__main__":
    main()
