import rumps # For GUI and now for notifications
import pyaudio
import wave
import threading
import os
import sys
from datetime import datetime
from groq import Groq
import pyperclip
# from plyer import notification # REMOVED
from dotenv import load_dotenv
from pathlib import Path
import time 
import logging
from logging.handlers import RotatingFileHandler

# --- Application Constants ---
APP_NAME = "AudioTranscriptionTool"
APP_VERSION = "1.0.0"

# --- Recording Parameters ---
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100 
TEMP_FILENAME_BASE = "_audiotranscriptiontool_temp_recording"

# --- Icon Filenames (these will be resolved to full paths later) ---
ICON_IDLE_FILENAME = "recorder_icon.png"
ICON_RECORDING_FILENAME = "recording_active.png"
ICON_PROCESSING_FILENAME = "processing_icon.png"
# General app icon for notifications (can be the same as idle or the .icns equivalent)
APP_NOTIFICATION_ICON_FILENAME = "recorder_icon.png" # or "recorder_icon.icns" if rumps handles .icns well

# --- Global Logger ---
logger = None 

# --- LOGGING SETUP ---
def setup_logging():
    global logger
    log_dir_name = f"{APP_NAME}_Logs"
    log_file_name = f"{APP_NAME.lower()}_app.log"
    
    base_log_path_str = "" 

    if getattr(sys, 'frozen', False) and sys.executable: 
        try:
            app_bundle_path = Path(sys.executable).resolve().parent.parent.parent 
            log_dir_base = app_bundle_path.parent 
            base_log_path = log_dir_base / log_dir_name
            base_log_path_str = str(base_log_path)
        except Exception as e_path:
            print(f"CRITICAL (Log Path Setup): Error determining bundled app log path: {e_path}. Falling back to user's home directory.")
            fallback_dir = Path.home() / f".{APP_NAME.lower()}_data" / "logs"
            base_log_path = fallback_dir
            base_log_path_str = str(fallback_dir) + " (fallback)"
    else: 
        base_log_path = Path(__file__).resolve().parent / log_dir_name
        base_log_path_str = str(base_log_path)

    try:
        os.makedirs(base_log_path, exist_ok=True)
        log_file_path = base_log_path / log_file_name
    except Exception as e_mkdir:
        print(f"CRITICAL (Log Directory Creation): Could not create log directory at {base_log_path_str}. Logging to Current Working Directory. Error: {e_mkdir}")
        log_file_path = Path.cwd() / log_file_name 
        base_log_path_str += f" (FAILED, using CWD: {Path.cwd()})"

    _logger = logging.getLogger(APP_NAME) 
    if _logger.hasHandlers():
        _logger.handlers.clear()
    _logger.setLevel(logging.DEBUG) 

    rf_handler = RotatingFileHandler(
        log_file_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
    )
    rf_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(module)s:%(lineno)d] - %(funcName)s - %(message)s')
    rf_handler.setFormatter(formatter)
    _logger.addHandler(rf_handler)
    
    if not getattr(sys, 'frozen', False):
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO) 
        ch.setFormatter(formatter)
        _logger.addHandler(ch)

    logger = _logger 

    logger.info(f"--- {APP_NAME} v{APP_VERSION} Logging System Initialized ---")
    logger.info(f"Logging to directory: {base_log_path.resolve() if base_log_path else 'N/A'}")
    logger.info(f"Log file path: {log_file_path.resolve()}")

    if getattr(sys, 'frozen', False):
        logger.info(f"Application is running as a bundled app.")
        if sys.executable:
            try:
                app_bundle_path = Path(sys.executable).resolve().parent.parent.parent
                logger.info(f"Executable path: {sys.executable}")
                logger.info(f"Deduced .app bundle path: {app_bundle_path}")
            except Exception as e: logger.error(f"Error deducing bundle path: {e}")
    else:
        logger.info(f"Application is running as a Python script: {Path(__file__).resolve()}")
    
    return logger

logger = setup_logging()

