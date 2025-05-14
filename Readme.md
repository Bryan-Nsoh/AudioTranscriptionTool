# Audio Transcription Tool

## Description

This Audio Transcription Tool is a Python-based application that allows users to record audio and automatically transcribe it using the Groq API. The tool provides a user-friendly interface appropriate for each operating system (menu bar app for macOS, system tray/hotkey for Windows) for easy recording and transcription.

## Features

-   **Cross-Platform:** Designed for both Windows and macOS.
-   **Easy Recording:**
    -   **macOS:** Menu bar interface to start/stop recording.
    -   **Windows:** System tray icon and global hotkey for recording control (details TBD based on `transcribe_gui_windows.py`).
-   Arbitrary-length audio recording.
-   Automatic transcription using the Groq API (Whisper model).
-   Clipboard integration: Transcribed text is automatically copied.
-   Desktop notifications for recording status and transcription completion.
-   **macOS:** Bundles into a standalone `.app` application.

## Requirements

-   Python 3.9+ (Python 3.13 has been tested on macOS; ensure your Python version is compatible with all dependencies, especially for Windows GUI elements and PyAudio).
-   Groq API key.
-   **For macOS:**
    -   Homebrew (for installing PortAudio).
    -   Xcode Command Line Tools (may be needed for some build dependencies).
-   **For Windows:**
    -   PortAudio (PyAudio may bundle this or require separate installation steps, e.g., via a pre-compiled wheel).

## General Setup (Common Steps)

1.  **Clone this repository:**
    ```bash
    git clone https://github.com/yourusername/audio-transcription-tool.git
    cd audio-transcription-tool
    ```

2.  **Create a `.env` file** in the project root directory and add your Groq API key:
    ```
    GROQ_API_KEY=your_api_key_here
    ```
    For the bundled macOS `.app`, this `.env` file will need to be placed next to the `.app` bundle after building. For script usage, it should be in the project root.

## macOS Setup & Usage

### 1. Prerequisites for macOS

