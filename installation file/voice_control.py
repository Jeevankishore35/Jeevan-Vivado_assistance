import os
import sys
import json
import time
import subprocess
import webbrowser
from datetime import datetime
try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.3
except ImportError:
    pyautogui = None

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    import winsound
except ImportError:
    winsound = None

CONFIG_FILE = "commands.json"
is_active = True  # Global state for voice control listening
tts_engine = None
SPEECH_ENGINE = "google"
whisper_model = None
WAKE_WORD = "assistant"
WAKE_WORD_REQUIRED = True
AUDIO_FEEDBACK = True
GEMINI_API_KEY = ""

def init_tts():
    """Initializes the Text-to-Speech engine and selects a female voice if available."""
    global tts_engine
    if pyttsx3 is None:
        tts_engine = None
        return
    try:
        tts_engine = pyttsx3.init()
        tts_engine.setProperty("rate", 175)  # Slightly slower for clearer pronunciation
        tts_engine.setProperty("volume", 0.9)
        
        # Try to find and set a female voice (e.g. Zira or Hazel on Windows)
        voices = tts_engine.getProperty("voices")
        for voice in voices:
            if "zira" in voice.name.lower() or "female" in voice.name.lower() or "hazel" in voice.name.lower() or "zira" in voice.id.lower():
                tts_engine.setProperty("voice", voice.id)
                break
    except Exception as e:
        print(f"[-] TTS Initialization failed: {e}")

def speak(text):
    """Speaks the given text out loud and prints to the console."""
    print(f"\n[Assistant]: {text}")
    if tts_engine:
        try:
            tts_engine.say(text)
            tts_engine.runAndWait()
        except Exception as e:
            print(f"[-] Speaking failed: {e}")

def load_settings():
    """Loads configuration settings from commands.json."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            return data.get("settings", {})
    except Exception as e:
        print(f"[-] Failed to load settings from {CONFIG_FILE}: {e}")
        return {}

def play_chime(chime_type):
    """Plays distinct system chimes using winsound for audio feedback."""
    if not AUDIO_FEEDBACK or winsound is None:
        return
    try:
        if chime_type == "start":
            winsound.Beep(600, 100)
            winsound.Beep(800, 100)
            winsound.Beep(1000, 150)
        elif chime_type == "success":
            winsound.Beep(880, 80)
            winsound.Beep(1200, 150)
        elif chime_type == "error" or chime_type == "cancel":
            winsound.Beep(400, 120)
            winsound.Beep(300, 200)
        elif chime_type == "calibrate":
            winsound.Beep(440, 150)
            winsound.Beep(440, 150)
    except Exception as e:
        print(f"[-] Failed to play chime: {e}")

def init_whisper():
    """Initializes the Whisper model if SPEECH_ENGINE is set to whisperflow."""
    global whisper_model, SPEECH_ENGINE, WAKE_WORD, WAKE_WORD_REQUIRED, AUDIO_FEEDBACK, GEMINI_API_KEY
    settings = load_settings()
    SPEECH_ENGINE = settings.get("speech_engine", "google").lower()
    WAKE_WORD = settings.get("wake_word", "assistant").lower().strip()
    WAKE_WORD_REQUIRED = settings.get("wake_word_required", True)
    AUDIO_FEEDBACK = settings.get("audio_feedback", True)
    GEMINI_API_KEY = settings.get("gemini_api_key", os.environ.get("GEMINI_API_KEY", ""))
    
    # Configure Gemini if API key is provided
    if GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            print("[System]: Gemini API configured for natural language command parsing.")
        except Exception as e:
            print(f"[-] Failed to configure Gemini API: {e}")
    
    if SPEECH_ENGINE == "whisperflow":
        try:
            import whisperflow.transcriber as ts
            import torch
            model_name = settings.get("whisper_model", "tiny.en")
            if not model_name.endswith(".pt"):
                model_name = f"{model_name}.pt"
            
            speak(f"Loading Whisper model ({model_name}). This might take a few seconds...")
            whisper_model = ts.get_model(model_name)
            
            # Detect GPU/CUDA
            device = "cuda" if torch.cuda.is_available() else "cpu"
            whisper_model = whisper_model.to(device)
            print(f"[System]: Whisper model loaded on {device.upper()}.")
            speak("Whisper model loaded successfully.")
        except ModuleNotFoundError:
            speak("whisperflow library is not installed. Falling back to Google Speech Recognition.")
            print("[-] Module 'whisperflow' not found. Please install it using 'pip install whisperflow'.")
            SPEECH_ENGINE = "google"
        except Exception as e:
            speak("Failed to load Whisper model. Falling back to Google.")
            print(f"[-] Whisper initialization failed: {e}")
            SPEECH_ENGINE = "google"

def parse_intent_with_gemini(text):
    """Uses Gemini API to translate natural language voice commands to exact system commands."""
    if not GEMINI_API_KEY:
        return text
    try:
        import google.generativeai as genai
        custom_cmds = load_custom_commands()
        custom_phrases = [cmd.get("phrase", "") for cmd in custom_cmds if cmd.get("phrase")]
        
        prompt = f"""You are a voice command parser for a Windows voice automation script.
