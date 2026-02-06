"""
Configuration loader - reads and validates config.yaml.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    channels: int = 1
    chunk_duration_ms: int = 30
    device_index: Optional[int] = None


@dataclass
class STTConfig:
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    default_task: str = "transcribe"
    language: Optional[str] = None
    beam_size: int = 5
    initial_prompt: Optional[str] = None


@dataclass
class VADConfig:
    aggressiveness: int = 2
    min_speech_duration: float = 0.5
    silence_duration: float = 0.8
    pre_speech_pad: float = 0.3


@dataclass
class HotkeyConfig:
    push_to_talk: str = "ctrl+shift+space"
    toggle_mode: str = "ctrl+shift+t"
    quit: str = "ctrl+shift+q"


@dataclass
class InjectorConfig:
    keystroke_delay: float = 0.005
    add_trailing_space: bool = True
    add_trailing_newline: bool = False


@dataclass
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    injector: InjectorConfig = field(default_factory=InjectorConfig)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from YAML file.
    Falls back to defaults if file not found.
    """
    if config_path is None:
        # Look for config.yaml in the project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(project_root, "config.yaml")

    config = AppConfig()

    if not os.path.exists(config_path):
        logger.warning(f"Config file not found at {config_path}, using defaults")
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return config

        # Audio config
        if "audio" in data:
            a = data["audio"]
            config.audio = AudioConfig(
                sample_rate=a.get("sample_rate", 16000),
                channels=a.get("channels", 1),
                chunk_duration_ms=a.get("chunk_duration_ms", 30),
                device_index=a.get("device_index"),
            )

        # STT config
        if "stt" in data:
            s = data["stt"]
            config.stt = STTConfig(
                model_size=s.get("model_size", "small"),
                device=s.get("device", "cpu"),
                compute_type=s.get("compute_type", "int8"),
                default_task=s.get("default_task", "transcribe"),
                language=s.get("language"),
                beam_size=s.get("beam_size", 5),
                initial_prompt=s.get("initial_prompt"),
            )

        # VAD config
        if "vad" in data:
            v = data["vad"]
            config.vad = VADConfig(
                aggressiveness=v.get("aggressiveness", 2),
                min_speech_duration=v.get("min_speech_duration", 0.5),
                silence_duration=v.get("silence_duration", 0.8),
                pre_speech_pad=v.get("pre_speech_pad", 0.3),
            )

        # Hotkey config
        if "hotkeys" in data:
            h = data["hotkeys"]
            config.hotkeys = HotkeyConfig(
                push_to_talk=h.get("push_to_talk", "ctrl+shift+space"),
                toggle_mode=h.get("toggle_mode", "ctrl+shift+t"),
                quit=h.get("quit", "ctrl+shift+q"),
            )

        # Injector config
        if "injector" in data:
            i = data["injector"]
            config.injector = InjectorConfig(
                keystroke_delay=i.get("keystroke_delay", 0.005),
                add_trailing_space=i.get("add_trailing_space", True),
                add_trailing_newline=i.get("add_trailing_newline", False),
            )

        logger.info(f"Configuration loaded from {config_path}")
        return config

    except Exception as e:
        logger.error(f"Failed to load config from {config_path}: {e}")
        logger.info("Using default configuration")
        return AppConfig()
