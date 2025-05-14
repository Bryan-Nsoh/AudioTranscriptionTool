#!/bin/bash

# Stop on first error
set -e

echo "Starting setup to build macOS Menu Bar App (AudioTranscriptionTool)..."
echo "This script uses RUMPS for the GUI. Applying robust argument handling."
echo "--------------------------------------------------------"

# --- Configuration ---
PYTHON_SCRIPT_NAME="transcribe_gui_macos.py"
APP_NAME="AudioTranscriptionTool"
REQUIREMENTS_FILE_NAME="requirements_macos.txt"
VENV_DIR_NAME="venv_build_macos"

ICON_FILE_APP_BUNDLE="recorder_icon.icns"
ICON_FILE_MENU_IDLE="recorder_icon.png"
ICON_FILE_MENU_ACTIVE="recording_active.png"
ICON_FILE_MENU_PROCESSING="processing_icon.png"

BUNDLE_ID="com.yourname.audiotranscriptiontool" # IMPORTANT: Change com.yourname

# --- Paths ---
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PYTHON_SCRIPT_PATH="$SCRIPT_DIR/$PYTHON_SCRIPT_NAME"
REQUIREMENTS_FILE_PATH="$SCRIPT_DIR/$REQUIREMENTS_FILE_NAME"
ICON_PATH_APP_BUNDLE="$SCRIPT_DIR/$ICON_FILE_APP_BUNDLE"
ICON_PATH_MENU_IDLE="$SCRIPT_DIR/$ICON_FILE_MENU_IDLE"
ICON_PATH_MENU_ACTIVE="$SCRIPT_DIR/$ICON_FILE_MENU_ACTIVE"
ICON_PATH_MENU_PROCESSING="$SCRIPT_DIR/$ICON_FILE_MENU_PROCESSING"

BUILD_ARTIFACTS_DIR_NAME="${APP_NAME}_MacOS_Build_Output"
BUILD_ARTIFACTS_PATH="$SCRIPT_DIR/$BUILD_ARTIFACTS_DIR_NAME"

# --- Sanity Checks ---
echo "Performing sanity checks..."
if [ ! -f "$PYTHON_SCRIPT_PATH" ]; then echo "ERROR: Python script '$PYTHON_SCRIPT_NAME' not found. Exiting."; exit 1; fi
if [ ! -f "$REQUIREMENTS_FILE_PATH" ]; then echo "ERROR: Requirements file '$REQUIREMENTS_FILE_NAME' not found. Exiting."; exit 1; fi
if ! command -v python3 &> /dev/null; then echo "ERROR: Python 3 not found. Please install it. Exiting."; exit 1; fi
echo "✓ Python 3 found: $(python3 --version)"
if ! command -v brew &> /dev/null; then echo "ERROR: Homebrew not found. Install from brew.sh. Exiting."; exit 1; fi
echo "✓ Homebrew found."

# --- Prepare PyInstaller Command Arguments Conditionally ---
declare -a PYINSTALLER_CMD_ARGS

PYINSTALLER_CMD_ARGS+=(--name "$APP_NAME")
PYINSTALLER_CMD_ARGS+=(--windowed) 
PYINSTALLER_CMD_ARGS+=(--distpath "$BUILD_ARTIFACTS_PATH/dist")
PYINSTALLER_CMD_ARGS+=(--workpath "$BUILD_ARTIFACTS_PATH/build_pyinstaller_temp")
PYINSTALLER_CMD_ARGS+=(--osx-bundle-identifier "$BUNDLE_ID")
PYINSTALLER_CMD_ARGS+=(--clean)

if [ -f "$ICON_PATH_APP_BUNDLE" ]; then
    echo "✓ Found app bundle icon: '$ICON_FILE_APP_BUNDLE'"
    PYINSTALLER_CMD_ARGS+=(--icon "$ICON_PATH_APP_BUNDLE")
else
    echo "WARNING: App bundle icon '$ICON_FILE_APP_BUNDLE' not found. Building with default icon."
fi

ICON_VARS_TO_CHECK=(ICON_PATH_MENU_IDLE ICON_PATH_MENU_ACTIVE ICON_PATH_MENU_PROCESSING)
for icon_var_name in "${ICON_VARS_TO_CHECK[@]}"; do
    icon_path_val="${!icon_var_name}"
    icon_filename_val=$(basename "$icon_path_val")
    if [ -f "$icon_path_val" ]; then
        echo "✓ Found menu icon for bundling: '$icon_filename_val'"
        PYINSTALLER_CMD_ARGS+=(--add-data "$icon_path_val:.")
    else
        echo "WARNING: Menu icon '$icon_filename_val' not found (expected at: $icon_path_val). Appearance may be affected."
    fi
