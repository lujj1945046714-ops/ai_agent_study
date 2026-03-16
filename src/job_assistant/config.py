from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_path(key: str, default: str) -> Path:
    return Path(os.environ.get(key, default)).expanduser().resolve()


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Workspace layout (write outputs outside site-packages)
WORKDIR = _env_path("JOB_ASSISTANT_WORKDIR", ".")
DATA_DIR = _env_path("JOB_ASSISTANT_DATA_DIR", str(WORKDIR / "data"))
OUTPUT_DIR = _env_path("JOB_ASSISTANT_OUTPUT_DIR", str(WORKDIR / "output"))
PROFILES_DIR = _env_path("JOB_ASSISTANT_PROFILES_DIR", str(WORKDIR / "profiles"))
USER_OUTPUT_DIR = _env_path("JOB_ASSISTANT_USER_OUTPUT_DIR", str(OUTPUT_DIR / "users"))

# LLM (OpenAI-compatible)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# GitHub (optional)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Proxy (optional; used for GitHub API / HuggingFace)
HTTP_PROXY = os.environ.get("HTTP_PROXY", "")

# SQLite persistence (optional)
DB_PATH = _env_path("JOB_ASSISTANT_DB_PATH", str(DATA_DIR / "jobs.db"))
APP_DB_PATH = _env_path("JOB_ASSISTANT_APP_DB_PATH", str(DATA_DIR / "app.db"))

# Web session/auth
SESSION_SECRET = os.environ.get("JOB_ASSISTANT_SESSION_SECRET", "change-me-in-production")

# Runtime knobs
MAX_FETCH_JOBS = int(os.environ.get("JOB_ASSISTANT_MAX_FETCH_JOBS", "30"))
MAX_COARSE_FILTER = int(os.environ.get("JOB_ASSISTANT_MAX_COARSE_FILTER", "20"))
MAX_DEEP_ANALYSIS = int(os.environ.get("JOB_ASSISTANT_MAX_DEEP_ANALYSIS", "5"))
GITHUB_TOP_N = int(os.environ.get("JOB_ASSISTANT_GITHUB_TOP_N", "3"))

# Job discovery tuning
DISCOVERY_FETCH_CONNECT_TIMEOUT_S = int(os.environ.get("JOB_ASSISTANT_DISCOVERY_FETCH_CONNECT_TIMEOUT_S", "5"))
DISCOVERY_FETCH_READ_TIMEOUT_S = int(os.environ.get("JOB_ASSISTANT_DISCOVERY_FETCH_READ_TIMEOUT_S", "12"))
DISCOVERY_FOLLOW_PER_LISTING = int(os.environ.get("JOB_ASSISTANT_DISCOVERY_FOLLOW_PER_LISTING", "5"))
DISCOVERY_FOLLOW_TOTAL = int(os.environ.get("JOB_ASSISTANT_DISCOVERY_FOLLOW_TOTAL", "25"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    USER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
