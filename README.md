# Voice Injector

Local voice-to-text that types at your cursor. Powered by Whisper AI running on your GPU.

**Hold a hotkey, speak, release — text appears wherever your cursor is.** Works in any app: browsers, IDEs, terminals, games, chat apps.

## Features

- **Universal injection** — types at your cursor position in any application via Win32 SendInput
- **Local & private** — runs entirely on your PC. No audio leaves your machine
- **GPU-accelerated** — Whisper large-v3-turbo on NVIDIA GPU (~0.3s processing)
- **Korean + English** — auto-detects language, handles mixed Korean/English speech
- **Translate mode** — speak Korean, get English text (via Google Translate)
- **Overlay UI** — floating status bar shows recording/processing state
- **System tray** — runs quietly in the background

## Requirements

- **Windows 10/11**
- **Python 3.10+**
- **NVIDIA GPU** with CUDA support (RTX 20/30/40/50 series)
  - Falls back to CPU with smaller model if no GPU detected
- ~3GB disk space for the Whisper model (downloaded on first run)

## Quick Start

### Option A: From source (developers)

```bash
git clone https://github.com/YOUR_USERNAME/VoiceInjector.git
cd VoiceInjector
pip install -r requirements.txt
python main.py
```

### Option B: Download exe (everyone)

1. Download the latest release from [Releases](https://github.com/YOUR_USERNAME/VoiceInjector/releases)
2. Run `VoiceInjector.exe`
3. Wait for model download on first launch (~3GB)

### First Run

On first launch, the Whisper model will be downloaded automatically (~3GB). This only happens once.

```
python main.py          # Start Voice Injector
python main.py --devices    # List microphone devices
python main.py --test-mic   # Test your microphone
python main.py --test-inject # Test text injection
python main.py -v           # Verbose logging
```

## Hotkeys

| Hotkey | Action |
|---|---|
| `Win+Ctrl` (hold) | **Push-to-talk**: hold, speak, release to inject text |
| `Win+Shift` | Toggle **Translate** mode (Korean → English) |
| `Ctrl+Shift+Q` | Quit |

## Overlay UI

The floating overlay at the bottom of your screen shows:

| State | Indicator |
|---|---|
| Ready | Gray dot, "Ready" |
| Recording | Green pulsing dot, "Recording..." |
| Processing | Orange spinner, "Processing..." |
| Result | Green check, shows injected text for 3 seconds |

The **Translate: ON/OFF** badge shows the current translation mode.

## Configuration

Edit `config.yaml` to customize:

```yaml
stt:
  model_size: large-v3-turbo    # Model: tiny/base/small/medium/large-v3/large-v3-turbo
  device: cuda                   # cuda (GPU) or cpu
  compute_type: float16          # float16 (GPU), int8 (CPU)
  language: null                 # null=auto-detect, ko=Korean, en=English

hotkeys:
  push_to_talk: win+ctrl         # Push-to-talk key combination
  toggle_mode: win+shift         # Toggle translate mode
  quit: ctrl+shift+q             # Quit application

audio:
  device_index: null             # null=default mic, or specific device number
```

Run `python main.py --devices` to see available microphone devices and set `device_index` if needed.

## How It Works

```
Hold Win+Ctrl → Microphone captures audio
                    ↓
Release key   → Whisper large-v3-turbo (GPU, ~0.3s)
                    ↓
              → Text injected at cursor via Win32 SendInput
                    ↓
              → (If Translate ON) Google Translate → English
```

- **Transcribe mode**: Speech → text as spoken (Korean/English auto-detect)
- **Translate mode**: Korean speech → Korean text → Google Translate → English text

## Tech Stack

| Component | Technology |
|---|---|
| STT Engine | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) |
| Model | Whisper large-v3-turbo (OpenAI) |
| Translation | [Google Translate](https://github.com/nidhaloff/deep-translator) (free) |
| Text Injection | Win32 SendInput API (Unicode) |
| Audio Capture | sounddevice (PortAudio) |
| VAD | WebRTC VAD |
| Hotkeys | pynput |
| Overlay | tkinter |
| System Tray | pystray |

## Troubleshooting

### "SendInput returned 0"
Run as administrator, or check if another app is blocking input simulation.

### Model download slow
The ~3GB model downloads from Hugging Face on first run. Use a VPN if blocked in your region.

### Wrong language detected
Set `language: ko` in `config.yaml` to force Korean, or `language: en` for English.

### No GPU detected
The app will fall back to CPU with the `base` model. For GPU, ensure NVIDIA drivers and CUDA are installed.

## License

MIT License — free for personal and commercial use.

## Contributing

Issues and PRs welcome. Please test on your hardware before submitting.
