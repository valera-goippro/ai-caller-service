import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "calls.db"
RECORDINGS_DIR = BASE_DIR / "data" / "recordings"

# Load from vault.env
def _load_vault():
    vault_path = Path.home() / "vault.env"
    env = {}
    if vault_path.exists():
        for line in vault_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

_vault = _load_vault()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", _vault.get("GROQ_API_KEY", ""))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", _vault.get("OPENAI_API_KEY", ""))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", _vault.get("ANTHROPIC_API_KEY", ""))

FS_ESL_HOST = os.getenv("FREESWITCH_ESL_HOST", _vault.get("FREESWITCH_ESL_HOST", "127.0.0.1"))
FS_ESL_PORT = int(os.getenv("FREESWITCH_ESL_PORT", _vault.get("FREESWITCH_ESL_PORT", "8021")))
FS_ESL_PASSWORD = os.getenv("FREESWITCH_ESL_PASSWORD", _vault.get("FREESWITCH_ESL_PASSWORD", "ClueCon"))

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8091  # 8090 may be in use

# Ensure data dirs exist
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
