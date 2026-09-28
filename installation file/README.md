# Windows Voice Automation Assistant — Portable Installation Package

This folder contains the complete, standalone installation package for the **Windows Voice Automation & Virtual Assistant**. You can copy/zip this entire folder and move it to any other Windows PC.

---

## 📋 System Requirements (Target PC)
1. **Operating System**: Windows 10 or Windows 11 (64-bit).
2. **Python**: Python 3.10, 3.11, or 3.12 installed.
   * *Important*: When installing Python, ensure the checkbox **"Add Python to PATH"** is checked.
3. **Hardware**: Working Microphone and Audio Output (speakers/headphones).
4. **Internet**: Active internet connection (required for Google Speech Recognition / Gemini AI intent parsing).

---

## 🚀 Setup & Installation (On New PC)

### Step 1: Copy the Folder
Copy or extract this entire `installation file` folder to any location on the target PC (e.g. `C:\Users\<Name>\Desktop\VoiceAssistant`).

### Step 2: Run the 1-Click Installer
* Double-click **`install.bat`**
* The installer will:
  1. Verify your Python installation.
  2. Create a clean isolated virtual environment (`venv`).
  3. Install all required dependencies (`SpeechRecognition`, `pyautogui`, `pyttsx3`, `keyboard`, `pyperclip`, `pyaudio`, `google-generativeai`).
  4. Display a completion confirmation.

### Step 3: Run the Assistant
* Double-click **`start.bat`**
* The assistant will calibrate your microphone for ambient background noise and announce:
  > *"Calibration complete. Sitting in background, listening for commands..."*

---

## 🗣️ Common Voice Commands

| Category | Spoken Command Example |
| :--- | :--- |
| **Apps** | *"open notepad"*, *"open chrome"*, *"open calculator"*, *"open whatsapp"*, *"close chrome"* |
| **Web & Search** | *"search python data types"*, *"open youtube"*, *"open github"* |
| **Music / Media** | *"play shape of you on youtube"*, *"play starboy on spotify"*, *"pause music"*, *"volume up"* |
| **Typing** | *"type hello world"*, *"type and enter my search query"* (gives 2-sec countdown to click text field) |
| **Windows** | *"minimize window"*, *"maximize window"*, *"close tab"*, *"next desktop"*, *"lock screen"* |
| **Vivado Assistant** | *"analyze vivado project"*, *"check vivado errors"*, *"check vivado timing"*, *"optimize active verilog"* |
| **Hardware** | *"check battery status"*, *"check system performance"*, *"brightness up"*, *"take screenshot"* |
| **Clipboard** | *"read clipboard"*, *"write clipboard"*, *"copy text"*, *"clear clipboard"* |

---

## ⌨️ Emergency Failsafe & Global Hotkeys
* **Pause / Resume Listening**: Press `Ctrl + H`
* **Safely Quit Assistant**: Press `Ctrl + Alt + H`
* **PyAutoGUI Emergency Failsafe**: Slam your mouse cursor into any of the 4 screen corners to abort automated movements immediately.

---

## ⚙️ Customization (`commands.json`)
You can open `commands.json` in Notepad to configure:
* **`gemini_api_key`**: Paste your Google Gemini API key here to enable advanced natural language understanding.
* **`wake_word`**: Change the wake word (defaults to `"assistant"`).
* **`wake_word_required`**: Set to `true` or `false`.
* **`custom_commands`**: Add your own custom voice triggers to open websites, execute shell scripts, or speak custom responses.

---

## 🔧 Troubleshooting

1. **"No microphone detected" or "Speech recognition error"**:
   * Open Windows Settings > **Privacy & Security** > **Microphone** and ensure *Microphone access* and *Let apps access your microphone* are enabled.
   * Make sure your default recording device is set correctly in Windows Sound Control Panel.
2. **Keyboard Hotkeys not registering**:
   * If running inside privileged applications (e.g. Task Manager, Admin Command Prompt), right-click `start.bat` and select **"Run as Administrator"**.
3. **PyAudio Compilation Error during install**:
   * The `install.bat` automatically tries fallback methods. If needed, download the pre-compiled `.whl` file for PyAudio matching your Python version from [Unofficial Windows Binaries](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) and run `pip install <filename>.whl`.