done

PYINSTALLER_CMD_ARGS+=(--hidden-import="plyer.platforms.macosx.notification") # Kept for now, harmless if plyer is present
PYINSTALLER_CMD_ARGS+=(--hidden-import="plyer.platforms.macosx.libs.osxnotifications") # Kept for now
# PYINSTALLER_CMD_ARGS+=(--hidden-import="pyobjus") # REMOVED
PYINSTALLER_CMD_ARGS+=("$PYTHON_SCRIPT_PATH")
echo "✓ PyInstaller arguments prepared."
echo "✓ Sanity checks complete."

# --- Install PortAudio ---
echo "Checking/Installing portaudio..."
if ! brew list portaudio &>/dev/null; then brew install portaudio; echo "✓ Portaudio installed."; else echo "✓ Portaudio already installed."; fi

# --- Prepare Build Directory ---
if [ -d "$BUILD_ARTIFACTS_PATH" ]; then rm -rf "$BUILD_ARTIFACTS_PATH"; fi
mkdir -p "$BUILD_ARTIFACTS_PATH"; echo "✓ Build directory prepared."
BUILD_LOG_FILE="$BUILD_ARTIFACTS_PATH/build_log.txt"
echo "Build logs will be at: $BUILD_LOG_FILE"

# --- Setup Virtual Environment & Install Packages ---
VENV_PATH_IN_BUILD_DIR="$BUILD_ARTIFACTS_PATH/$VENV_DIR_NAME"
echo "Creating Python venv for build..."
python3 -m venv "$VENV_PATH_IN_BUILD_DIR"; echo "✓ Build venv created."
PIP_IN_VENV="$VENV_PATH_IN_BUILD_DIR/bin/pip"
echo "Installing packages into build venv..."
"$PIP_IN_VENV" install --upgrade pip >> "$BUILD_LOG_FILE" 2>&1
if ! "$PIP_IN_VENV" install -r "$REQUIREMENTS_FILE_PATH" >> "$BUILD_LOG_FILE" 2>&1; then echo "ERROR: Failed to install requirements. Check $BUILD_LOG_FILE."; exit 1; fi
if ! "$PIP_IN_VENV" install pyinstaller >> "$BUILD_LOG_FILE" 2>&1; then echo "ERROR: Failed to install PyInstaller. Check $BUILD_LOG_FILE."; exit 1; fi
echo "✓ Build packages installed."

# --- Build Application with PyInstaller ---
PYINSTALLER_IN_VENV="$VENV_PATH_IN_BUILD_DIR/bin/pyinstaller"
echo "Building '$APP_NAME.app'... This may take some time."
echo "PyInstaller command will use arguments: ${PYINSTALLER_CMD_ARGS[@]}"
"$PYINSTALLER_IN_VENV" "${PYINSTALLER_CMD_ARGS[@]}" >> "$BUILD_LOG_FILE" 2>&1
APP_BUNDLE_PATH="$BUILD_ARTIFACTS_PATH/dist/$APP_NAME.app"

# --- Verification and Final Instructions ---
if [ -d "$APP_BUNDLE_PATH" ]; then
    echo ""
    echo "--------------------------------------------------------"
    echo "BUILD SUCCESSFUL!"
    echo "--------------------------------------------------------"
    echo "Application Bundle: '$APP_BUNDLE_PATH'"
    echo "To run:"
    echo "1. **CRITICAL:** Copy your '.env' file (with API keys) into:"
    echo "   '$BUILD_ARTIFACTS_PATH/dist/' (next to '$APP_NAME.app')."
    echo "   Cmd: cp \"$SCRIPT_DIR/.env\" \"$BUILD_ARTIFACTS_PATH/dist/\""
    echo "2. Open Finder, go to '$BUILD_ARTIFACTS_PATH/dist/'."
    echo "3. Double-click '$APP_NAME.app'."
    echo "   (First run: Right-click > Open if macOS blocks it)."
    echo "4. Grant Microphone permissions when prompted."
    echo "LOGGING: Check '${APP_NAME}_Logs' folder next to the .app (in '$BUILD_ARTIFACTS_PATH/dist/') for logs after running."
    echo "--------------------------------------------------------"
else
    echo "--------------------------------------------------------"
    echo "ERROR: BUILD FAILED."
    echo "App bundle not found: '$APP_BUNDLE_PATH'."
    echo "Check build log: $BUILD_LOG_FILE"
    echo "--------------------------------------------------------"
    exit 1
fi
exit 0