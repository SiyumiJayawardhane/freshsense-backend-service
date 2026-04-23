import logging
import os
 
from dotenv import load_dotenv
 
load_dotenv()
 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("freshsense-live-backend")
 
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DEFAULT_USER_ID = os.getenv("SUPABASE_USER_ID", "").strip()
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*").strip() or "*"
 
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587").strip())
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
 
EMAIL_POLL_INTERVAL_SECONDS = float(os.getenv("EMAIL_POLL_INTERVAL_SECONDS", "10").strip())
EMAIL_DEDUP_WINDOW_HOURS = int(os.getenv("EMAIL_DEDUP_WINDOW_HOURS", "24").strip())