-   **Homebrew:** If not installed, get it from [brew.sh](https://brew.sh).
-   **PortAudio:** Install via Homebrew:
    ```bash
    brew install portaudio
    ```
-   **Python 3:** Ensure you have a working Python 3 installation (Python 3.13 used for development).

### 2. Setup Virtual Environment & Install Packages for macOS

```bash
# Navigate to the project root
cd /path/to/audio-transcription-tool

# Create and activate a virtual environment
python3 -m venv .venv_macos
source .venv_macos/bin/activate

# Install macOS-specific requirements
pip install -r requirements_macos.txt
```

### 3. Running the Script Directly (for development/testing) on macOS

```bash
# Ensure your .env file is in the project root
# Ensure your virtual environment (.venv_macos) is activated
python3 transcribe_gui_macos.py
```
The application icon will appear in your menu bar.

### 4. Building the Standalone `.app` Bundle for macOS

The project includes a shell script to automate the bundling process using PyInstaller.

1.  **Provide Icons:**
    *   `recorder_icon.icns`: Your main application icon (e.g., 512x512).
    *   `recorder_icon.png`: Menu bar icon for idle state (e.g., 32x32 or 44x44, transparent background recommended).
    *   `recording_active.png`: Menu bar icon for recording state (same size as idle).
    *   `processing_icon.png`: Menu bar icon for processing state (same size as idle).
    Place these in the project root directory.

2.  **Customize Bundle ID (Optional but Recommended):**
    Open `setup_macos.sh` and change `BUNDLE_ID="com.yourname.audiotranscriptiontool"` to something unique.

3.  **Run the Build Script:**
    ```bash
    chmod +x setup_macos.sh
    ./setup_macos.sh
    ```
    This will create a `AudioTranscriptionTool_MacOS_Build_Output` directory containing the `dist` folder, which in turn holds `AudioTranscriptionTool.app`.

### 5. Running the Bundled `.app` on macOS

1.  **CRITICAL:** After building, copy your `.env` file from the project root into the `AudioTranscriptionTool_MacOS_Build_Output/dist/` directory, so it sits **next to** `AudioTranscriptionTool.app`.
2.  Navigate to `AudioTranscriptionTool_MacOS_Build_Output/dist/` in Finder.
3.  Double-click `AudioTranscriptionTool.app` to run.
    *   On the first run, you might need to right-click > Open if macOS Gatekeeper blocks it.
    *   Grant microphone permissions when prompted by the system.
4.  The application icon will appear in the menu bar. Click it to start/stop recording.
5.  Logs are stored in an `AudioTranscriptionTool_Logs` folder, also created in the `dist` directory (next to the `.app`). You can also access logs via the "View Logs" menu item.

## Windows Setup & Usage

### 1. Prerequisites for Windows

-   **Python 3:** Ensure you have a working Python 3 installation.
-   **PortAudio:** PyAudio needs PortAudio. If `pip install pyaudio` fails, you might need to find a pre-compiled PyAudio wheel for your Python version and Windows architecture, or ensure PortAudio DLLs are accessible.

### 2. Setup Virtual Environment & Install Packages for Windows

```bash
# Navigate to the project root
cd C:\path\to\audio-transcription-tool

# Create and activate a virtual environment
python -m venv .venv_windows
.venv_windows\Scripts\activate

# Install Windows-specific requirements
pip install -r requirements_windows.txt
```

### 3. Running the Script on Windows

```bash
# Ensure your .env file is in the project root
# Ensure your virtual environment (.venv_windows) is activated
python transcribe_gui_windows.py
```
(Details of the Windows GUI and hotkeys will depend on the implementation in `transcribe_gui_windows.py` using libraries like `pystray`, `keyboard`, etc.)

### 4. Creating a Shortcut (Windows) - Example

This example assumes your Windows script `transcribe_gui_windows.py` can run without needing a console window to stay open for hotkeys (e.g., if it's a background process with a system tray icon).

1.  Right-click on your desktop and select "New" > "Shortcut".
2.  For the location, you might use `pythonw.exe` to run without a console window:
    ```
    C:\path\to\your\project\.venv_windows\Scripts\pythonw.exe C:\path\to\your\project\transcribe_gui_windows.py
    ```
    Replace `C:\path\to\your\project` with the actual absolute path to your project directory.
    *Note: The `.env` file still needs to be accessible, typically from the project root where `transcribe_gui_windows.py` is located when run this way.*
3.  Name your shortcut and click "Finish".

## Important Note on Network Environments

This tool connects to the external Groq API (`https://api.groq.com`) for transcription. In highly secure network environments (e.g., corporate networks with SSL inspection proxies, strict firewalls like those at national labs), this connection may fail due to SSL certificate verification issues or firewall blocks.

-   **Symptoms:** Errors like `SSL: CERTIFICATE_VERIFY_FAILED` or `Connection error` in the logs when transcription is attempted.
-   **Resolution:**
    -   On standard home/personal networks, this should not be an issue if your system's CA certificates are up to date. The macOS version includes specific code to use `certifi`'s CA bundle for better compatibility.
    -   Within restrictive networks, you would need to consult your IT department to obtain necessary proxy CA certificates and configure the application (and potentially system proxy settings) to trust them. This can be complex and is dependent on organizational policy. **This tool, in its current form, may not function correctly inside such restrictive networks without significant IT-level network configuration or approvals.**

## Troubleshooting

-   **API Key:** Ensure your `.env` file is correctly placed (project root for scripts, next to the `.app` for macOS bundle) and contains the valid `GROQ_API_KEY`.
-   **Dependencies:** Make sure all required packages are installed for your respective OS (`requirements_macos.txt` or `requirements_windows.txt`).
-   **Audio Issues:**
    -   Ensure your microphone is connected and selected as the default system input device.
    -   On macOS, grant microphone permission to the app.
    -   If `PyAudio` installation fails, ensure `PortAudio` is correctly installed and accessible.
-   **Logs:** Check the `AudioTranscriptionTool_Logs` directory for detailed error messages. On macOS, this folder is created next to the `.app` bundle (or in the project directory if running the script directly).

## Contributing

Contributions to this project are welcome. Please fork the repository and submit a pull request with your changes.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

-   This project uses the Groq API for audio transcription.
-   Thanks to the developers of PyAudio, rumps (for macOS), pyperclip, and other supporting libraries.
