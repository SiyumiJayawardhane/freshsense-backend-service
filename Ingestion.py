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