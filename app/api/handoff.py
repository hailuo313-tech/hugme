from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class ReplyData(BaseModel):
    content: str
    used_script_id: Optional[str] = None


class ReturnAIData(BaseModel):
    notes: Optional[str] = None
    allow_upsell: bool = True


@router.post("/{task_id}/lock")
async def lock_task(task_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(
        text("UPDATE handoff_tasks SET status='HUMAN_LOCKED', locked_at=NOW() WHERE id=:id"), {"id": task_id}
    )
    await db.commit()
    return {"status": "locked", "task_id": task_id}


@router.post("/{task_id}/reply")
async def operator_reply(task_id: str, data: ReplyData):
    return {"status": "sent", "task_id": task_id}


@router.post("/{task_id}/return-ai")
async def return_to_ai(task_id: str, data: ReturnAIData, db: AsyncSession = Depends(get_db)):
    await db.execute(text("UPDATE handoff_tasks SET status='CLOSED', closed_at=NOW() WHERE id=:id"), {"id": task_id})
    await db.commit()
    return {"status": "returned_to_ai", "task_id": task_id}


@router.post("/{task_id}/escalate")
async def escalate_task(task_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(text("UPDATE handoff_tasks SET status='ESCALATED' WHERE id=:id"), {"id": task_id})
    await db.commit()
    return {"status": "escalated", "task_id": task_id}
