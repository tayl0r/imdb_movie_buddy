"""Shared utility for loading .env configuration."""

import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """Read key=value pairs from .env file and return as dict."""
    env = {}
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if not os.path.exists(env_path):
        return env
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            env[key.strip()] = value
    return env
