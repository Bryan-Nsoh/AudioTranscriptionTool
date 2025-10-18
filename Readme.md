# Audio Transcription Tool v2.0

Modern Windows-only audio transcription tool with intelligent silence detection and multi-provider fallback support.

## Features

- **OpenAI gpt-4o-mini-transcribe** as primary transcription service
- Optional **Groq Whisper-large-v3** and **Gemini 1.5 Flash** fallbacks
- **Silero VAD** with adjustable aggressiveness (toggle off at 0)
- Real-time recording with 3-minute batch processing
- System tray integration
- Configurable hotkeys
- Automatic clipboard paste

## Installation

### Using UV (Recommended)

```bash
# Install UV
pip install uv

# Install dependencies
uv pip install -r requirements.txt
```

### Using pip

```bash
pip install -r requirements.txt
```

## Configuration

1. Run the application: `uv run python src/transcribe_gui.py`
2. Click **Settings**
3. Configure:
   - **Transcription Service** (Auto/OpenAI/Groq/Gemini)
   - API key for the selected service(s)
   - **Hotkey** (default: Alt+R)
   - **Voice Detection Aggressiveness** (0–3, set to 0 to disable)

## Usage

1. Press the configured hotkey or click **Record**
2. Speak (silence is automatically filtered out)
3. Press hotkey again or click **Stop Recording**
4. Transcription automatically pastes to active window

## Building Executable

```bash
# Recreate PyInstaller build
uv tool run --with keyboard --with groq --with openai --with pyaudio --with pyperclip --with pystray --with pillow --with requests --with pyautogui --with google-generativeai --with torch --with onnxruntime ^
    pyinstaller --clean --distpath dist --workpath build --noconfirm transcribe_gui.spec
```

Executable will be in `dist/transcribe_gui/`

## Silence Detection

Silero VAD filters out non-speech audio in real-time:
- Saves API costs by skipping silence
- Adjust aggressiveness in Settings (higher = more aggressive filtering)
- Set to **0** to capture every frame (useful when debugging clipping)

## Troubleshooting

**VAD model fails to load:**
- First run downloads the Silero model via Torch Hub; ensure internet access or clear the Torch cache if it fails

**Microphone not detected:**
- Check Windows audio input settings
- Ensure no other application is using the microphone

**Transcription fails:**
- Verify API keys are correct
- Check internet connection
- Try fallback providers

## Architecture

```
Recording -> Silero VAD -> 3-min batches -> OpenAI -> (Groq) -> (Gemini) -> Clipboard -> Auto-paste
```

## Project Layout

```
AudioTranscriptionTool/
├── assets/
│   └── icons/
│       ├── recorder_icon.ico
│       └── recorder_icon.png
├── src/
│   └── transcribe_gui.py
├── .env
├── .gitignore
├── HANDOFF.md
├── LICENSE
├── README.md
├── pyproject.toml
├── requirements.txt
├── transcribe_gui.spec
└── uv.lock
```

## Requirements

- Windows 10/11
- Python 3.8+
- Active internet connection
- Microphone

## License

MIT
