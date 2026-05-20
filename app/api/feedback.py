"""
H-06: 坐席看板反馈收集 API
- POST /api/v1/admin/feedback     — 提交坐席看板使用反馈
- GET  /api/v1/admin/feedback     — 获取反馈列表（管理员）
- GET  /api/v1/admin/feedback/{id} — 获取单条反馈详情
- PUT  /api/v1/admin/feedback/{id} — 更新反馈状态（管理员）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from core.database import get_db
from pydantic import BaseModel
from typing import Any, Optional
from loguru import logger
from datetime import datetime
import json

router = APIRouter()

# ── 数据模型 ────────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    """提交反馈的请求模型"""
    overall_satisfaction: int
    usability_rating: int
    ai_assist_rating: int
    translation_quality: int
    features_used: list[str]
    issues: str
    suggestions: str
    operator_id: Optional[str] = None

class FeedbackUpdate(BaseModel):
    """更新反馈状态的请求模型"""
    status: str  # "pending", "reviewed", "resolved"
    admin_notes: Optional[str] = None

class FeedbackResponse(BaseModel):
    """反馈响应模型"""
    id: int
    operator_id: Optional[str]
    overall_satisfaction: int
    usability_rating: int
    ai_assist_rating: int
    translation_quality: int
    features_used: list[str]
    issues: str
    suggestions: str
    status: str
    admin_notes: Optional[str]
    created_at: str
    updated_at: str

# ── 数据库表初始化 ───────────────────────────────────────────────────

async def _ensure_feedback_table(db: AsyncSession) -> None:
    """确保反馈表存在"""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS operator_feedback (
        id SERIAL PRIMARY KEY,
        operator_id VARCHAR(255),
        overall_satisfaction INTEGER NOT NULL CHECK (overall_satisfaction BETWEEN 1 AND 5),
        usability_rating INTEGER NOT NULL CHECK (usability_rating BETWEEN 1 AND 5),
        ai_assist_rating INTEGER NOT NULL CHECK (ai_assist_rating BETWEEN 1 AND 5),
        translation_quality INTEGER NOT NULL CHECK (translation_quality BETWEEN 1 AND 5),
        features_used JSONB NOT NULL DEFAULT '[]'::jsonb,
        issues TEXT NOT NULL,
        suggestions TEXT,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        admin_notes TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    
    CREATE INDEX IF NOT EXISTS idx_operator_feedback_operator_id ON operator_feedback(operator_id);
    CREATE INDEX IF NOT EXISTS idx_operator_feedback_status ON operator_feedback(status);
    CREATE INDEX IF NOT EXISTS idx_operator_feedback_created_at ON operator_feedback(created_at DESC);
    """
    await db.execute(text(create_table_sql))
    await db.commit()

# ── API 端点 ────────────────────────────────────────────────────────

