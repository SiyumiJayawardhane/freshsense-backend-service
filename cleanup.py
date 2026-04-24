import json
import urllib.error
import urllib.parse
import urllib.request

import psycopg2.extras

from config import (
    CLEANUP_TABLES,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_STORAGE_BUCKET,
    SUPABASE_URL,
    logger,
)
from db import get_conn


def _extract_storage_path(image_url: str) -> str | None:
    if not image_url:
        return None

    parsed = urllib.parse.urlparse(image_url)
    path = parsed.path or ""

    public_prefix = f"/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/"
    if public_prefix in path:
        return path.split(public_prefix, 1)[1]

    sign_prefix = f"/storage/v1/object/sign/{SUPABASE_STORAGE_BUCKET}/"
    if sign_prefix in path:
        return path.split(sign_prefix, 1)[1]

    bucket_segment = f"/{SUPABASE_STORAGE_BUCKET}/"
    if bucket_segment in path:
        return path.split(bucket_segment, 1)[1]

    return None


def _delete_storage_objects(object_paths: list[str]) -> int:
    if not object_paths:
        return 0
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        logger.warning("Skipping storage cleanup: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing")
        return 0
    if not SUPABASE_STORAGE_BUCKET:
        logger.warning("Skipping storage cleanup: SUPABASE_STORAGE_BUCKET is missing")
        return 0

    endpoint = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}"
    body = json.dumps({"prefixes": [], "paths": object_paths}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="DELETE")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if getattr(resp, "status", 200) >= 400:
                logger.warning("Storage cleanup request returned non-success status=%s", getattr(resp, "status", None))
                return 0
            logger.info("Deleted %s object(s) from Supabase Storage bucket=%s", len(object_paths), SUPABASE_STORAGE_BUCKET)
            return len(object_paths)
    except urllib.error.HTTPError as ex:
        err_body = ex.read().decode("utf-8", errors="ignore")
        logger.error("Storage cleanup HTTP error status=%s body=%s", ex.code, err_body)
    except urllib.error.URLError as ex:
        logger.error("Storage cleanup connection error reason=%s", ex.reason)
    return 0


def run_cleanup_once(source: str = "scheduler") -> dict[str, int | str]:
    conn = get_conn()
    table_counts: dict[str, int] = {}
    deleted_images = 0
    fetched_image_urls = 0

    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT image_url FROM public.food_items WHERE image_url IS NOT NULL")
            image_rows = cur.fetchall() or []
            fetched_image_urls = len(image_rows)
            image_paths = sorted(
                {
                    p
                    for p in (_extract_storage_path(str(r.get("image_url") or "").strip()) for r in image_rows)
                    if p
                }
            )

            for table_name in CLEANUP_TABLES:
                cur.execute(f"SELECT COUNT(*) AS count FROM public.{table_name}")
                row = cur.fetchone() or {}
                count = int(row.get("count", 0))
                table_counts[table_name] = count
                cur.execute(f"DELETE FROM public.{table_name}")

            conn.commit()
            deleted_images = _delete_storage_objects(image_paths)

    except Exception:
        conn.rollback()
        logger.exception("Cleanup failed source=%s", source)
        raise
    finally:
        conn.close()

    summary = {
        "source": source,
        "deleted_images": deleted_images,
        "fetched_image_urls": fetched_image_urls,
    }
    summary.update({f"deleted_{k}": v for k, v in table_counts.items()})
    logger.info("Cleanup completed: %s", summary)
    return summary
