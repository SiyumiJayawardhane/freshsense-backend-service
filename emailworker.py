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

