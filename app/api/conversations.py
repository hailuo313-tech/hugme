
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db

router = APIRouter()

@router.get("/{conv_id}")
async def get_conversation(conv_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT * FROM conversations WHERE id=:id"), {"id": conv_id})
    conv = result.fetchone()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return dict(conv._mapping)

@router.post("/{conv_id}/reply")
async def ai_reply(conv_id: str, db: AsyncSession = Depends(get_db)):
    return {
        "reply_content": "[AI reply placeholder - set OPENROUTER_API_KEY in .env to activate]",
        "model_used": "none",
        "consistency_score": 1.0
    }
