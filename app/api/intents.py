from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.intent_classifier import classify_intent

router = APIRouter()


class IntentClassifyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    locale: Optional[str] = Field(default=None, max_length=10)


@router.post("/classify")
async def classify_intent_endpoint(data: IntentClassifyRequest):
    result = classify_intent(data.text, locale=data.locale)
    return result.model_dump()
