"""
Build script for creating Voice Injector exe using PyInstaller.

Usage:
    pip install pyinstaller
    python build.py
"""

import os
import subprocess
import sys


def build():
    print("=" * 55)
    print("  Building Voice Injector exe")
    print("=" * 55)

    # Check PyInstaller
    try:
        import PyInstaller

        print(f"  PyInstaller: {PyInstaller.__version__}")
    except ImportError:
        print("  Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Build command
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=VoiceInjector",
        "--onedir",  # Create a directory with all files (faster startup than --onefile)
        "--windowed",  # No console window (runs in tray)
        "--icon=NONE",  # TODO: Add icon
        "--noconfirm",  # Overwrite previous build
        # Hidden imports that PyInstaller might miss
        "--hidden-import=sounddevice",
        "--hidden-import=webrtcvad",
        "--hidden-import=faster_whisper",
        "--hidden-import=ctranslate2",
        "--hidden-import=pynput",
        "--hidden-import=pynput.keyboard",
        "--hidden-import=pynput.keyboard._win32",
        "--hidden-import=pystray",
        "--hidden-import=pystray._win32",
        "--hidden-import=PIL",
        "--hidden-import=deep_translator",
        "--hidden-import=yaml",
        "--hidden-import=numpy",
        "--hidden-import=huggingface_hub",
        "--hidden-import=tokenizers",
        # Include config file
        "--add-data=config.yaml;.",
        # Main entry point
        "main.py",
    ]

    print(f"\n  Running PyInstaller...")
    print(f"  Command: {' '.join(cmd[:5])}...\n")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n" + "=" * 55)
        print("  Build successful!")
        print("  Output: dist/VoiceInjector/VoiceInjector.exe")
        print("=" * 55)
    else:
        print("\n  Build FAILED. Check output above for errors.")
        sys.exit(1)


if __name__ == "__main__":
    build()
