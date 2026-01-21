"""Quick test of OpenAI API and audio"""
import os
import sys
sys.path.insert(0, str(__file__).replace('tmp\\test_api.py', ''))

from dotenv import load_dotenv
load_dotenv(r"C:\Users\bryan\AppData\Roaming\VoiceTranscribe\.env")

# Test 1: Check API key
api_key = os.getenv("OPENAI_API_KEY", "")
print(f"API Key loaded: {'Yes' if api_key else 'NO - MISSING!'}")
print(f"Key prefix: {api_key[:20]}..." if api_key else "")

# Test 2: Check OpenAI connection
try:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    models = client.models.list()
    print(f"OpenAI API: Connected OK")
except Exception as e:
    print(f"OpenAI API ERROR: {e}")

# Test 3: Check audio device
try:
    import pyaudio
    p = pyaudio.PyAudio()
    info = p.get_default_input_device_info()
    print(f"Audio device: {info['name']}")
    p.terminate()
except Exception as e:
    print(f"Audio ERROR: {e}")
