"""Shared utility for loading .env configuration."""

import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """Load config from the .env file, then overlay real environment variables.

    Environment variables take precedence over the .env file, so the same code
    works locally (reads .env) and in containers (secrets injected as env vars
    via docker compose `env_file:`, with no .env file present).
    """
    env = {}
    env_path = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_path):
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
    env.update(os.environ)
    return env
