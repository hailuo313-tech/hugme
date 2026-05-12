
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from pydantic import BaseModel
from typing import Optional
import uuid

router = APIRouter()

class MemoryCreate(BaseModel):
    memory_type: str
    content: str
    importance_score: Optional[float] = 5.0
    memory_scope: Optional[str] = "global"
    character_id: Optional[str] = None

@router.get("/users/{user_id}/memories")
async def get_memories(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM memories WHERE user_id=:uid AND is_active=true ORDER BY importance_score DESC"),
        {"uid": user_id}
    )
    return [dict(r._mapping) for r in result.fetchall()]

@router.post("/users/{user_id}/memories")
async def create_memory(user_id: str, data: MemoryCreate, db: AsyncSession = Depends(get_db)):
    mid = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO memories (id,user_id,memory_type,content,importance_score,memory_scope,character_id) VALUES (:id,:uid,:mt,:ct,:sc,:ms,:cid)"),
        {"id": mid, "uid": user_id, "mt": data.memory_type, "ct": data.content, "sc": data.importance_score, "ms": data.memory_scope, "cid": data.character_id}
    )
    await db.commit()
    return {"memory_id": mid, "status": "created"}

@router.patch("/memories/{memory_id}")
async def update_memory(memory_id: str, db: AsyncSession = Depends(get_db)):
    return {"status": "ok", "memory_id": memory_id}

@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(text("UPDATE memories SET is_active=false WHERE id=:id"), {"id": memory_id})
    await db.commit()
    return {"status": "deleted"}
