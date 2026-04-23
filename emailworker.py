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

def ensure_email_dispatch_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS public.notification_email_dispatches (
            notification_id uuid PRIMARY KEY REFERENCES public.notifications(id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            fingerprint text,
            recipient_email text,
            status text NOT NULL,
            last_error text,
            attempts integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    cur.execute(
        """
        ALTER TABLE public.notification_email_dispatches
        ADD COLUMN IF NOT EXISTS fingerprint text
        """
    )
    logger.info("Ensured email dispatch tracking table exists")

def build_notification_fingerprint(notification: NotificationRow) -> str:
    payload = "|".join(
        [
            notification.user_id.strip().lower(),
            notification.title.strip().lower(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
 
 
def has_recently_sent_fingerprint(cur, user_id: str, fingerprint: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM public.notification_email_dispatches
        WHERE user_id = %s
          AND fingerprint = %s
          AND status = 'sent'
          AND updated_at >= now() - (%s * interval '1 hour')
        LIMIT 1
        """,
        (user_id, fingerprint, EMAIL_DEDUP_WINDOW_HOURS),
    )
    return cur.fetchone() is not None
 
 
def fetch_pending_notification_rows(cur, limit: int = 50) -> list[NotificationRow]:
    cur.execute(
        """
        SELECT n.id, n.user_id, n.title, n.message, n.severity, n.created_at
        FROM public.notifications n
        LEFT JOIN public.notification_email_dispatches d
          ON d.notification_id = n.id
        WHERE n.severity IN ('warning', 'critical')
          AND (
            d.notification_id IS NULL
            OR (d.status = 'failed' AND d.attempts < 3)
          )
        ORDER BY n.created_at ASC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall() or []
    logger.info(f"Fetched {len(rows)} pending notification(s) for email dispatch")
    return [
        NotificationRow(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            title=str(row["title"]),
            message=str(row["message"]),
            severity=str(row["severity"]),
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]
 
 
def mark_notification_email_attempt(
    cur,
    notification_id: str,
    user_id: str,
    status: str,
    recipient_email: str | None,
    fingerprint: str | None,
    last_error: str | None,
) -> None:
    cur.execute(
        """
        INSERT INTO public.notification_email_dispatches
            (notification_id, user_id, fingerprint, recipient_email, status, last_error, attempts, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, 1, now(), now())
        ON CONFLICT (notification_id)
        DO UPDATE SET
            fingerprint = EXCLUDED.fingerprint,
            recipient_email = EXCLUDED.recipient_email,
            status = EXCLUDED.status,
            last_error = EXCLUDED.last_error,
            attempts = public.notification_email_dispatches.attempts + 1,
            updated_at = now()
        """,
        (notification_id, user_id, fingerprint, recipient_email, status, last_error),
    )
    logger.info(
        "Recorded email dispatch attempt "
        f"notification_id={notification_id} status={status} "
        f"recipient={mask_email(recipient_email)} error={last_error or '<none>'}"
    )
 
 
def send_notification_email(to_email: str, title: str, message: str, severity: str, created_at: str) -> None:
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        logger.warning("Email sending skipped: SMTP_HOST or SMTP_FROM_EMAIL not configured")
        return
 
    subject = f"[FreshSense {severity.upper()}] {title}"
    email_body = (
        "FreshSense Alert\n\n"
        f"{message}\n\n"
        f"Severity: {severity}\n"
        f"Detected at: {created_at}\n"
    )
 
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(email_body)
 
    try:
        logger.info(f"Attempting to send email to {to_email} - Subject: {subject}")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            if SMTP_USE_TLS:
                smtp.starttls()
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)
        logger.info(f"✓ Email sent successfully to {to_email}")
    except Exception as ex:
        logger.error(f"✗ Failed to send email to {to_email}: {type(ex).__name__}: {ex}")
        raise
 
 
def process_pending_notification_emails_once(batch_size: int = 50) -> None:
    conn = get_conn()
    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            logger.info(f"Email worker poll started (batch_size={batch_size})")
            ensure_email_dispatch_table(cur)
            conn.commit()
 
            notifications = fetch_pending_notification_rows(cur, limit=batch_size)
            if not notifications:
                logger.info("No pending notification emails found in this poll")
                return
 
            logger.info(f"Found {len(notifications)} pending notification email(s)")
            for notification in notifications:
                logger.info(
                    "Processing notification for email "
                    f"notification_id={notification.id} user_id={notification.user_id} "
                    f"severity={notification.severity}"
                )
                recipient_email: str | None = None
                fingerprint = build_notification_fingerprint(notification)
                status = "failed"
                error_message: str | None = None
                try:
                    if has_recently_sent_fingerprint(cur, notification.user_id, fingerprint):
                        status = "skipped_duplicate"
                        logger.info(
                            "Skipping duplicate notification email "
                            f"notification_id={notification.id} user_id={notification.user_id} "
                            f"dedup_window_hours={EMAIL_DEDUP_WINDOW_HOURS}"
                        )
                    else:
                        recipient_email = get_user_email(cur, notification.user_id)
                        if not recipient_email:
                            raise ValueError(f"No email found for user_id={notification.user_id}")
                        send_notification_email(
                            to_email=recipient_email,
                            title=notification.title,
                            message=notification.message,
                            severity=notification.severity,
                            created_at=notification.created_at,
                        )
                        status = "sent"
                except Exception as ex:
                    error_message = f"{type(ex).__name__}: {ex}"
                    logger.error(
                        f"Notification email failed for notification_id={notification.id}: {error_message}"
                    )
                finally:
                    mark_notification_email_attempt(
                        cur=cur,
                        notification_id=notification.id,
                        user_id=notification.user_id,
                        status=status,
                        recipient_email=recipient_email,
                        fingerprint=fingerprint,
                        last_error=error_message,
                    )
                    conn.commit()
            logger.info("Email worker poll finished")
    finally:
        conn.close()
 
 
async def email_dispatch_worker() -> None:
    logger.info(
        "Notification email worker started "
        f"(interval={EMAIL_POLL_INTERVAL_SECONDS}s, smtp_host={'set' if SMTP_HOST else 'missing'}, "
        f"smtp_from={'set' if SMTP_FROM_EMAIL else 'missing'}, "
        f"dedup_window_hours={EMAIL_DEDUP_WINDOW_HOURS})"
    )
    while True:
        try:
            process_pending_notification_emails_once()
        except Exception as ex:
            logger.error(f"Email worker loop error: {type(ex).__name__}: {ex}", exc_info=True)
        await asyncio.sleep(EMAIL_POLL_INTERVAL_SECONDS)