@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def create_feedback(
    feedback: FeedbackCreate,
    db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    提交坐席看板使用反馈
    
    验收标准：能够成功收集反馈数据，为H-06任务提供数据支持
    """
    try:
        await _ensure_feedback_table(db)
        
        insert_sql = """
        INSERT INTO operator_feedback (
            operator_id, overall_satisfaction, usability_rating, ai_assist_rating,
            translation_quality, features_used, issues, suggestions
        ) VALUES (
            :operator_id, :overall_satisfaction, :usability_rating, :ai_assist_rating,
            :translation_quality, :features_used::jsonb, :issues, :suggestions
        ) RETURNING id, created_at
        """
        
        result = await db.execute(
            text(insert_sql),
            {
                "operator_id": feedback.operator_id,
                "overall_satisfaction": feedback.overall_satisfaction,
                "usability_rating": feedback.usability_rating,
                "ai_assist_rating": feedback.ai_assist_rating,
                "translation_quality": feedback.translation_quality,
                "features_used": json.dumps(feedback.features_used),
                "issues": feedback.issues,
                "suggestions": feedback.suggestions,
            }
        )
        row = result.fetchone()
        await db.commit()
        
        logger.info(f"反馈提交成功，ID: {row[0]}, 操作员: {feedback.operator_id}")
        
        return {
            "success": True,
            "feedback_id": row[0],
            "created_at": row[1].isoformat() if row[1] else None
        }
        
    except Exception as e:
        logger.error(f"反馈提交失败: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"反馈提交失败: {str(e)}"
        )

@router.get("/feedback")
async def list_feedback(
    status_filter: Optional[str] = Query(None, description="按状态筛选: pending, reviewed, resolved"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    获取反馈列表（管理员功能）
    
    用于H-06任务的反馈管理和处理
    """
    try:
        await _ensure_feedback_table(db)
        
        where_clause = ""
        params = {"limit": limit, "offset": offset}
        
        if status_filter:
            where_clause = "WHERE status = :status"
            params["status"] = status_filter
        
        count_sql = f"SELECT COUNT(*) FROM operator_feedback {where_clause}"
        total_result = await db.execute(text(count_sql), params)
        total = total_result.scalar()
        
        list_sql = f"""
        SELECT id, operator_id, overall_satisfaction, usability_rating, ai_assist_rating,
               translation_quality, features_used, issues, suggestions, status, admin_notes,
               created_at, updated_at
        FROM operator_feedback
        {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """
        
        result = await db.execute(text(list_sql), params)
        rows = result.fetchall()
        
        feedback_list = []
        for row in rows:
            feedback_list.append({
                "id": row[0],
                "operator_id": row[1],
                "overall_satisfaction": row[2],
                "usability_rating": row[3],
                "ai_assist_rating": row[4],
                "translation_quality": row[5],
                "features_used": json.loads(row[6]) if row[6] else [],
                "issues": row[7],
                "suggestions": row[8],
                "status": row[9],
                "admin_notes": row[10],
                "created_at": row[11].isoformat() if row[11] else None,
                "updated_at": row[12].isoformat() if row[12] else None,
            })
        
        return {
            "items": feedback_list,
            "total": total,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error(f"获取反馈列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取反馈列表失败: {str(e)}"
        )

@router.get("/feedback/{feedback_id}")
async def get_feedback(
    feedback_id: int,
    db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """获取单条反馈详情"""
    try:
        await _ensure_feedback_table(db)
        
        sql = """
        SELECT id, operator_id, overall_satisfaction, usability_rating, ai_assist_rating,
               translation_quality, features_used, issues, suggestions, status, admin_notes,
               created_at, updated_at
        FROM operator_feedback
        WHERE id = :feedback_id
        """
        
        result = await db.execute(text(sql), {"feedback_id": feedback_id})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="反馈不存在"
            )
        
        return {
            "id": row[0],
            "operator_id": row[1],
            "overall_satisfaction": row[2],
            "usability_rating": row[3],
            "ai_assist_rating": row[4],
            "translation_quality": row[5],
            "features_used": json.loads(row[6]) if row[6] else [],
            "issues": row[7],
            "suggestions": row[8],
            "status": row[9],
            "admin_notes": row[10],
            "created_at": row[11].isoformat() if row[11] else None,
            "updated_at": row[12].isoformat() if row[12] else None,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取反馈详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取反馈详情失败: {str(e)}"
        )

@router.put("/feedback/{feedback_id}")
async def update_feedback(
    feedback_id: int,
    update: FeedbackUpdate,
    db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    更新反馈状态（管理员功能）
    
    用于H-06任务的反馈处理，将反馈标记为已处理
    """
    try:
        await _ensure_feedback_table(db)
        
        sql = """
        UPDATE operator_feedback
        SET status = :status,
            admin_notes = :admin_notes,
            updated_at = NOW()
        WHERE id = :feedback_id
        RETURNING id, updated_at
        """
        
        result = await db.execute(
            text(sql),
            {
                "feedback_id": feedback_id,
                "status": update.status,
                "admin_notes": update.admin_notes,
            }
        )
        row = result.fetchone()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="反馈不存在"
            )
        
        await db.commit()
        logger.info(f"反馈状态更新成功，ID: {feedback_id}, 状态: {update.status}")
        
        return {
            "success": True,
            "feedback_id": row[0],
            "updated_at": row[1].isoformat() if row[1] else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新反馈状态失败: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新反馈状态失败: {str(e)}"
        )