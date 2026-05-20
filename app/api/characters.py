from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db

router = APIRouter()


@router.get("")
async def list_characters(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT * FROM characters WHERE status='active'"))
    return [dict(r._mapping) for r in result.fetchall()]


@router.get("/{character_id}")
async def get_character(character_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT * FROM characters WHERE id=:id"), {"id": character_id})
    char = result.fetchone()
    if not char:
        raise HTTPException(404, "Character not found")
    return dict(char._mapping)
