import os
import pyaudio
import wave
import tempfile
from groq import Groq
from dotenv import dotenv_values
from datetime import datetime
import re
import time
import sys

# Explicitly read .env file
print("Current working directory:", os.getcwd())
env_path = os.path.join(os.path.dirname(__file__), '.env')
print(f"Looking for .env file at: {env_path}")
env_vars = dotenv_values(env_path)

# Check for API key
GROQ_API_KEY = env_vars.get("GROQ_API_KEY")
print(f"GROQ_API_KEY found in .env: {'Yes' if GROQ_API_KEY else 'No'}")
if not GROQ_API_KEY:
    print("Error: GROQ_API_KEY not found in .env file.")
    print("Make sure you have a .env file in the same directory as this script with the line:")
    print("GROQ_API_KEY=your_api_key_here")
    sys.exit(1)
else:
    print(f"GROQ_API_KEY from .env (first 5 chars): {GROQ_API_KEY[:5]}...")

def record_audio(duration=5):
    print(f"Recording audio for {duration} seconds...")
    start_time = time.time()
    
    chunk = 1024
    format = pyaudio.paInt16
    channels = 1
    rate = 16000

    p = pyaudio.PyAudio()

    stream = p.open(format=format,
                    channels=channels,
                    rate=rate,
                    input=True,
                    frames_per_buffer=chunk)

    frames = []

    for _ in range(0, int(rate / chunk * duration)):
        data = stream.read(chunk)
        frames.append(data)

    stream.stop_stream()
    stream.close()
    p.terminate()

    end_time = time.time()
    print(f"Recording completed in {end_time - start_time:.2f} seconds")

    return frames, rate

def save_audio(frames, rate):
    start_time = time.time()
    filename = tempfile.mktemp(suffix=".wav")
    wf = wave.open(filename, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
    wf.setframerate(rate)
    wf.writeframes(b''.join(frames))
    wf.close()
    end_time = time.time()
    print(f"Audio saved to temporary file in {end_time - start_time:.2f} seconds")
    return filename

def transcribe_audio(filename):
    start_time = time.time()
    client = Groq(api_key=GROQ_API_KEY)

    with open(filename, "rb") as file:
        try:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(filename), file.read()),
                model="whisper-large-v3",
                response_format="text"
            )
            end_time = time.time()
            print(f"Transcription completed in {end_time - start_time:.2f} seconds")
            return transcription
        except Exception as e:
            end_time = time.time()
            print(f"Transcription failed in {end_time - start_time:.2f} seconds")
            print(f"Error details: {str(e)}")
            return f"Transcription failed: {str(e)}"

def save_transcription(transcription):
    start_time = time.time()
    # Clean the transcription text to create a valid filename
    words = re.findall(r'\w+', transcription.lower())
    first_words = '_'.join(words[:3]) if len(words) >= 3 else '_'.join(words)
    
    # Get current date
    current_date = datetime.now().strftime("%Y%m%d")
    
    # Create filename
    filename = f"{first_words}_{current_date}.txt"
    
    # Ensure the filename is valid and not too long
    filename = re.sub(r'[^\w\-_\. ]', '_', filename)[:255]
    
    # Create 'transcriptions' folder if it doesn't exist
    os.makedirs('transcriptions', exist_ok=True)
    
    # Save the transcription
    filepath = os.path.join('transcriptions', filename)
    with open(filepath, 'w') as f:
        f.write(transcription)
    
    end_time = time.time()
    print(f"Transcription saved to file in {end_time - start_time:.2f} seconds")
    return filepath

def main():
    overall_start_time = time.time()

    print("Starting transcription process...")

    # Record audio
    frames, rate = record_audio(duration=5)
    
    # Save audio to temporary file
    audio_file = save_audio(frames, rate)

    # Transcribe audio
    transcription = transcribe_audio(audio_file)
    print("Transcription:")
    print(transcription)

    # Save transcription to file
    if not isinstance(transcription, str) or not transcription.startswith("Transcription failed"):
        saved_file = save_transcription(transcription)
        print(f"Transcription saved to: {saved_file}")
    else:
        print("Transcription failed, not saving to file.")

    # Clean up
    os.remove(audio_file)
    print(f"Temporary audio file removed: {audio_file}")

    overall_end_time = time.time()
    print(f"Total process completed in {overall_end_time - overall_start_time:.2f} seconds")

if __name__ == "__main__":
    main()