The user spoke a natural language command: "{text}"

Translate it into one of these exact system command formats if it matches the intent:
- open [app_name] (e.g. open notepad, open calculator, open whatsapp)
- search [query] (e.g. search python variables)
- play [song_name] on youtube (e.g. play shape of you on youtube)
- play [song_name] on spotify (e.g. play perfect on spotify)
- play music / pause music / stop music
- type [text] (e.g. type hello world)
- type and enter [text]
- press [key] (valid keys: enter, space, escape, backspace, tab, up, down, left, right)
- scroll down / scroll up
- volume up / volume down / mute
- close window / close tab
- close [app_name] (e.g. close chrome, close whatsapp)
- minimize window / maximize window
- lock screen / take screenshot
- what time is it
- stop listening
- read clipboard / write clipboard / clear clipboard / copy text
- select all / undo that / redo that / delete line / delete word
- next desktop / previous desktop / new desktop / close desktop
- next tab / previous tab / reopen tab / go back / go forward
- check battery status / check system performance / brightness up / brightness down
- open downloads folder / open documents folder
- analyze vivado project / check vivado project
- check vivado errors / why did vivado fail
- check vivado timing / check timing slack
- optimize active verilog / optimize verilog design

Also, if the intent matches one of these custom user phrases, output that exact custom phrase:
{custom_phrases}

