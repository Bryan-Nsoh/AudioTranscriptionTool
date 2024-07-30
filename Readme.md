# Audio Transcription Tool

## Description

This Audio Transcription Tool is a Python-based application that allows users to record audio and automatically transcribe it using the Groq API. The tool runs continuously in the background, waiting for user input to start and stop recording. Once a recording is stopped, it's automatically transcribed, and the transcription is copied to the clipboard for easy pasting.

## Features

- Continuous operation with hotkey-triggered recording
- Arbitrary-length audio recording
- Automatic transcription using Groq API
- Clipboard integration for easy access to transcriptions
- Desktop notifications upon transcription completion

## Requirements

- Python 3.7+
- Groq API key
- Required Python packages (see `requirements.txt`)

## Setup

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/audio-transcription-tool.git
   cd audio-transcription-tool
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv .venv
   source .venv/bin/activate  # On Windows, use `.venv\Scripts\activate`
   ```

3. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root directory and add your Groq API key:
   ```
   GROQ_API_KEY=your_api_key_here
   ```

## Usage

1. Run the script:
   ```
   python transcribe.py
   ```

2. The script will run continuously in the background. Use the following hotkeys:
   - Press `Ctrl+Shift+R` to start recording
   - Press `Ctrl+Shift+R` again to stop recording and trigger transcription
   - The transcription will be automatically copied to your clipboard
   - A desktop notification will appear when transcription is complete

3. To exit the script, press `Ctrl+C` in the console.

## Creating a Shortcut (Windows)

To create a desktop shortcut for easy access:

1. Right-click on your desktop and select "New" > "Shortcut"
2. Enter the following as the location:
   ```
   %ComSpec% /k "cd /d path\to\your\project && .venv\Scripts\activate && python transcribe.py && pause"
   ```
   Replace `path\to\your\project` with the actual path to your project directory.
3. Name your shortcut and click "Finish"

## Troubleshooting

- If you encounter any issues with the Groq API key, ensure that your `.env` file is in the same directory as the `transcribe.py` script and contains the correct API key.
- Make sure all required packages are installed by running `pip install -r requirements.txt`.
- If you're having trouble with audio recording, ensure that your microphone is properly connected and set as the default input device.

## Contributing

Contributions to this project are welcome. Please fork the repository and submit a pull request with your changes.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- This project uses the Groq API for audio transcription.
- Thanks to the developers of PyAudio, keyboard, pyperclip, and plyer for their excellent libraries.