# --- Resource Path Function ---
def get_resource_path(relative_path):
    try:
        base_path = Path(sys._MEIPASS)
        logger.debug(f"Running bundled. _MEIPASS = {base_path}")
    except AttributeError:
        base_path = Path(__file__).resolve().parent
        logger.debug(f"Running as script. Base path for resources = {base_path}")
    
    resource_path = base_path / relative_path
    logger.debug(f"Attempting to resolve resource '{relative_path}' to '{resource_path}'")

    if not resource_path.exists():
        logger.warning(f"Resource NOT FOUND at primary expected path: {resource_path}")
        if getattr(sys, 'frozen', False) and sys.executable:
            try:
                executable_dir = Path(sys.executable).resolve().parent
                alt_path_resources_dir = executable_dir.parent / "Resources"
                alt_resource_path = alt_path_resources_dir / relative_path
                logger.debug(f"Attempting alternative Contents/Resources path: {alt_resource_path}")
                if alt_resource_path.exists():
                    logger.info(f"Found resource at alternative Contents/Resources path: {alt_resource_path}")
                    return alt_resource_path
            except Exception as e_alt:
                logger.error(f"Error constructing or checking alternative resource path: {e_alt}")
    elif getattr(sys, 'frozen', False):
         logger.info(f"Found bundled resource: {resource_path}")
    else:
         logger.info(f"Found script-local resource: {resource_path}")
    return resource_path

# --- Helper for notification icon path ---
_notification_icon_path = None
def get_notification_icon_path():
    global _notification_icon_path
    if _notification_icon_path is None: # Cache it
        resolved_path = get_resource_path(APP_NOTIFICATION_ICON_FILENAME)
        if resolved_path and resolved_path.exists():
            _notification_icon_path = str(resolved_path)
            logger.info(f"Notification icon path set to: {_notification_icon_path}")
        else:
            logger.warning(f"Notification icon '{APP_NOTIFICATION_ICON_FILENAME}' not found at '{resolved_path}'. Notifications may lack an icon.")
            _notification_icon_path = "" # Mark as checked, not found
    return _notification_icon_path if _notification_icon_path else None


# --- Environment and API Key Setup ---
def load_env_and_get_api_key():
    env_path_to_check = None
    expected_env_location_desc = "" 
    
    if getattr(sys, 'frozen', False) and sys.executable:
        try:
            app_executable_path = Path(sys.executable).resolve()
            app_bundle_path = app_executable_path.parent.parent.parent 
            env_dir = app_bundle_path.parent 
            env_path_to_check = env_dir / ".env"
            expected_env_location_desc = f"in the directory '{env_dir.name}' (containing the '{app_bundle_path.name}' application bundle)"
            logger.info(f"Bundled app mode. Expecting .env file at: {env_path_to_check}")
        except Exception as e:
            logger.error(f"Error determining .env path for bundled app: {e}. Will try default load.")
            expected_env_location_desc = "at a standard location for bundled apps (this resolution failed)"
    else: 
        script_dir = Path(__file__).resolve().parent
        env_path_to_check = script_dir / ".env"
        expected_env_location_desc = f"in the script directory '{script_dir.name}'"
        logger.info(f"Script mode. Expecting .env file at: {env_path_to_check}")

    if env_path_to_check and env_path_to_check.exists() and env_path_to_check.is_file():
        logger.info(f"Found .env file at: {env_path_to_check}. Loading...")
        load_dotenv(dotenv_path=env_path_to_check, override=True)
    else:
        logger.warning(f".env file NOT FOUND at primary expected location: {env_path_to_check}. "
                       "Attempting default python-dotenv search strategy (e.g., CWD or script dir).")
        load_dotenv(override=True) 
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        error_message = (f"CRITICAL: GROQ_API_KEY not found in environment.\n\n"
                         f"Please ensure a .env file with the line 'GROQ_API_KEY=YOUR_KEY_HERE' "
                         f"is present {expected_env_location_desc}.\n\n"
                         f"Alternatively, set GROQ_API_KEY as a system environment variable.")
        logger.critical(error_message)
        print(f"FATAL ERROR (PRE-GUI INITIALIZATION): {error_message}") 
        sys.exit(1) 
    
    logger.info("GROQ_API_KEY successfully loaded.")
    return api_key

