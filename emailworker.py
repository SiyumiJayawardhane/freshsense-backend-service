import asyncio
import hashlib
import smtplib
from email.message import EmailMessage
 
import psycopg2.extras
 
from config import (
    EMAIL_DEDUP_WINDOW_HOURS,
    EMAIL_POLL_INTERVAL_SECONDS,
    SMTP_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_TLS,
    logger,
)
from db import get_conn
from schemas import NotificationRow

def mask_email(email: str | None) -> str:
    if not email:
        return "<missing>"
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + ("*" * (len(local) - 2)) + local[-1]
    return f"{masked_local}@{domain}"

def get_user_email(cur, user_id: str) -> str | None:
    cur.execute(
        "SELECT email FROM auth.users WHERE id = %s LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        logger.warning(f"No auth.users row found for user_id={user_id}")
        return None
    email = row.get("email")
    normalized = str(email).strip() if email else None
    if not normalized:
        logger.warning(f"auth.users.email missing for user_id={user_id}")
    else:
        logger.info(f"Resolved recipient for user_id={user_id}: {mask_email(normalized)}")
    return normalized