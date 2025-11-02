"""Unit tests covering the configuration persistence helpers."""

import json
from pathlib import Path

from core.config import AppConfig, AppOptions, ConfigManager


def test_config_roundtrip(tmp_path):
    """Persist and reload configuration to ensure encryption round-trip works."""
    config_path = tmp_path / "config.json"
    key_path = tmp_path / "key.key"
    manager = ConfigManager(config_path=config_path, key_path=key_path)

    options = AppOptions(
        is_ocr=True,
        enable_formula=False,
        enable_table=True,
        language="en",
        concurrency=3,
        auto_retry=True,
        max_retry_attempts=2,
    )
    config = AppConfig(api_key="secret", output_dir="/tmp/output", options=options)
    manager.save(config)

    loaded = manager.load()
    assert loaded.api_key == config.api_key
    assert loaded.output_dir == config.output_dir
    assert loaded.options == options


def test_config_loads_defaults_when_missing(tmp_path):
    """Verify loading a missing file yields default configuration values."""
    manager = ConfigManager(config_path=tmp_path / "missing.json", key_path=tmp_path / "key.key")
    config = manager.load()
    assert config.api_key == ""
    assert config.output_dir == ""
    assert config.options.enable_table


def test_config_loads_plaintext_backward_compatibility(tmp_path):
    """Ensure legacy plaintext configs can still be read successfully."""
    config_path = tmp_path / "config.json"
    key_path = tmp_path / "key.key"
    key_path.write_bytes(b"test-key" * 4)
    payload = {"api_key": "plain-text-key", "output_dir": "/data"}
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    manager = ConfigManager(config_path=config_path, key_path=key_path)
    config = manager.load()
    assert config.api_key == "plain-text-key"
    assert config.output_dir == "/data"