GROQ_API_KEY = load_env_and_get_api_key() 
groq_client = None
try:
    logger.info("Initializing Groq API client...")
    groq_client = Groq(api_key=GROQ_API_KEY)
    logger.info("Groq API client initialized successfully.")
except Exception as e_groq_init:
    error_msg = f"Failed to initialize Groq API client: {e_groq_init}"
    logger.critical(error_msg, exc_info=True)
    try:
        if rumps._AVAILABLE:
             rumps.alert(title=f"{APP_NAME} - API Client Error", message=error_msg + "\nPlease check your API key and network connection.", ok="Quit")
        else:
            print(f"ALERT (RUMPS NOT FULLY READY FOR GUI ALERT): {APP_NAME} - API Client Error - {error_msg}")
    except Exception as e_alert_groq: 
        logger.error(f"Failed to show rumps alert for Groq client init error: {e_alert_groq}")
        print(f"ALERT (RUMPS ALERT FAILED): {APP_NAME} - API Client Error - {error_msg}")
    sys.exit(1)

# --- Audio Handling Class ---
class AudioHandler:
    def __init__(self, app_ref):
        self.app_ref = app_ref 
        self.logger = logging.getLogger(f"{APP_NAME}.AudioHandler")
        self.audio_interface = None
        self.stream = None
        self.frames = []
        self.is_recording = False
        self.recording_thread = None
        self._initialize_audio_interface()

    def _send_notification(self, title, subtitle, message):
        try:
            self.logger.debug(f"Sending notification: Title='{title}', Subtitle='{subtitle}'")
            rumps.notification(title=title, subtitle=subtitle, message=message, icon=get_notification_icon_path(), sound=True)
        except Exception as e_notify:
            self.logger.error(f"Failed to send rumps notification: {e_notify}", exc_info=True)

    def _initialize_audio_interface(self):
        self.logger.info("Initializing PyAudio interface...")
        try:
            self.audio_interface = pyaudio.PyAudio()
            self.logger.info("PyAudio interface initialized successfully.")
        except Exception as e:
            msg = (f"Failed to initialize PyAudio: {e}\n\n"
                   "This is often due to missing PortAudio. Please ensure it's installed "
                   "(e.g., via Homebrew: 'brew install portaudio').\n\n"
                   "The application cannot record audio and will now exit.")
            self.logger.critical(msg, exc_info=True)
            if hasattr(self.app_ref, 'show_alert_and_quit'):
                self.app_ref.show_alert_and_quit(f"{APP_NAME} - Critical Audio Error", msg)
            else: 
                logger.error("AudioHandler: app_ref not available to show PyAudio critical error alert. Exiting.")
                sys.exit(1)

    def _record_audio_worker(self):
        self.logger.debug("Audio recording worker thread started.")
        try:
            self.stream = self.audio_interface.open(format=FORMAT,
                                                     channels=CHANNELS,
                                                     rate=RATE,
                                                     input=True,
                                                     frames_per_buffer=CHUNK)
            self.frames = [] 
            self.logger.info("Audio stream opened. Recording...")
            
            while self.is_recording:
                try: 
                    data = self.stream.read(CHUNK, exception_on_overflow=False) 
                    self.frames.append(data)
                except IOError as e: 
                    self.logger.warning(f"IOError while reading audio stream: {e}. Stopping recording.")
                    self.is_recording = False 
                    if hasattr(self.app_ref, 'show_alert'): # Notify main app thread if possible
                        rumps.Timer(lambda _: self.app_ref.show_alert(f"{APP_NAME} - Recording Issue", f"Audio input error: {e}. Recording stopped."), 0).start()
                    break 
            self.logger.debug("Recording loop finished.")
        except Exception as e: 
            self.logger.error(f"Unhandled error in audio recording worker: {e}", exc_info=True)
            self.is_recording = False 
            if hasattr(self.app_ref, 'show_alert'):
                rumps.Timer(lambda _: self.app_ref.show_alert(f"{APP_NAME} - Recording Error", f"A critical error occurred during recording: {e}"), 0).start()
        finally:
            if self.stream:
                try: 
                    if self.stream.is_active(): self.stream.stop_stream()
                    self.stream.close()
                    self.logger.debug("Audio stream stopped and closed.")
                except Exception as e_stream_close: 
                    self.logger.error(f"Error stopping/closing audio stream: {e_stream_close}", exc_info=True)
            self.stream = None
            self.logger.info("Audio recording worker thread finished.")

    def _save_audio_to_file(self):
        if not self.frames: 
            self.logger.warning("No audio frames captured. Cannot save audio file.")
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename_obj = None 

        try:
            if getattr(sys, 'frozen', False) and sys.executable: 
                cache_dir_base = Path.home() / "Library" / "Caches" 
                app_cache_dir = cache_dir_base / APP_NAME / "TempRecordings"
            else: 
                app_cache_dir = Path(__file__).resolve().parent / "temp_audio_recordings"
            
            os.makedirs(app_cache_dir, exist_ok=True) 
            output_filename_obj = app_cache_dir / f"{TEMP_FILENAME_BASE}_{timestamp}.wav"
            self.logger.info(f"Preparing to save audio to: {output_filename_obj}")

        except Exception as e_path_create:
            self.logger.error(f"Error creating designated temporary audio path '{app_cache_dir}': {e_path_create}. "
                              f"Falling back to OS temporary directory.", exc_info=True)
            fallback_temp_dir = Path('/tmp') / f"{APP_NAME}_Recordings"
            os.makedirs(fallback_temp_dir, exist_ok=True)
            output_filename_obj = fallback_temp_dir / f"{TEMP_FILENAME_BASE}_{timestamp}.wav"
            self.logger.info(f"Using fallback save path: {output_filename_obj}")

        try:
            wf = wave.open(str(output_filename_obj), 'wb') 
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self.audio_interface.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(self.frames))
            wf.close()
            self.logger.info(f"Audio file successfully saved: {output_filename_obj}")
            return output_filename_obj 
        except Exception as e_wave_save:
            self.logger.error(f"Error saving WAV file to {output_filename_obj}: {e_wave_save}", exc_info=True)
            if hasattr(self.app_ref, 'show_alert'):
                 rumps.Timer(lambda _: self.app_ref.show_alert(f"{APP_NAME} - Save Error", f"Failed to save audio recording: {e_wave_save}"),0).start()
            return None

    def _transcribe_and_notify_worker(self, audio_file_path_obj): 
        if not audio_file_path_obj or not audio_file_path_obj.exists():
            self.logger.error(f"Transcription worker called with invalid or non-existent audio file path: {audio_file_path_obj}")
            rumps.Timer(lambda _: self.app_ref.set_icon_state("idle"), 0).start()
            return

        self.logger.info(f"Transcription worker started for: {audio_file_path_obj.name}")
        rumps.Timer(lambda _: self.app_ref.set_icon_state("processing"), 0).start()
        transcribed_text = "" 

        try:
            with open(audio_file_path_obj, "rb") as audio_file_for_api:
                self.logger.debug(f"Sending '{audio_file_path_obj.name}' to Groq API for transcription...")
                transcription_result = groq_client.audio.transcriptions.create(
                    file=(audio_file_path_obj.name, audio_file_for_api.read()), 
                    model="whisper-large-v3"
                )
            transcribed_text = transcription_result.text
            self.logger.info(f"Transcription successful. Text length: {len(transcribed_text)} characters.")
            
            if not transcribed_text.strip():
                self.logger.warning("Transcription result was empty or only whitespace.")
                self._send_notification(title=APP_NAME, subtitle="Transcription Note", message="The audio resulted in an empty transcription.")
            else:
                try:
                    pyperclip.copy(transcribed_text)
                    self.logger.info("Transcribed text copied to clipboard.")
                    self._send_notification(title=APP_NAME, subtitle="Transcription Complete!", message="Text copied to clipboard.")
                except pyperclip.PyperclipException as e_clip:
                    self.logger.error(f"Pyperclip error copying to clipboard: {e_clip}", exc_info=True)
                    if hasattr(self.app_ref, 'show_alert'):
                        rumps.Timer(lambda _: self.app_ref.show_alert(f"{APP_NAME} - Clipboard Error", 
                                                f"Could not copy text to clipboard: {e_clip}\n\n"
                                                f"Transcription:\n{transcribed_text[:300]}..."), 0).start()
                    self._send_notification(title=APP_NAME, subtitle="Transcription Done (Clipboard Failed)",
                                        message="Text transcribed, but clipboard copy failed. See logs.")

        except Exception as e_transcribe_api:
            self.logger.error(f"Error during Groq API transcription call: {e_transcribe_api}", exc_info=True)
            self._send_notification(title=APP_NAME, subtitle="Transcription Failed",
                                message=f"An error occurred during transcription: {str(e_transcribe_api)[:100]}...")
        finally:
            try:
                if audio_file_path_obj and audio_file_path_obj.exists():
                    os.remove(audio_file_path_obj)
                    self.logger.info(f"Removed temporary audio file: {audio_file_path_obj}")
            except Exception as e_remove_file:
                self.logger.warning(f"Error removing temporary audio file {audio_file_path_obj}: {e_remove_file}")
            
            rumps.Timer(lambda _: self.app_ref.set_icon_state("idle"), 0).start()

    def start_recording(self):
        if self.is_recording:
            self.logger.info("Start recording called, but already recording. Ignoring.")
            return
        
        if not self.audio_interface: 
            self.logger.critical("PyAudio interface not available. Cannot start recording.")
            if hasattr(self.app_ref, 'show_alert'):
                 self.app_ref.show_alert(f"{APP_NAME} - Critical Audio Error", "Audio system not initialized. Please restart the application.")
            return

        self.is_recording = True
        self.frames = [] 
        
        self.recording_thread = threading.Thread(target=self._record_audio_worker, name="AudioRecordThread")
        self.recording_thread.daemon = True 
        self.recording_thread.start()
        
        self.logger.info("Recording initiated and worker thread started.")
        self._send_notification(title=APP_NAME, subtitle="Recording Started", message="Audio recording is now active.")
        self.app_ref.update_menu_and_icon_state()

    def stop_recording_and_process(self):
        if not self.is_recording:
            self.logger.info("Stop recording called, but not currently recording. Ignoring.")
            self.app_ref.update_menu_and_icon_state() 
            return

        self.logger.info("Stopping recording process...")
        self.is_recording = False 

        if self.recording_thread and self.recording_thread.is_alive():
            self.logger.debug("Waiting for recording thread to join (timeout: 5s)...")
            self.recording_thread.join(timeout=5.0) 
            if self.recording_thread.is_alive():
                self.logger.warning("Recording thread did not join within the timeout.")
        self.recording_thread = None 
        self.logger.debug("Recording thread joined or timeout reached.")

        if not self.frames:
            self.logger.warning("Recording stopped, but no audio data was captured. Aborting processing.")
            self._send_notification(title=APP_NAME, subtitle="Recording Stopped", message="No audio was captured.")
            self.app_ref.update_menu_and_icon_state() 
            return

        self.logger.info("Recording stopped successfully. Proceeding to save and transcribe audio.")
        self._send_notification(title=APP_NAME, subtitle="Processing Audio", message="Recording stopped. Now transcribing...")
        self.app_ref.set_icon_state("processing") 

        audio_file_path_obj = self._save_audio_to_file() 

        if audio_file_path_obj:
            self.logger.info(f"Audio saved to {audio_file_path_obj}. Starting transcription thread.")
            trans_thread = threading.Thread(
                target=self._transcribe_and_notify_worker, 
                args=(audio_file_path_obj,), 
                name="AudioTranscribeThread"
            )
            trans_thread.daemon = True
            trans_thread.start()
        else:
            self.logger.error("Failed to save audio file after recording. Transcription cannot proceed.")
            self.app_ref.set_icon_state("idle") 
            if hasattr(self.app_ref, 'show_alert'):
                self.app_ref.show_alert(f"{APP_NAME} - Critical Error", "Failed to save the audio recording. Transcription aborted. Please check logs.")

    def cleanup(self):
        self.logger.info("Cleanup initiated for AudioHandler.")
        if self.is_recording:
            self.logger.warning("Audio recording was active during cleanup. Attempting to stop it.")
            self.is_recording = False 
            if self.recording_thread and self.recording_thread.is_alive():
                self.logger.debug("Waiting for recording thread to join during cleanup (timeout: 2s)...")
                self.recording_thread.join(timeout=2.0) 
                if self.recording_thread.is_alive():
                    self.logger.warning("Recording thread still alive after cleanup join attempt.")
        
        if self.audio_interface:
            try:
                self.audio_interface.terminate()
                self.logger.info("PyAudio interface terminated successfully.")
            except Exception as e_terminate:
                self.logger.error(f"Error during PyAudio termination: {e_terminate}", exc_info=True)
        self.audio_interface = None
        self.logger.info("AudioHandler cleanup finished.")

