"""
First-time setup script for Voice Injector.
Detects hardware, configures optimal settings, and downloads model.

Usage:
    python setup.py
"""

import os
import sys
import shutil


def check_python():
    """Check Python version."""
    ver = sys.version_info
    print(f"  Python: {ver.major}.{ver.minor}.{ver.micro}", end="")
    if ver >= (3, 10):
        print(" [OK]")
        return True
    else:
        print(" [FAIL] Python 3.10+ required")
        return False


def check_gpu():
    """Detect NVIDIA GPU and CUDA support."""
    print("  GPU detection:")

    # Check nvidia-smi
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        print("    nvidia-smi: not found")
        print("    -> No NVIDIA GPU detected. Will use CPU mode.")
        return None

    import subprocess

    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("    -> nvidia-smi failed. Will use CPU mode.")
        return None

    gpu_info = result.stdout.strip()
    print(f"    GPU: {gpu_info}")

    # Check ctranslate2 CUDA support
    try:
        import ctranslate2

        cuda_count = ctranslate2.get_cuda_device_count()
        if cuda_count > 0:
            compute_types = ctranslate2.get_supported_compute_types("cuda")
            print(f"    CUDA devices: {cuda_count}")
            print(f"    Supported types: {compute_types}")

            if "float16" in compute_types:
                print("    -> GPU mode: float16 [OPTIMAL]")
                return "float16"
            elif "float32" in compute_types:
                print("    -> GPU mode: float32 [OK]")
                return "float32"
        else:
            print("    CUDA devices: 0")
            print("    -> ctranslate2 CUDA not available. Will use CPU mode.")
            return None
    except ImportError:
        print(
            "    -> ctranslate2 not installed yet. Run: pip install -r requirements.txt"
        )
        return None
    except Exception as e:
        print(f"    -> CUDA check failed: {e}")
        return None


def configure(gpu_compute_type):
    """Write optimal config based on detected hardware."""
    import yaml

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if gpu_compute_type:
        # GPU mode
        config["stt"]["model_size"] = "large-v3-turbo"
        config["stt"]["device"] = "cuda"
        config["stt"]["compute_type"] = gpu_compute_type
        config["stt"]["beam_size"] = 5
        print(f"\n  Config: large-v3-turbo on CUDA ({gpu_compute_type})")
    else:
        # CPU mode
        config["stt"]["model_size"] = "base"
        config["stt"]["device"] = "cpu"
        config["stt"]["compute_type"] = "int8"
        config["stt"]["beam_size"] = 3
        print("\n  Config: base model on CPU (int8)")

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"  Saved to: {config_path}")


def download_model(model_size):
    """Pre-download the Whisper model."""
    print(f"\n  Downloading Whisper model '{model_size}'...")
    print("  (This may take a few minutes on first run)\n")

    from faster_whisper import WhisperModel

    model_dir = os.path.join(os.path.dirname(__file__), "models")
    os.makedirs(model_dir, exist_ok=True)

    # This triggers the download
    model = WhisperModel(
        model_size,
        device="cpu",  # Use CPU for download/verification
        compute_type="int8",
        download_root=model_dir,
    )

    print(f"\n  Model '{model_size}' ready!")
    del model


def main():
    print("=" * 55)
    print("  Voice Injector - First Time Setup")
    print("=" * 55)
    print()

    # Step 1: Check Python
    print("[1/4] Checking Python...")
    if not check_python():
        sys.exit(1)

    # Step 2: Check dependencies
    print("\n[2/4] Checking dependencies...")
    try:
        import sounddevice
        import webrtcvad
        import faster_whisper
        import pynput
        import pystray
        import yaml

        print("  All dependencies installed [OK]")
    except ImportError as e:
        print(f"  Missing: {e}")
        print("  Run: pip install -r requirements.txt")
        sys.exit(1)

    # Step 3: Detect GPU
    print("\n[3/4] Detecting hardware...")
    gpu_type = check_gpu()

    # Step 4: Configure
    print("\n[4/4] Configuring...")
    configure(gpu_type)

    model_size = "large-v3-turbo" if gpu_type else "base"

    # Ask to download model
    print(
        f"\n  Model '{model_size}' needs to be downloaded (~{'3GB' if 'large' in model_size else '150MB'})."
    )
    answer = input("  Download now? [Y/n]: ").strip().lower()
    if answer != "n":
        download_model(model_size)

    print("\n" + "=" * 55)
    print("  Setup complete! Run: python main.py")
    print("=" * 55)


if __name__ == "__main__":
    main()
