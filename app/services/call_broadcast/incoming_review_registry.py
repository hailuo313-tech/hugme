"""In-memory registry for live inbound calls awaiting operator accept/reject."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

DEFAULT_REVIEW_TTL_SECONDS = 90


@dataclass
class PendingIncomingReview:
    job_id: str
    account_id: str
    chat_id: int
    access_hash: int | None
    trace_id: str
    inbound_call_number: int
    expires_at: float


_by_job_id: dict[str, PendingIncomingReview] = {}
_by_chat_key: dict[tuple[str, int], str] = {}


def register_pending_review(
    *,
    job_id: str,
    account_id: str,
    chat_id: int,
    access_hash: int | None,
    trace_id: str,
    inbound_call_number: int,
    ttl_seconds: int = DEFAULT_REVIEW_TTL_SECONDS,
) -> PendingIncomingReview:
    review = PendingIncomingReview(
        job_id=job_id,
        account_id=account_id,
        chat_id=int(chat_id),
        access_hash=access_hash,
        trace_id=trace_id,
        inbound_call_number=inbound_call_number,
        expires_at=time.time() + max(30, int(ttl_seconds)),
    )
    _by_job_id[job_id] = review
    _by_chat_key[(account_id, int(chat_id))] = job_id
    return review


def get_pending_review(job_id: str) -> PendingIncomingReview | None:
    review = _by_job_id.get(job_id)
    if review is None:
        return None
    if review.expires_at <= time.time():
        return None
    return review


def pop_pending_review(job_id: str) -> PendingIncomingReview | None:
    review = _by_job_id.pop(job_id, None)
    if review is None:
        return None
    _by_chat_key.pop((review.account_id, review.chat_id), None)
    return review


def list_expired_job_ids() -> list[str]:
    now = time.time()
    expired = [job_id for job_id, review in _by_job_id.items() if review.expires_at <= now]
    for job_id in expired:
        pop_pending_review(job_id)
    return expired


def pending_review_count() -> int:
    cleanup = list_expired_job_ids()
    return len(_by_job_id)


def clear_all() -> None:
    _by_job_id.clear()
    _by_chat_key.clear()


def snapshot_pending() -> list[dict[str, Any]]:
    now = time.time()
    items: list[dict[str, Any]] = []
    for review in _by_job_id.values():
        items.append(
            {
                "job_id": review.job_id,
                "account_id": review.account_id,
                "chat_id": review.chat_id,
                "inbound_call_number": review.inbound_call_number,
                "seconds_remaining": max(0, int(review.expires_at - now)),
            }
        )
    return items
