"""
Load repo-root `.env` regardless of process cwd (Docker, uvicorn --reload, pytest).

`python-dotenv`'s default `load_dotenv()` only checks `os.getcwd()`, which is not
always the project root inside containers or reload workers.

Uses UTF-8 with BOM handling (`utf-8-sig`) so a BOM on the first line does not
corrupt the first variable name (a common reason keys appear "missing").
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

logger = logging.getLogger(__name__)

# Clinic_app/common/env.py -> parents[2] == repository root (contains Clinic_app/)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOTENV_PATH = _REPO_ROOT / ".env"


def load_project_dotenv() -> None:
    """
    Load variables from `<repo>/.env` into os.environ (does not override existing keys).

    If `.env` is missing, falls back to default dotenv discovery (cwd).
    If a path exists but is not a file (e.g. Docker created a directory when the
    host file was missing), log a clear warning.
    """
    if _DOTENV_PATH.is_file():
        try:
            vals = dotenv_values(
                _DOTENV_PATH,
                encoding="utf-8-sig",
                interpolate=True,
            )
        except OSError as exc:
            logger.warning("Could not read %s: %s", _DOTENV_PATH, exc)
            vals = {}

        for key, value in vals.items():
            if value is None:
                continue
            if key not in os.environ:
                os.environ[key] = value

        return

    if _DOTENV_PATH.exists() and not _DOTENV_PATH.is_file():
        logger.warning(
            "Expected a file at %s but found a non-file. "
            "Docker bind-mounts create a directory if the host path does not exist — "
            "ensure .env exists next to docker-compose.dev.yaml.",
            _DOTENV_PATH,
        )

    load_dotenv(override=False)
