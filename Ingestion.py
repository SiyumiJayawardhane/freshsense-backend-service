from typing import Any
 
from schemas import DetectedItemInput, SensorInput
 
 
def parse_label(label: str) -> tuple[str, str]:
    raw = (label or "").strip().lower()
    if "_" in raw:
        status_raw, item_raw = raw.split("_", 1)
        if status_raw in {"fresh", "spoiled", "at", "atrisk", "at_risk"}:
            if status_raw in {"at", "atrisk", "at_risk"}:
                return "at_risk", item_raw
            return status_raw, item_raw
    return "fresh", raw or "unknown_item"

def derive_detection(item: DetectedItemInput) -> dict[str, Any]:
    status_from_label, item_name_raw = parse_label(item.label)
    status = item.freshness_status or status_from_label
    name = item_name_raw.replace("_", " ").strip().title()
    confidence_pct = round(item.confidence * 100, 2)
    if item.freshness_score is not None:
        freshness_score = item.freshness_score
    elif status == "fresh":
        freshness_score = max(80.0, confidence_pct)
    elif status == "at_risk":
        freshness_score = max(40.0, min(79.0, confidence_pct))
    else:
        freshness_score = min(39.0, confidence_pct)
 
    return {
        "name": name,
        "category": item.category or "Produce",
        "image_url": item.image_url,
        "freshness_score": freshness_score,
        "freshness_status": status,
        "confidence": confidence_pct,
        "estimated_days_to_spoil": (
            item.estimated_days_to_spoil
            if item.estimated_days_to_spoil is not None
            else (5 if status == "fresh" else 2 if status == "at_risk" else 0)
        ),
        "storage_tips": item.storage_tips or [],
    }

def upsert_food_item(cur, user_id: str, item: dict[str, Any], detected_at: str) -> str:
    cur.execute(
        "SELECT id FROM public.food_items WHERE user_id = %s AND name = %s LIMIT 1",
        (user_id, item["name"]),
    )
    existing = cur.fetchone()
 
    if existing:
        food_id = str(existing["id"])
        cur.execute(
            """
            UPDATE public.food_items
            SET category = %s,
                image_url = %s,
                freshness_score = %s,
                freshness_status = %s,
                confidence = %s,
                estimated_days_to_spoil = %s,
                storage_tips = %s,
                detected_at = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                item["category"],
                item["image_url"],
                item["freshness_score"],
                item["freshness_status"],
                item["confidence"],
                item["estimated_days_to_spoil"],
                item["storage_tips"],
                detected_at,
                detected_at,
                food_id,
            ),
        )
        return food_id
 
    cur.execute(
        """
        INSERT INTO public.food_items
            (user_id, name, category, image_url, freshness_score, freshness_status,
             confidence, estimated_days_to_spoil, storage_tips, detected_at, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            user_id,
            item["name"],
            item["category"],
            item["image_url"],
            item["freshness_score"],
            item["freshness_status"],
            item["confidence"],
            item["estimated_days_to_spoil"],
            item["storage_tips"],
            detected_at,
            detected_at,
            detected_at,
        ),
    )
    return str(cur.fetchone()["id"])