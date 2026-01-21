"""Test transcription with a generated audio file"""
import os
import wave
import struct
import math
from dotenv import load_dotenv
load_dotenv(r"C:\Users\bryan\AppData\Roaming\VoiceTranscribe\.env")

from openai import OpenAI

# Generate a simple test audio file (1 second of silence + tone)
def generate_test_audio(filename):
    sample_rate = 16000
    duration = 1.0
    freq = 440  # A note

    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        # Generate samples
        samples = []
        for i in range(int(sample_rate * duration)):
            t = i / sample_rate
            # Mix of silence and tone
            val = int(32767 * 0.3 * math.sin(2 * math.pi * freq * t))
            samples.append(struct.pack('<h', val))
        wf.writeframes(b''.join(samples))

# Create test file
test_file = "tmp/test_audio.wav"
generate_test_audio(test_file)
print(f"Generated: {test_file}")

# Try transcription with the model
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

print("\nTrying gpt-4o-mini-transcribe...")
try:
    with open(test_file, "rb") as f:
        response = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=f,
            response_format="text",
            language="en"
        )
    print(f"Response type: {type(response)}")
    print(f"Response: '{response}'")
    print(f"Response length: {len(str(response)) if response else 0}")
except Exception as e:
    print(f"ERROR: {e}")

# Also try whisper-1 for comparison
print("\nTrying whisper-1...")
try:
    with open(test_file, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="text",
            language="en"
        )
    print(f"Response: '{response}'")
except Exception as e:
    print(f"ERROR: {e}")

os.remove(test_file)
