"""Configuration models and encrypted persistence utilities for the MinerU client."""

import json
from pathlib import Path
from typing import Any, Dict

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, validator


CONFIG_FILE_NAME = "config.json"
CONFIG_KEY_FILE = "key.key"
CONFIG_VERSION = 1


class AppOptions(BaseModel):
    """Fine-grained user configurable options that mirror API request flags."""

    is_ocr: bool = Field(default=False, description="Whether to enable OCR during parsing.")
    enable_formula: bool = Field(default=True, description="Whether to enable formula detection.")
    enable_table: bool = Field(default=True, description="Whether to enable table detection.")
    language: str = Field(default="ch", description="Document language hint.")
    concurrency: int = Field(default=2, ge=1, le=8, description="Max parallel uploads.")
    auto_retry: bool = Field(default=True, description="Automatically retry failed uploads.")
    max_retry_attempts: int = Field(default=2, ge=0, le=5, description="Automatic retry attempts per file.")

    @validator("language")
    def validate_language(cls, value: str) -> str:
        """Normalise missing language hints to the default Chinese shorthand."""
        if not value:
            return "ch"
        return value


class AppConfig(BaseModel):
    """Root persisted configuration including credentials and task history limits."""

    version: int = CONFIG_VERSION
    api_key: str = ""
    output_dir: str = ""
    options: AppOptions = Field(default_factory=AppOptions)
    history_limit: int = Field(default=20, ge=1, le=200, description="How many task history entries to persist.")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the configuration to a plain dictionary."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AppConfig":
        """Create a configuration instance while tolerating legacy payloads."""
        if not payload:
            return cls()
        # Accept legacy payloads without version/options fields
        if "options" not in payload:
            payload["options"] = {}
        if "version" not in payload:
            payload["version"] = 0
        return cls(**payload)


class ConfigManager:
    """Manage encrypted configuration persistence."""

    def __init__(self, config_path: Path | str | None = None, key_path: Path | str | None = None) -> None:
        """Set up file paths and ensure the encryption key exists."""
        resolved_config = Path(config_path).expanduser() if config_path else None
        base_dir = resolved_config.parent if resolved_config else Path(".")
        self._config_path = resolved_config if resolved_config else base_dir / CONFIG_FILE_NAME
        self._key_path = Path(key_path).expanduser() if key_path else base_dir / CONFIG_KEY_FILE
        self._ensure_key_exists()

    @property
    def config_path(self) -> Path:
        """Return the resolved configuration file path."""
        return self._config_path

    @property
    def key_path(self) -> Path:
        """Return the resolved encryption key file path."""
        return self._key_path

    def _ensure_key_exists(self) -> None:
        """Create a new Fernet key if no encryption key exists yet."""
        if not self._key_path.exists():
            key = Fernet.generate_key()
            self._key_path.write_bytes(key)

    def _get_cipher(self) -> Fernet:
        """Read the Fernet key from disk and build a cipher instance."""
        key = self._key_path.read_bytes()
        return Fernet(key)

    def load(self) -> AppConfig:
        """Load configuration, decrypting the API key when necessary."""
        if not self._config_path.exists():
            return AppConfig()

        with self._config_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if payload.get("api_key"):
            cipher = self._get_cipher()
            try:
                payload["api_key"] = cipher.decrypt(payload["api_key"].encode()).decode()
            except Exception:
                # Fallback to plain text if decryption fails (legacy configs)
                pass

        return AppConfig.from_dict(payload)

    def save(self, config: AppConfig) -> None:
        """Persist configuration while encrypting the API key on disk."""
        payload = config.to_dict()
        cipher = self._get_cipher()

        if payload.get("api_key"):
            payload["api_key"] = cipher.encrypt(payload["api_key"].encode()).decode()

        with self._config_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
