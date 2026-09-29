"""Runtime configuration, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv(
        "DATABASE_URL", "postgresql+psycopg2://inventory:inventory@localhost:5432/inventory"))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", ROOT / "data")))
    sql_dir: Path = field(default_factory=lambda: ROOT / "sql")
    seed: int = field(default_factory=lambda: _int("SIM_SEED", 42))
    slack_webhook_url: str | None = field(default_factory=lambda: os.getenv("SLACK_WEBHOOK_URL") or None)
    smtp_host: str | None = field(default_factory=lambda: os.getenv("SMTP_HOST") or None)
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", 587))
    smtp_user: str | None = field(default_factory=lambda: os.getenv("SMTP_USER") or None)
    smtp_password: str | None = field(default_factory=lambda: os.getenv("SMTP_PASSWORD") or None)
    alert_from: str | None = field(default_factory=lambda: os.getenv("ALERT_FROM") or None)
    alert_to: str | None = field(default_factory=lambda: os.getenv("ALERT_TO") or None)

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def clean_dir(self) -> Path:
        return self.data_dir / "clean"


def get_settings() -> Settings:
    return Settings()
