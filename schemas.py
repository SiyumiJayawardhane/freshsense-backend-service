from pydantic import BaseModel, Field
 
 
class SensorInput(BaseModel):
    humidity: float | None = None
    temperature: float | None = None
    gas_value: float | None = None
 
 
class DetectedItemInput(BaseModel):
    label: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    image_url: str | None = None
    freshness_status: str | None = None
    category: str | None = None
    estimated_days_to_spoil: int | None = None
    freshness_score: float | None = None
    storage_tips: list[str] | None = None
 
 
class IngestPayload(BaseModel):
    user_id: str | None = None
    sensor: SensorInput
    detected_items: list[DetectedItemInput] = []
    captured_at: str | None = None
 
 
class NotificationRow(BaseModel):
    id: str
    user_id: str
    title: str
    message: str
    severity: str
    created_at: str