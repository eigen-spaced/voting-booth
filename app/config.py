import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "voting_booth.db")))
CREDENTIALS_PATH = Path(os.getenv("CREDENTIALS_PATH", str(DATA_DIR / "voter_creds.txt")))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_PATH}")
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "change-this-session-secret-for-production")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminBooth2026!")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "booth-admin-export-key")
VOTER_CODE_DIGITS = int(os.getenv("VOTER_CODE_DIGITS", "4"))
