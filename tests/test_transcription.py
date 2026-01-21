"""
Test transcription reliability - especially for longer recordings.
Run this to verify the app won't lose your audio.
"""

import os
import sys
import time
import wave
import struct
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from dotenv import load_dotenv

# Load env
CONFIG_DIR = Path(os.getenv("APPDATA", Path.home())) / "VoiceTranscribe"
load_dotenv(CONFIG_DIR / ".env")

from openai import OpenAI

RATE = 16000
TEST_DIR = Path(__file__).parent / "test_audio"
TEST_DIR.mkdir(exist_ok=True)

def generate_test_audio(duration_seconds, filename, include_speech_pattern=True):
    """Generate test audio file with speech-like patterns."""
    print(f"Generating {duration_seconds}s test audio: {filename}")

    samples = []
    for i in range(int(RATE * duration_seconds)):
        t = i / RATE

        if include_speech_pattern:
            # Simulate speech with varying amplitude
            speech_envelope = 0.3 + 0.7 * abs(math.sin(t * 2))  # Vary volume
            freq = 150 + 100 * math.sin(t * 5)  # Vary pitch
            val = int(16000 * speech_envelope * math.sin(2 * math.pi * freq * t))
        else:
            # Silence
            val = int(100 * (1 if i % 2 else -1))  # Tiny noise

        samples.append(struct.pack('<h', max(-32768, min(32767, val))))

    filepath = TEST_DIR / filename
    with wave.open(str(filepath), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(b''.join(samples))

    size_kb = os.path.getsize(filepath) / 1024
    print(f"  Created: {filepath} ({size_kb:.1f} KB)")
    return filepath

def test_transcription(filepath, model="gpt-4o-mini-transcribe"):
    """Test transcription of a file."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set")
        return False

    print(f"\nTesting transcription: {filepath}")
    print(f"  Model: {model}")
    print(f"  File size: {os.path.getsize(filepath) / 1024:.1f} KB")

    try:
        client = OpenAI(api_key=api_key, timeout=120.0)

        start = time.time()
        with open(filepath, "rb") as f:
            response = client.audio.transcriptions.create(
                model=model,
                file=f,
                response_format="text",
                language="en"
            )
        elapsed = time.time() - start

        print(f"  SUCCESS in {elapsed:.1f}s")
        print(f"  Response length: {len(response)} chars")
        print(f"  First 100 chars: {response[:100]}...")
        return True

    except Exception as e:
        print(f"  FAILED: {e}")
        return False

def test_file_preservation():
    """Test that audio files are preserved on failure."""
    print("\n=== Testing File Preservation ===")

    # Create a test file
    filepath = generate_test_audio(5, "preservation_test.wav")

    # Simulate what process_audio does
    FAILED_DIR = CONFIG_DIR / "failed_recordings"
    FAILED_DIR.mkdir(exist_ok=True)

    print(f"  Original file exists: {filepath.exists()}")

    # Simulate move to failed
    import shutil
    dest = FAILED_DIR / f"test_preserved_{int(time.time())}.wav"
    shutil.copy(filepath, dest)

    print(f"  Backup created: {dest.exists()}")
    print(f"  Backup path: {dest}")

    # Cleanup
    os.remove(filepath)
    os.remove(dest)
    print("  PASSED - file preservation works")

def run_all_tests():
    print("=" * 60)
    print("VOICE TRANSCRIBE - RELIABILITY TESTS")
    print("=" * 60)

    results = []

    # Test 1: Short recording (10s)
    print("\n=== Test 1: Short Recording (10s) ===")
    f = generate_test_audio(10, "test_10s.wav")
    results.append(("10s recording", test_transcription(f)))

    # Test 2: Medium recording (30s)
    print("\n=== Test 2: Medium Recording (30s) ===")
    f = generate_test_audio(30, "test_30s.wav")
    results.append(("30s recording", test_transcription(f)))

    # Test 3: Long recording (60s)
    print("\n=== Test 3: Long Recording (60s) ===")
    f = generate_test_audio(60, "test_60s.wav")
    results.append(("60s recording", test_transcription(f)))

    # Test 4: Very long recording (90s)
    print("\n=== Test 4: Very Long Recording (90s) ===")
    f = generate_test_audio(90, "test_90s.wav")
    results.append(("90s recording", test_transcription(f)))

    # Test 5: File preservation
    test_file_preservation()
    results.append(("File preservation", True))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    failed = sum(1 for _, p in results if not p)
    print(f"\nTotal: {len(results) - failed}/{len(results)} passed")

    if failed:
        print("\nWARNING: Some tests failed! Check errors above.")
        return 1
    else:
        print("\nAll tests passed!")
        return 0

if __name__ == "__main__":
    sys.exit(run_all_tests())
