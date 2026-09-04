"""JEEVAN application settings.

No hardcoded secrets: the JWT secret is read from the JEEVAN_JWT_SECRET env var
or generated once and persisted to data/.jwt_secret (dev convenience only).
"""
import os
import secrets

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # backend/
HOME_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))                 # repo root
DATA_DIR = os.path.join(BASE_DIR, "data")
CCTV_DIR = os.path.join(DATA_DIR, "cctv")


def _load_secret() -> str:
    val = os.environ.get("JEEVAN_JWT_SECRET")
    if val:
        return val
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, ".jwt_secret")
    if os.path.exists(path):
        with open(path) as fh:
            val = fh.read().strip()
        if val:
            return val
    val = secrets.token_hex(32)
    with open(path, "w") as fh:
        fh.write(val)
    return val


class Settings:
    APP_NAME: str = "JEEVAN"
    DATA_DIR: str = DATA_DIR
    CCTV_DIR: str = CCTV_DIR
    # forward slashes -> valid SQLAlchemy URL on Windows and POSIX
    DB_URL: str = os.environ.get(
        "JEEVAN_DB",
        "sqlite:///" + os.path.join(DATA_DIR, "jeevan.db").replace("\\", "/"))
    JWT_SECRET: str = _load_secret()
    JWT_ALG: str = "HS256"
    ACCESS_TTL: int = int(os.environ.get("JEEVAN_ACCESS_TTL", 60 * 30))          # 30 min
    REFRESH_TTL: int = int(os.environ.get("JEEVAN_REFRESH_TTL", 60 * 60 * 24 * 30))  # 30 d
    MAX_UPLOAD_MB: int = int(os.environ.get("JEEVAN_MAX_UPLOAD_MB", 100))
    AI_SERVICE_URL: str = os.environ.get("JEEVAN_AI_URL", "")   # external inference service (optional)
    AI_STAGE_DELAY: float = float(os.environ.get("JEEVAN_AI_DELAY", "0.5"))  # demo stage pacing
    AI_AUTO_VERIFY_CONFIDENCE: float = 0.90
    AI_MODEL_NAME: str = "jeevan-vision-stub"
    AI_MODEL_VERSION: str = "0.3.0"
    DEBUG: bool = os.environ.get("JEEVAN_DEBUG", "1") == "1"

    ALLOWED_VIDEO = {
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
    }


settings = Settings()
os.makedirs(settings.CCTV_DIR, exist_ok=True)
