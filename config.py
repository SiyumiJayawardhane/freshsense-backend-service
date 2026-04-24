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
 
EDGE_TRIGGER_URL = os.getenv("EDGE_TRIGGER_URL", "").strip()
EDGE_TRIGGER_TOKEN = os.getenv("EDGE_TRIGGER_TOKEN", "").strip()
EDGE_TRIGGER_TIMEOUT_SECONDS = float(os.getenv("EDGE_TRIGGER_TIMEOUT_SECONDS", "8").strip())

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "").strip() or "food-images"

CLEANUP_TABLES = tuple(
    t.strip()
    for t in os.getenv(
        "CLEANUP_TABLES",
        "notification_email_dispatches,notifications,sensor_readings,food_items",
    ).split(",")
    if t.strip() and t.strip().lower() != "profiles"
)