# --- Rumps Application Class ---
class AudioTranscriberRumpsApp(rumps.App):
    def __init__(self):
        self.logger = logging.getLogger(f"{APP_NAME}.RumpsApp") 
        self.logger.info(f"'{APP_NAME}' RumpsApp initializing...")
        
        self.idle_icon_path_str = str(get_resource_path(ICON_IDLE_FILENAME))
        self.recording_icon_path_str = str(get_resource_path(ICON_RECORDING_FILENAME))
        self.processing_icon_path_str = str(get_resource_path(ICON_PROCESSING_FILENAME))

        self.logger.info(f"Resolved Idle icon path: {self.idle_icon_path_str}")
        self.logger.info(f"Resolved Recording icon path: {self.recording_icon_path_str}")
        self.logger.info(f"Resolved Processing icon path: {self.processing_icon_path_str}")
        get_notification_icon_path() # Resolve and cache notification icon path early

        initial_icon_for_rumps = None
        if Path(self.idle_icon_path_str).exists():
            initial_icon_for_rumps = self.idle_icon_path_str
            self.logger.info(f"Using idle icon for app startup: {initial_icon_for_rumps}")
        else:
            self.logger.error(f"CRITICAL - IDLE ICON '{ICON_IDLE_FILENAME}' MISSING at resolved path: {self.idle_icon_path_str}!")
        
        if not Path(self.recording_icon_path_str).exists():
            self.logger.warning(f"Recording icon '{ICON_RECORDING_FILENAME}' missing.")
        if not Path(self.processing_icon_path_str).exists():
            self.logger.warning(f"Processing icon '{ICON_PROCESSING_FILENAME}' missing.")
        
        try:
            super(AudioTranscriberRumpsApp, self).__init__(
                name=APP_NAME, 
                icon=initial_icon_for_rumps, 
                quit_button="Quit " + APP_NAME 
            )
        except Exception as e_super_init:
            self.logger.critical(f"Failed during rumps.App super().__init__: {e_super_init}", exc_info=True)
            print(f"FATAL ERROR: Failed to initialize rumps.App: {e_super_init}")
            sys.exit(1)
            
        try:
            self.audio_handler = AudioHandler(app_ref=self)
        except SystemExit: 
            self.logger.critical("AudioHandler failed to initialize. Application cannot continue.")
            raise 
        except Exception as e_audio_handler:
            self.logger.critical(f"Unexpected error initializing AudioHandler: {e_audio_handler}", exc_info=True)
            self.show_alert_and_quit("Critical Error", f"Failed to set up audio system: {e_audio_handler}")

        self.toggle_recording_item = rumps.MenuItem("Start Recording", callback=self.toggle_recording_cb)
        self.about_item = rumps.MenuItem(f"About {APP_NAME}", callback=self.show_about_cb)
        self.view_logs_item = rumps.MenuItem("View Logs", callback=self.view_logs_cb)
        
        self.menu = [
            self.toggle_recording_item,
            None, 
            self.view_logs_item,
            self.about_item,
            None, 
        ] 
        self.update_menu_and_icon_state() 
        self.logger.info(f"'{APP_NAME}' RumpsApp initialized successfully.")

    def set_icon_state(self, state_str): 
        self.logger.debug(f"Attempting to set icon state to: '{state_str}'")
        target_icon_path = self.idle_icon_path_str 

        if state_str == "recording":
            if Path(self.recording_icon_path_str).exists():
                target_icon_path = self.recording_icon_path_str
            else:
                self.logger.warning(f"Recording icon missing, using idle for '{state_str}'.")
        elif state_str == "processing":
            if Path(self.processing_icon_path_str).exists():
                target_icon_path = self.processing_icon_path_str
            else:
                self.logger.warning(f"Processing icon missing, using idle for '{state_str}'.")
        
        if Path(target_icon_path).exists():
            try:
                if self.icon != target_icon_path: 
                    self.icon = target_icon_path
                    self.logger.info(f"Menu bar icon set to '{Path(target_icon_path).name}' for state '{state_str}'.")
                else:
                    self.logger.debug(f"Icon already set. No change.")
            except Exception as e_set_icon:
                self.logger.error(f"Error setting icon to '{target_icon_path}': {e_set_icon}", exc_info=True)
        else:
            self.logger.error(f"Target icon for state '{state_str}' NOT FOUND: {target_icon_path}.")
            if self.icon is not None: 
                self.icon = None 
                self.logger.info("Icon set to None (text mode).")

    def update_menu_and_icon_state(self):
        self.logger.debug("Updating menu and icon state...")
        if self.audio_handler.is_recording:
            self.toggle_recording_item.title = "Stop Recording"
            self.set_icon_state("recording")
        else:
            self.toggle_recording_item.title = "Start Recording"
            current_icon_filename = Path(self.icon).name if self.icon and Path(self.icon).exists() else ""
            if ICON_PROCESSING_FILENAME not in current_icon_filename:
                 self.set_icon_state("idle")
            else:
                 self.logger.debug("Icon 'processing', not changing to 'idle'.")
        self.logger.debug("Menu and icon state update complete.")

    def toggle_recording_cb(self, sender):
        self.logger.info(f"Toggle Rec CB. Recording: {self.audio_handler.is_recording}")
        if not self.audio_handler.is_recording:
            self.audio_handler.start_recording()
        else:
            self.audio_handler.stop_recording_and_process()

    def show_about_cb(self, sender):
        self.logger.info("About menu item clicked.")
        about_message = (f"{APP_NAME} - Version {APP_VERSION}\n\n"
                         "Records audio, transcribes via Groq AI, "
                         "and copies text to clipboard.\n\n"
                         "Icons:\n"
                         f"- Idle: {Path(self.idle_icon_path_str).name if Path(self.idle_icon_path_str).exists() else 'Default'}\n"
                         f"- Recording: {Path(self.recording_icon_path_str).name if Path(self.recording_icon_path_str).exists() else 'Default'}\n"
                         f"- Processing: {Path(self.processing_icon_path_str).name if Path(self.processing_icon_path_str).exists() else 'Default'}\n\n"
                         ".env file with GROQ_API_KEY should be placed correctly.\n"
                         "Logs are in 'AudioTranscriptionTool_Logs' folder.")
        rumps.alert(title=f"About {APP_NAME}", message=about_message, ok="OK")
    
    def view_logs_cb(self, sender):
        self.logger.info("View Logs menu item clicked.")
        log_file_path_to_open = None
        if logger and logger.handlers:
            for handler in logger.handlers:
                if isinstance(handler, RotatingFileHandler):
                    log_file_path_to_open = Path(handler.baseFilename).resolve()
                    break
        
        if log_file_path_to_open and log_file_path_to_open.exists():
            self.logger.info(f"Opening log file: {log_file_path_to_open}")
            os.system(f'open "{log_file_path_to_open}"')
        elif log_file_path_to_open:
            self.logger.warning(f"Log file not found: {log_file_path_to_open}")
            self.show_alert("Log File Not Found", f"Log file not found:\n{log_file_path_to_open}")
        else:
            self.logger.warning("Could not determine log file path.")
            self.show_alert("Log File Path Unknown", "Could not determine log file location.")

    def show_alert(self, title, message): 
        self.logger.info(f"Alert: Title='{title}', Msg='{message[:150]}...'")
        rumps.alert(title=title, message=message, ok="OK")

    def show_alert_and_quit(self, title, message): 
        self.logger.critical(f"CRITICAL Alert, app quit: T='{title}', M='{message[:250]}...'")
        try:
            rumps.alert(title=title, message=message, ok="Quit") 
        except Exception as e_alert_quit:
            self.logger.error(f"Failed to show rumps alert for critical error: {e_alert_quit}", exc_info=True)
        finally:
            self.logger.info("Initiating application quit due to critical error.")
            rumps.quit_application() 

    @rumps.clicked("Quit " + APP_NAME) 
    def on_quit_button_clicked(self, sender=None): 
        self.logger.info(f"'{APP_NAME}' Quit button clicked. Cleaning up...")
        if hasattr(self, 'audio_handler') and self.audio_handler:
            self.audio_handler.cleanup()
        else:
            self.logger.warning("Audio_handler not found during quit.")
        self.logger.info("Cleanup finished. App will terminate.")
        rumps.quit_application() 

