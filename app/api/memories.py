
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid

from api.admin import require_operator
from services.memory_retriever import retrieve as retriever_retrieve

router = APIRouter()

class MemoryCreate(BaseModel):
    memory_type: str
    content: str
    importance_score: Optional[float] = 5.0
    memory_scope: Optional[str] = "global"
    character_id: Optional[str] = None


class MemoryRetrieveRequest(BaseModel):
    """D4-1 retrieval request."""

    query: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(10, ge=1, le=50)
    k_candidates: int = Field(30, ge=1, le=200)
    memory_types: Optional[List[str]] = None
    min_importance: float = Field(0.0, ge=0.0, le=10.0)
    character_id: Optional[str] = None
    include_global: bool = True

@router.get("/users/{user_id}/memories")
async def get_memories(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    result = await db.execute(
        text("SELECT * FROM memories WHERE user_id=:uid AND is_active=true ORDER BY importance_score DESC"),
        {"uid": user_id}
    )
    return [dict(r._mapping) for r in result.fetchall()]

@router.post("/users/{user_id}/memories")
async def create_memory(
    user_id: str,
    data: MemoryCreate,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    mid = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO memories (id,user_id,memory_type,content,importance_score,memory_scope,character_id) VALUES (:id,:uid,:mt,:ct,:sc,:ms,:cid)"),
        {"id": mid, "uid": user_id, "mt": data.memory_type, "ct": data.content, "sc": data.importance_score, "ms": data.memory_scope, "cid": data.character_id}
    )
    await db.commit()
    return {"memory_id": mid, "status": "created"}

@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    return {"status": "ok", "memory_id": memory_id}

@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    await db.execute(text("UPDATE memories SET is_active=false WHERE id=:id"), {"id": memory_id})
    await db.commit()
    return {"status": "deleted"}


@router.post("/users/{user_id}/memories/retrieve")
async def retrieve_memories(
    user_id: str,
    body: MemoryRetrieveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _operator: dict = Depends(require_operator),
):
    """D4-1: Hybrid retrieval (operator JWT required)."""
    trace_id = getattr(request.state, "trace_id", None)
    result = await retriever_retrieve(
        db=db,
        user_id=user_id,
        query_text=body.query,
        k_final=body.k,
        k_candidates=body.k_candidates,
        memory_types=body.memory_types,
        min_importance=body.min_importance,
        character_id=body.character_id,
        include_global=body.include_global,
        trace_id=trace_id,
    )
    return {
        "embedding_used": result.embedding_used,
        "fallback_reason": result.fallback_reason,
        "candidates_scanned": result.candidates_scanned,
        "latency_ms": round(result.latency_ms, 1),
        "hits": [
            {
                "id": h.id,
                "content": h.content,
                "memory_type": h.memory_type,
                "importance_score": h.importance_score,
                "confidence_score": h.confidence_score,
                "emotion_tags": h.emotion_tags,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "last_used_at": h.last_used_at.isoformat() if h.last_used_at else None,
                "similarity": round(h.similarity, 6),
                "final_score": round(h.final_score, 6),
            }
            for h in result.hits
        ],
    }
