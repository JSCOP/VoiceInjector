"""
Voice Injector - Speech-to-Text injection at cursor position.

Usage:
    python main.py              # Start with default config
    python main.py --config X   # Start with custom config file
    python main.py --devices    # List audio input devices
    python main.py --test-mic   # Test microphone input
    python main.py --test-inject # Test text injection
"""

import argparse
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)-7s] %(name)-20s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("voice_injector.log", encoding="utf-8"),
        ],
    )

    # Reduce noise from libraries
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("ctranslate2").setLevel(logging.WARNING)


def cmd_list_devices():
    """List available audio input devices."""
    import sounddevice as sd

    print("\n=== Audio Input Devices ===\n")
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            default = " (DEFAULT)" if i == sd.default.device[0] else ""
            print(f"  [{i}] {dev['name']}{default}")
            print(
                f"      Channels: {dev['max_input_channels']}, "
                f"Sample Rate: {dev['default_samplerate']:.0f} Hz"
            )
    print()


def cmd_test_mic():
    """Test microphone input - records for 3 seconds and shows level."""
    import numpy as np
    import sounddevice as sd

    print("\n=== Microphone Test ===")
    print("Recording for 3 seconds... Speak now!\n")

    sample_rate = 16000
    duration = 3
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
    )
    sd.wait()

    # Calculate audio level
    audio_np = audio.flatten().astype(np.float32)
    rms = np.sqrt(np.mean(audio_np**2))
    peak = np.max(np.abs(audio_np))

    print(f"  RMS Level:  {rms:.0f} / 32768")
    print(f"  Peak Level: {peak:.0f} / 32768")

    if peak < 500:
        print("\n  WARNING: Audio level very low. Check your microphone.")
    elif peak < 3000:
        print("\n  Audio level is moderate. Speak louder or move closer to mic.")
    else:
        print("\n  Audio level looks good!")
    print()


def cmd_test_inject():
    """Test text injection."""
    from src.injector.text_injector import TextInjector

    injector = TextInjector(
        keystroke_delay=0.005, add_trailing_space=False, add_trailing_newline=False
    )

    print("\n=== Text Injection Test ===")
    print("In 3 seconds, text will be injected at your cursor position.")
    print("Click on a text field (Notepad, browser, etc.) NOW!\n")

    import time

    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    test_text = (
        "Hello! Voice Injector is working. 안녕하세요! 음성 주입기가 작동합니다."
    )
    print(f"\n  Injecting: '{test_text}'")
    injector.inject_text_fast(test_text)
    print("  Done!")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Voice Injector - Speech-to-Text injection at cursor position"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to config.yaml file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--devices",
        action="store_true",
        help="List audio input devices and exit",
    )
    parser.add_argument(
        "--test-mic",
        action="store_true",
        help="Test microphone input and exit",
    )
    parser.add_argument(
        "--test-inject",
        action="store_true",
        help="Test text injection and exit",
    )

    args = parser.parse_args()

    # Handle utility commands
    if args.devices:
        cmd_list_devices()
        return

    if args.test_mic:
        cmd_test_mic()
        return

    if args.test_inject:
        cmd_test_inject()
        return

    # Normal startup
    setup_logging(verbose=args.verbose)

    from src.config_loader import load_config
    from src.app import VoiceInjectorApp

    config = load_config(args.config)
    app = VoiceInjectorApp(config)

    try:
        app.start()
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
