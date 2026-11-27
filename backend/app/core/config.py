import re

from pathlib import Path
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parents[3]

ENV_FILE = BASE_DIR / ".env"

DATABASE_PATH = (
    BASE_DIR / "database/financeai.db"
)

MODEL_PATH = (
    BASE_DIR / "models/modelo_final_v1"
)

APP_NAME = "FinanceAI"

APP_VERSION = "0.1.0"

APP_MODE = "paper_trading"

HOST = "127.0.0.1"

PORT = 8000


def load_api_key(env_file=ENV_FILE):

    if not env_file.is_file():

        raise RuntimeError(
            "Configuracion privada no disponible."
        )

    key = dotenv_values(env_file).get(
        "FINANCEAI_API_KEY"
    )

    if not isinstance(key, str):

        raise RuntimeError(
            "Clave privada no configurada."
        )

    if not re.fullmatch(r"[0-9a-f]{64}", key):

        raise RuntimeError(
            "Formato de clave privada invalido."
        )

    return key