if __name__ == "__main__":
    logger.info(f"--- Starting {APP_NAME} v{APP_VERSION} ---")
    
    logger.debug(f"Main: Idle icon '{ICON_IDLE_FILENAME}': {get_resource_path(ICON_IDLE_FILENAME)}")
    logger.debug(f"Main: Recording icon '{ICON_RECORDING_FILENAME}': {get_resource_path(ICON_RECORDING_FILENAME)}")
    logger.debug(f"Main: Processing icon '{ICON_PROCESSING_FILENAME}': {get_resource_path(ICON_PROCESSING_FILENAME)}")
    logger.debug(f"Main: Notification icon '{APP_NOTIFICATION_ICON_FILENAME}': {get_notification_icon_path()}")
    
    app_instance = None 
    try:
        logger.info("Main: Creating AudioTranscriberRumpsApp instance...")
        app_instance = AudioTranscriberRumpsApp()
        
        logger.info("Main: Starting RUMPS application event loop...")
        app_instance.run() 
        logger.info("Main: RUMPS application event loop finished normally.")

    except SystemExit as e_sysexit: 
        exit_code_str = f" (Code: {e_sysexit.code})" if hasattr(e_sysexit, 'code') and e_sysexit.code is not None else ""
        logger.critical(f"Main: SystemExit caught{exit_code_str}. Application terminating. Check logs for init errors.")
    except RuntimeError as e_runtime:
        logger.critical(f"Main: RuntimeError during app setup/run: {e_runtime}", exc_info=True)
        if "PyObjC" in str(e_runtime) or "main thread" in str(e_runtime) or "NSApplication" in str(e_runtime):
             err_msg = (f"Critical App Start Error:\n{e_runtime}\n\nOften macOS event loop/PyObjC issue. Cannot continue.")
             try: 
                 if rumps._AVAILABLE: rumps.alert(title="App Start Error", message=err_msg, ok="Quit")
                 else: print(f"CRITICAL ERROR (NO GUI): {err_msg}")
             except: print(f"CRITICAL ERROR (GUI FAILED): {err_msg}") 
        else: 
             try: 
                 if rumps._AVAILABLE: rumps.alert(title="App Runtime Error", message=f"Unexpected runtime error: {e_runtime}", ok="Quit")
                 else: print(f"CRITICAL ERROR (NO GUI): Unexpected runtime error: {e_runtime}")
             except: print(f"CRITICAL ERROR (GUI FAILED): Unexpected runtime error: {e_runtime}")
    except Exception as e_unhandled:
        logger.critical(f"Main: Unhandled critical exception: {e_unhandled}", exc_info=True)
        try: 
            if rumps._AVAILABLE: rumps.alert(title="Critical Unhandled Error", message=f"Critical error, app must close: {e_unhandled}", ok="Quit")
            else: print(f"CRITICAL ERROR (NO GUI): {e_unhandled}")
        except: print(f"CRITICAL ERROR (GUI FAILED): {e_unhandled}")
    finally:
        logger.info(f"--- {APP_NAME} has shut down. ---")