Output ONLY the translated command string. Do not add quotes, markdown formatting, explanation, or extra words. If the intent does not match any of these system or custom commands, output the user's spoken text exactly as they said it.
"""
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        translated_text = response.text.strip().lower()
        print(f"[Gemini Intent Parser]: '{text}' -> '{translated_text}'")
        return translated_text
    except Exception as e:
        print(f"[-] Gemini intent parsing failed: {e}")
        return text

def load_custom_commands():
    """Loads custom commands from commands.json."""
    if not os.path.exists(CONFIG_FILE):
        return []
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            return data.get("custom_commands", [])
    except Exception as e:
        print(f"[-] Failed to load {CONFIG_FILE}: {e}")
        return []

def execute_custom_command(text):
    """Checks and executes custom commands from commands.json. Returns True if handled."""
    custom_cmds = load_custom_commands()
    text_lower = text.lower().strip()
    
    for cmd in custom_cmds:
        phrase = cmd.get("phrase", "").lower().strip()
        if phrase and (phrase in text_lower or text_lower in phrase):
            action = cmd.get("action", "")
            target = cmd.get("target", "")
            
            if action == "url":
                speak(f"Opening website: {target}")
                webbrowser.open(target)
                return True
            elif action == "command":
                speak(f"Running system command: {target}")
                subprocess.Popen(target, shell=True)
                return True
            elif action == "speak":
                speak(target)
                return True
    return False

def scan_installed_apps():
    """Scans Windows Start Menu directories for installed app shortcuts (.lnk files)."""
    apps = {}
    paths = []
    
    # 1. User-specific Start Menu Programs
    appdata_path = os.environ.get('APPDATA')
    if appdata_path:
        paths.append(os.path.join(appdata_path, 'Microsoft', 'Windows', 'Start Menu', 'Programs'))
        
    # 2. System-wide Start Menu Programs
    paths.append(r'C:\ProgramData\Microsoft\Windows\Start Menu\Programs')
    
    # 3. Desktop shortcuts
    userprofile = os.environ.get('USERPROFILE')
    if userprofile:
        paths.append(os.path.join(userprofile, 'Desktop'))
        paths.append(r'C:\Users\Public\Desktop')

    for base_dir in paths:
        if not os.path.exists(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                if file.endswith('.lnk'):
                    name = os.path.splitext(file)[0].lower().strip()
                    # Filter out helper uninstallers or readme shortcuts
                    if "uninstall" in name or "read me" in name or "readme" in name:
                        continue
                    full_path = os.path.join(root, file)
                    if name not in apps:
                        apps[name] = full_path
    return apps

def launch_app_by_name(query):
    """Searches and launches an installed app by name."""
    query = query.lower().strip()
    apps = scan_installed_apps()
    
    # Try exact match first
    if query in apps:
        try:
            os.startfile(apps[query])
            speak(f"Launching {query}.")
            return True
        except Exception as e:
            print(f"Error launching {query}: {e}")
            
    # Try substring match (e.g. user says "chrome" matches "google chrome")
    for app_name, app_path in apps.items():
        if query in app_name or app_name in query:
            try:
                os.startfile(app_path)
                speak(f"Launching {app_name}.")
                return True
            except Exception as e:
                print(f"Error launching {app_name}: {e}")
                
    # Fallback to system start command
    try:
        subprocess.Popen(f"start {query}", shell=True)
        speak(f"Attempting to launch {query} using system shell.")
        return True
    except Exception:
        pass
        
    return False

def exit_assistant():
    """Safely exits the background script from the global hotkey."""
    print("\n" + "="*50)
    print("[System]: Exit shortcut detected. Stopping voice control...")
    print("="*50)
    speak("Goodbye! Stopping voice control system.")
    os._exit(0)

def toggle_listening():
    """Toggles the active state of the speech listening loop."""
    global is_active
    is_active = not is_active
    if is_active:
        print("\n" + "="*50)
        print("[System]: Voice control activated. Listening...")
        print("="*50)
        speak("Voice control activated.")
    else:
        print("\n" + "="*50)
        print("[System]: Voice control paused. Press Ctrl+H to resume.")
        print("="*50)
        speak("Voice control paused.")

def play_on_youtube(song_name):
    """Searches YouTube for the song name and opens the top video directly."""
    speak(f"Playing {song_name} on YouTube.")
    try:
        import urllib.request
        import re
        import urllib.parse
        
        query = urllib.parse.quote(song_name)
        url = f"https://www.youtube.com/results?search_query={query}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            html = response.read().decode()
            video_ids = re.findall(r"watch\?v=(\S{11})", html)
            if video_ids:
                video_url = f"https://www.youtube.com/watch?v={video_ids[0]}"
                webbrowser.open(video_url)
            else:
                webbrowser.open(url)
    except Exception as e:
        import urllib.parse
        print(f"Error finding YouTube video: {e}")
        webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(song_name)}")

def close_app_by_name(query):
    """Closes a running application by name using taskkill."""
    query = query.lower().strip()
    
    # Process name mappings for common apps
    process_mappings = {
        "whatsapp": "WhatsApp.exe",
        "spotify": "Spotify.exe",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "browser": "chrome.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "calculator": "CalculatorApp.exe",
        "calc": "CalculatorApp.exe",
        "notepad": "notepad.exe",
        "command prompt": "cmd.exe",
        "cmd": "cmd.exe",
        "discord": "Discord.exe",
        "steam": "steam.exe",
        "vlc": "vlc.exe"
    }
    
    process_name = process_mappings.get(query, f"{query}.exe")
    
    speak(f"Closing {query}.")
    try:
        # Silently terminate the process and all its child tasks (/t)
        subprocess.run(
            f"taskkill /f /t /im {process_name}", 
            shell=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        # Also try lowercase just in case
        subprocess.run(
            f"taskkill /f /t /im {process_name.lower()}", 
            shell=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        return True
    except Exception as e:
        print(f"Error closing {query}: {e}")
        return False

def process_command(text):
    """Parses and executes the spoken voice command."""
    text_lower = text.lower().strip()
    print(f"\n[Command Parsed]: '{text_lower}'")
    
    recognized = True

    # 1. First check if it matches a custom command from commands.json
    if execute_custom_command(text_lower):
        play_chime("success")
        return

    # 2. Check built-in commands and dynamic app launching
    
    # --- Dynamic App Launch & Browsing Commands ---
    if text_lower.startswith("open "):
        app_name = text_lower[5:].strip()
        
        if app_name == "browser" or app_name == "google":
            speak("Opening default web browser.")
            webbrowser.open("https://www.google.com")
        elif app_name == "youtube":
            speak("Opening YouTube.")
            webbrowser.open("https://www.youtube.com")
        elif app_name == "notepad":
            speak("Opening Notepad.")
            subprocess.Popen("notepad.exe")
        elif app_name == "calculator" or app_name == "calc":
            speak("Opening Calculator.")
            subprocess.Popen("calc.exe")
        elif app_name == "command prompt" or app_name == "cmd":
            speak("Opening Command Prompt.")
            subprocess.Popen("cmd.exe")
        elif app_name == "whatsapp":
            speak("Opening WhatsApp.")
            # First try opening the local WhatsApp application
            success = launch_app_by_name("whatsapp")
            if not success:
                speak("Desktop app not found. Opening WhatsApp Web in browser.")
                webbrowser.open("https://web.whatsapp.com")
        else:
            # Dynamically launch any other app
            success = launch_app_by_name(app_name)
            if not success:
                speak(f"I couldn't find an application named {app_name} on your laptop.")

    elif text_lower.startswith("search "):
        query = text_lower[7:].strip()
        if query:
            speak(f"Searching Google for {query}")
            webbrowser.open(f"https://www.google.com/search?q={query}")
        else:
            speak("What would you like me to search for?")

    # --- Music & Play Commands ---
    elif text_lower.startswith("open youtube and play "):
        song_name = text_lower[22:].strip()
        if song_name:
            play_on_youtube(song_name)
        else:
            speak("What song would you like me to play on YouTube?")

    elif text_lower.startswith("play ") and "on spotify" in text_lower:
        song_name = text_lower[5:].replace("on spotify", "").strip()
        if song_name:
            speak(f"Playing {song_name} on Spotify.")
            webbrowser.open(f"https://open.spotify.com/search/{song_name}")
            # Give the browser page time to load, then press enter to play the first result
            time.sleep(5)
            pyautogui.press("enter")
        else:
            speak("What song would you like to play on Spotify?")

    elif text_lower.startswith("play ") and "on youtube" in text_lower:
        song_name = text_lower[5:].replace("on youtube", "").strip()
        if song_name:
            play_on_youtube(song_name)
        else:
            speak("What song would you like me to play on YouTube?")

    elif text_lower.startswith("play "):
        song_name = text_lower[5:].strip()
        if song_name:
            play_on_youtube(song_name)
        else:
            speak("What would you like me to play?")

    elif text_lower == "play" or text_lower == "play music":
        speak("Resuming playback.")
        pyautogui.press("playpause")

    elif text_lower == "pause" or text_lower == "pause music":
        speak("Pausing playback.")
        pyautogui.press("playpause")

    elif text_lower == "stop" or text_lower == "stop music":
        speak("Stopping playback.")
        pyautogui.press("stop")

    # --- Keyboard & Typing Simulation ---
    elif text_lower.startswith("type and enter ") or text_lower.startswith("write and enter "):
        prefix_len = 15 if text_lower.startswith("type and enter ") else 16
        content_to_type = text[prefix_len:].strip()
        if content_to_type:
            speak("Please click inside the text box now.")
            print("[System]: Click your target input field now! Typing in 2 seconds...")
            time.sleep(2.0)
            keyboard.write(content_to_type)
            pyautogui.press("enter")
        else:
            speak("What would you like me to type?")

    elif text_lower.startswith("type ") or text_lower.startswith("write ") or text_lower.startswith("enter "):
        if text_lower.startswith("type "):
            prefix_len = 5
        elif text_lower.startswith("write "):
            prefix_len = 6
        else:
            prefix_len = 6
            
        content_to_type = text[prefix_len:].strip()
        if content_to_type:
            speak("Please click inside the text box now.")
            print("[System]: Click your target input field now! Typing in 2 seconds...")
            time.sleep(2.0)
            keyboard.write(content_to_type)
        else:
            speak("What would you like me to type?")

    elif text_lower.startswith("press "):
        key = text_lower[6:].strip()
        valid_keys = pyautogui.KEYBOARD_KEYS
        if key in valid_keys:
            speak(f"Pressing {key}")
            pyautogui.press(key)
        elif key == "enter":
            speak("Pressing enter")
            pyautogui.press("enter")
        elif key == "space":
            speak("Pressing space")
            pyautogui.press("space")
        else:
            speak(f"I don't recognize the key: {key}")

    # --- Mouse & Scrolling ---
    elif "scroll down" in text_lower:
        speak("Scrolling down.")
        pyautogui.scroll(-400)

    elif "scroll up" in text_lower:
        speak("Scrolling up.")
        pyautogui.scroll(400)

    # --- Media / Volume Controls ---
    elif "volume up" in text_lower:
        speak("Increasing volume.")
        for _ in range(5):
            pyautogui.press("volumeup")

    elif "volume down" in text_lower:
        speak("Decreasing volume.")
        for _ in range(5):
            pyautogui.press("volumedown")

    elif "mute" in text_lower:
        speak("Toggling mute.")
        pyautogui.press("volumemute")

    # --- Window & App Closing ---
    elif text_lower == "close" or "close window" in text_lower:
        speak("Closing the active window.")
        pyautogui.hotkey("alt", "f4")

    elif "close tab" in text_lower:
        speak("Closing active tab.")
        pyautogui.hotkey("ctrl", "w")

    elif text_lower.startswith("close "):
        target = text_lower[6:].strip()
        close_app_by_name(target)

    elif text_lower == "minimize" or "minimize window" in text_lower:
        speak("Minimizing window.")
        # Super reliable Windows minimize shortcut: Alt + Space, then N
        pyautogui.hotkey("alt", "space")
        time.sleep(0.15)
        pyautogui.press("n")

    elif "maximize window" in text_lower or "maximize" in text_lower:
        speak("Maximizing window.")
        pyautogui.hotkey("win", "up")

    # --- System Controls ---
    elif "lock screen" in text_lower or "lock laptop" in text_lower or "lock computer" in text_lower:
        speak("Locking screen.")
        subprocess.run("rundll32.exe user32.dll,LockWorkStation")

    elif "take screenshot" in text_lower or "screenshot" in text_lower:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"screenshot_{timestamp}.png"
        speak("Taking screenshot.")
        pyautogui.screenshot(filename)
        print(f"[System] Screenshot saved as {filename}")

    elif "what time is it" in text_lower or "what is the time" in text_lower:
        current_time = datetime.now().strftime("%I:%M %p")
        speak(f"It is currently {current_time}.")

    # --- Clipboard Commands ---
    elif text_lower == "read clipboard":
        try:
            import pyperclip
            content = pyperclip.paste()
            if content.strip():
                speak(f"Your clipboard contains: {content}")
            else:
                speak("Your clipboard is empty.")
        except Exception as e:
            print(f"Error reading clipboard: {e}")
            speak("Failed to read clipboard.")

    elif text_lower == "write clipboard" or text_lower == "paste clipboard":
        pyautogui.hotkey("ctrl", "v")

    elif text_lower == "copy text" or text_lower == "copy selected":
        pyautogui.hotkey("ctrl", "c")

    elif text_lower == "clear clipboard":
        try:
            import pyperclip
            pyperclip.copy("")
            speak("Clipboard cleared.")
        except Exception as e:
            print(f"Error clearing clipboard: {e}")
            speak("Failed to clear clipboard.")

    # --- Text Editing & Navigation ---
    elif text_lower == "select all":
        pyautogui.hotkey("ctrl", "a")

    elif text_lower == "undo that" or text_lower == "undo":
        pyautogui.hotkey("ctrl", "z")

    elif text_lower == "redo that" or text_lower == "redo":
        pyautogui.hotkey("ctrl", "y")

    elif text_lower == "delete line":
        pyautogui.hotkey("shift", "home")
        time.sleep(0.05)
        pyautogui.press("backspace")

    elif text_lower == "delete word":
        pyautogui.hotkey("ctrl", "backspace")

    # --- Virtual Desktop Management ---
    elif text_lower == "next desktop" or text_lower == "next workspace":
        pyautogui.hotkey("ctrl", "win", "right")

    elif text_lower == "previous desktop" or text_lower == "previous workspace":
        pyautogui.hotkey("ctrl", "win", "left")

    elif text_lower == "new desktop" or text_lower == "new workspace":
        pyautogui.hotkey("ctrl", "win", "d")

    elif text_lower == "close desktop" or text_lower == "close workspace":
        pyautogui.hotkey("ctrl", "win", "f4")

    # --- Browser Tab Control ---
    elif text_lower == "next tab" or text_lower == "switch tab":
        pyautogui.hotkey("ctrl", "tab")

    elif text_lower == "previous tab":
        pyautogui.hotkey("ctrl", "shift", "tab")

    elif text_lower == "reopen tab":
        pyautogui.hotkey("ctrl", "shift", "t")

    elif text_lower == "go back" or text_lower == "page back":
        pyautogui.hotkey("alt", "left")

    elif text_lower == "go forward" or text_lower == "page forward":
        pyautogui.hotkey("alt", "right")

    # --- System Info & Hardware controls ---
    elif text_lower == "check battery status" or text_lower == "how is my battery":
        try:
            res = subprocess.check_output(
                'powershell -Command "(Get-CimInstance -ClassName Win32_Battery).EstimatedChargeRemaining"',
                shell=True, text=True
            ).strip()
            if res:
                charging_status = subprocess.check_output(
                    'powershell -Command "(Get-CimInstance -ClassName Win32_Battery).BatteryStatus"',
                    shell=True, text=True
                ).strip()
                status_str = "charging" if charging_status == "2" else "discharging"
                speak(f"Your battery is at {res} percent and is currently {status_str}.")
            else:
                speak("Could not read battery information. Are you on a desktop PC?")
        except Exception as e:
            print(f"Error checking battery: {e}")
            speak("Failed to read battery statistics.")

    elif text_lower == "check system performance" or text_lower == "cpu usage":
        try:
            cpu = subprocess.check_output(
                'powershell -Command "(Get-CimInstance Win32_Processor).LoadPercentage"',
                shell=True, text=True
            ).strip()
            mem = subprocess.check_output(
                'powershell -Command "$m = Get-CimInstance Win32_OperatingSystem; [math]::Round((($m.TotalVisibleMemorySize - $m.FreePhysicalMemory) / $m.TotalVisibleMemorySize) * 100)"',
                shell=True, text=True
            ).strip()
            speak(f"Current CPU usage is {cpu} percent, and RAM usage is {mem} percent.")
        except Exception as e:
            print(f"Error checking system performance: {e}")
            speak("Failed to read performance statistics.")

    elif text_lower == "brightness up":
        speak("Increasing brightness.")
        subprocess.run('powershell -Command "$b = (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness; $new = [math]::min(100, $b + 15); (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(0, $new)"', shell=True)

    elif text_lower == "brightness down":
        speak("Decreasing brightness.")
        subprocess.run('powershell -Command "$b = (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness; $new = [math]::max(0, $b - 15); (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(0, $new)"', shell=True)

    # --- File Explorer Navigation ---
    elif text_lower == "open downloads folder" or text_lower == "downloads":
        speak("Opening Downloads folder.")
        os.startfile(os.path.expanduser('~/Downloads'))

    elif text_lower == "open documents folder" or text_lower == "documents":
        speak("Opening Documents folder.")
        os.startfile(os.path.expanduser('~/Documents'))

    # --- Vivado Assistant Commands ---
    elif "analyze vivado" in text_lower or "check vivado project" in text_lower:
        speak("Scanning your Vivado project files for optimization opportunities...")
        try:
            vivado_dir = r"c:\Users\Jeevan\Downloads\vivado"
            if vivado_dir not in sys.path:
                sys.path.insert(0, vivado_dir)
            from symrtlo.assistant import VivadoProjectAdvisor
            advisor = VivadoProjectAdvisor(vivado_dir)
            report = advisor.analyze_and_optimize_all(goal="area", apply_fixes=True)
            total_files = report["total_files"]
            rules_cnt = report["total_rules_suggested"]
            speak(f"Scan complete. Found {total_files} Verilog modules with {rules_cnt} suggested optimizations.")
        except Exception as e:
            print(f"Vivado project analysis error: {e}")
            speak("Failed to analyze Vivado project.")

    elif "check vivado errors" in text_lower or "why did vivado fail" in text_lower:
        speak("Analyzing Vivado synthesis logs for errors and critical warnings...")
        try:
            vivado_dir = r"c:\Users\Jeevan\Downloads\vivado"
            if vivado_dir not in sys.path:
                sys.path.insert(0, vivado_dir)
            from symrtlo.assistant import VivadoProjectScanner, VivadoLogDiagnoser
            scanner = VivadoProjectScanner(vivado_dir)
            runs = scanner.find_latest_vivado_runs()
            log_file = runs.get("synth_log") or runs.get("root_log")
            if log_file and os.path.exists(log_file):
                diag = VivadoLogDiagnoser(log_file).diagnose()
                if diag["is_successful"]:
                    speak("No critical errors found in your Vivado synthesis log.")
                else:
                    first_err = diag["diagnoses"][0] if diag["diagnoses"] else None
                    if first_err:
                        speak(f"Found {diag['total_errors']} errors. Primary issue is {first_err['category']}. {first_err['fix_advice']}")
                    else:
                        speak(f"Found {diag['total_errors']} errors in Vivado log.")
            else:
                speak("No active Vivado log file found in the project directory.")
        except Exception as e:
            print(f"Vivado log diagnosis error: {e}")
            speak("Could not diagnose Vivado log.")

    elif "check vivado timing" in text_lower or "timing slack" in text_lower or "check timing" in text_lower:
        speak("Checking Vivado static timing slack...")
        try:
            vivado_dir = r"c:\Users\Jeevan\Downloads\vivado"
            if vivado_dir not in sys.path:
                sys.path.insert(0, vivado_dir)
            from symrtlo.assistant import VivadoProjectScanner, TimingSlackAnalyzer
            scanner = VivadoProjectScanner(vivado_dir)
            runs = scanner.find_latest_vivado_runs()
            timing_file = runs.get("synth_timing_rpt") or runs.get("impl_timing_rpt")
            if timing_file and os.path.exists(timing_file):
                timing_res = TimingSlackAnalyzer(timing_file).analyze()
                if timing_res["timing_met"]:
                    speak(f"Timing constraints are met. Worst negative slack is positive at {timing_res['wns']} nanoseconds.")
                else:
                    speak(f"Timing violation detected! Worst negative slack is {timing_res['wns']} nanoseconds with {timing_res['failing_endpoints']} failing endpoints.")
            else:
                speak("No Vivado timing report found. Please run synthesis or implementation first.")
        except Exception as e:
            print(f"Vivado timing error: {e}")
            speak("Failed to read Vivado timing report.")

    elif "optimize active verilog" in text_lower or "optimize verilog" in text_lower:
        speak("Optimizing Verilog designs for area and power...")
        try:
            vivado_dir = r"c:\Users\Jeevan\Downloads\vivado"
            if vivado_dir not in sys.path:
                sys.path.insert(0, vivado_dir)
            from symrtlo.assistant import VivadoProjectAdvisor
            advisor = VivadoProjectAdvisor(os.path.join(vivado_dir, "examples"))
            res = advisor.analyze_and_optimize_all(goal="area", apply_fixes=True)
            speak("Optimization complete. Optimized Verilog files have been generated with formal equivalence verification.")
        except Exception as e:
            print(f"Optimization error: {e}")
            speak("Failed to optimize Verilog designs.")

    # --- Script Exit ---
    elif "stop listening" in text_lower or "exit assistant" in text_lower:
        speak("Goodbye! Stopping voice control system.")
        sys.exit(0)

    else:
        print(f"[System]: Command '{text_lower}' not recognized.")
        recognized = False
        play_chime("error")
        
    if recognized:
        play_chime("success")

def run_text_console():
    print("\n" + "=" * 60)
    print("      WINDOWS AUTOMATION SYSTEM (TEXT PROMPT MODE)     ")
    print("=" * 60)
    print("Type any command (e.g. 'open notepad', 'search python', 'analyze vivado', 'exit'):\n")
    while True:
        try:
            cmd = input("Assistant >>> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        if not cmd:
            continue
        if cmd.lower() in ("exit", "quit", "stop listening"):
            print("Stopping assistant. Goodbye!")
            break
        process_command(cmd)

def main():
    global is_active
    
    # Check for explicit text-only flag
    if "--text" in sys.argv or "-t" in sys.argv:
        init_tts()
        run_text_console()
        return

    # Initialize speech components
    init_tts()
    init_whisper()
    
    if sr is None:
        print("\n[Info]: Speech recognition not installed. Running in Text Prompt Mode...")
        run_text_console()
        return

    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.dynamic_energy_adjustment_damping = 0.15
    recognizer.dynamic_energy_ratio = 1.5
    recognizer.pause_threshold = 1.2  # Allow longer pauses while speaking commands

    try:
        mic = sr.Microphone()
    except Exception as e:
        print(f"\n[Info]: No microphone detected ({e}). Switching to Text Prompt Mode...")
        run_text_console()
        return

    # Setup global keyboard hotkeys if available
    if keyboard is not None:
        try:
            keyboard.add_hotkey("ctrl+h", toggle_listening)
            keyboard.add_hotkey("ctrl+alt+h", exit_assistant)
        except Exception:
            pass

    print("=" * 60)
    print("      WINDOWS VOICE AUTOMATION SYSTEM (BACKGROUND RUNNER)      ")
    print("=" * 60)
    print("Toggle Hotkeys: Press Ctrl+H to pause/resume. Press Ctrl+Alt+H to exit.")
    print("Failsafe: Move mouse cursor to any corner of screen to stop.")
    print("\nSome voice commands you can try:")
    print("  - 'open browser' or 'open youtube'")
    print("  - 'search [something]' (e.g., 'search python tutorial')")
    print("  - 'open notepad' / 'open calculator'")
    print("  - 'type [text]' (e.g., 'type hello world')")
    print("  - 'volume up' / 'volume down' / 'mute'")
    print("  - 'close window' / 'lock screen'")
    print("  - 'stop listening'")
    print("=" * 60)
    
    speak("Voice control engine activated. Calibrating microphone for background noise...")
    play_chime("calibrate")
    with mic as source:
        # Calibrate for longer (2.5 seconds) to filter ambient noise much more effectively
        recognizer.adjust_for_ambient_noise(source, duration=2.5)
    
    play_chime("success")
    speak("Calibration complete. Siting in background, listening for commands...")
    print("\n[Status: LISTENING] - Press Ctrl+H to pause.")

    while True:
        try:
            # If paused, sleep a bit and check again
            if not is_active:
                time.sleep(0.1)
                continue
            
            with mic as source:
                # Use a small timeout so we don't block indefinitely 
                # and can check if is_active has been toggled to False
                audio = recognizer.listen(source, timeout=1.5, phrase_time_limit=6)
                
            # If the user toggled it off while it was capturing audio, discard it
            if not is_active:
                continue
                
            print("\n[Processing speech...]")
            if SPEECH_ENGINE == "whisperflow" and whisper_model is not None:
                import whisperflow.transcriber as ts
                raw_pcm = audio.get_raw_data(convert_rate=16000, convert_width=2)
                result = ts.transcribe_pcm_chunks(whisper_model, [raw_pcm])
                text = result.get("text", "")
            else:
                # Utilize regional language parameter to maximize Indian accent recognition accuracy
                text = recognizer.recognize_google(audio, language="en-IN")
            
            text_cleaned = text.strip().lower()
            if not text_cleaned:
                continue
                
            print(f"[Heard]: '{text}'")
            
            # Wake word filtering
            if WAKE_WORD_REQUIRED:
                if WAKE_WORD in text_cleaned:
                    idx = text_cleaned.find(WAKE_WORD)
                    text_cleaned = text_cleaned[idx + len(WAKE_WORD):].strip()
                    play_chime("start")
                else:
                    # Ignore since wake word was not heard
                    continue
            else:
                play_chime("start")
                    
            if not text_cleaned:
                speak("Yes? How can I help you?")
                continue
                
            if GEMINI_API_KEY:
                text_cleaned = parse_intent_with_gemini(text_cleaned)
                
            process_command(text_cleaned)
            
        except sr.WaitTimeoutError:
            # Normal timeout because no speech was detected, loop back and keep checking
            pass
        except sr.UnknownValueError:
            # Audio was detected but couldn't be recognized as speech (e.g., breathing, keyboard clicks)
            pass
        except sr.RequestError as e:
            speak("Speech translation connection issue. Please check your internet.")
            print(f"Request error: {e}")
            time.sleep(2)
        except KeyboardInterrupt:
            speak("Stopping voice control.")
            break
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
