"""Test microphone is actually capturing audio"""
import pyaudio
import struct
import math

CHUNK = 1024
RATE = 16000
RECORD_SECONDS = 3

p = pyaudio.PyAudio()

# List all input devices
print("=== Available Input Devices ===")
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if info['maxInputChannels'] > 0:
        print(f"  [{i}] {info['name']} (inputs: {info['maxInputChannels']})")

default_info = p.get_default_input_device_info()
print(f"\n=== Default Input: [{default_info['index']}] {default_info['name']} ===")

# Record a few seconds
print(f"\nRecording {RECORD_SECONDS} seconds... SPEAK NOW!")
stream = p.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)

frames = []
max_amplitude = 0
for _ in range(int(RATE / CHUNK * RECORD_SECONDS)):
    data = stream.read(CHUNK, exception_on_overflow=False)
    frames.append(data)
    # Calculate amplitude
    samples = struct.unpack('<' + 'h' * CHUNK, data)
    chunk_max = max(abs(s) for s in samples)
    if chunk_max > max_amplitude:
        max_amplitude = chunk_max

stream.stop_stream()
stream.close()
p.terminate()

# Analyze
total_frames = len(frames)
total_bytes = sum(len(f) for f in frames)
print(f"\nRecorded: {total_frames} chunks, {total_bytes} bytes")
print(f"Max amplitude: {max_amplitude} / 32767 ({max_amplitude/32767*100:.1f}%)")

if max_amplitude < 100:
    print("\n!!! PROBLEM: Audio level is EXTREMELY LOW - mic may be muted or wrong device")
elif max_amplitude < 500:
    print("\n!!! WARNING: Audio level is very low - check mic gain")
elif max_amplitude < 2000:
    print("\nAudio level is low but should work")
else:
    print("\nAudio level looks good!")
