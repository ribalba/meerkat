"""Offline sync.

The client keeps a local IndexedDB mirror and a queue of mutations made while
offline. On reconnect it POSTs the queue to ``/api/sync/push``; conflicts are
resolved last-write-wins on the client-supplied ``updated_at``. It then GETs
``/api/sync/pull?since=<ts>`` to fetch everything changed server-side (including
soft-deleted rows, so deletes propagate).
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import Bucket, Event, EventType, Todo, utcnow
from ..schemas import (
    SyncMutation,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncResult,
)
from ..security import get_current_user, new_id
from ..services import attach_to_events, attach_to_todos, log_todo_changes, snapshot

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger("uvicorn.error")


def _norm(dt: datetime | None) -> datetime:
    """Coerce any datetime to naive UTC, matching how values are stored (SQLite drops
    tzinfo). tz-aware input is converted to UTC then stripped; naive input is assumed UTC."""
    if dt is None:
        return datetime(1970, 1, 1)
    if dt.tzinfo:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _newer(incoming: datetime, existing: datetime | None) -> bool:
    """True if the incoming change should win under last-write-wins."""
    return _norm(incoming) >= _norm(existing)


@router.post("/push", response_model=SyncPushResponse)
def push(payload: SyncPushRequest, db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    results: list[SyncResult] = []
    for m in payload.mutations:
        # Each mutation runs in its own savepoint: a failure rolls back only that
        # mutation, and a successful one is flushed so later mutations in the same
        # batch (e.g. a comment on a just-created todo) can see it.
        try:
            with db.begin_nested():
                status = _apply(db, m, user)
                db.flush()
            results.append(SyncResult(op_id=m.op_id, status=status))
        except Exception as exc:  # noqa: BLE001 - report per-mutation, keep going
            logger.exception("sync push failed for %s %s (op %s)", m.entity, m.action, m.op_id)
            results.append(SyncResult(op_id=m.op_id, status="error", detail=str(exc)))
    db.commit()
    return SyncPushResponse(results=results, server_time=utcnow())


def _apply(db: DBSession, m: SyncMutation, user) -> str:
    if m.entity == "bucket":
        return _apply_bucket(db, m, user)
    if m.entity == "todo":
        return _apply_todo(db, m, user)
    if m.entity == "comment":
        return _apply_comment(db, m, user)
    raise ValueError(f"Unknown entity: {m.entity}")


def _apply_bucket(db: DBSession, m: SyncMutation, user) -> str:
    bucket = db.get(Bucket, m.id)
    if bucket and bucket.owner_id != user.id:
        raise ValueError("Not allowed")
    if bucket is None:
        if m.action == "delete":
            return "skipped"
        bucket = Bucket(id=m.id, owner_id=user.id, name=m.data.get("name", "Untitled"))
        db.add(bucket)
    elif not _newer(m.updated_at, bucket.updated_at):
        return "skipped"  # server copy is newer

    if m.action == "delete":
        bucket.deleted = True
    else:
        for f in ("name", "color", "position"):
            if f in m.data:
                setattr(bucket, f, m.data[f])
    bucket.updated_at = _norm(m.updated_at)
    return "applied"


def _apply_todo(db: DBSession, m: SyncMutation, user) -> str:
    todo = db.get(Todo, m.id)
    if todo and todo.owner_id != user.id:
        raise ValueError("Not allowed")
    is_new = todo is None
    if todo is None:
        if m.action == "delete":
            return "skipped"
        # An update can reach the server before its create (or after the create
        # failed). Without a bucket_id we can't insert the row (NOT NULL FK), so
        # skip and let the client resend once the create has landed.
        bucket_id = m.data.get("bucket_id")
        if not bucket_id:
            return "skipped"
        todo = Todo(
            id=m.id,
            owner_id=user.id,
            bucket_id=bucket_id,
            title=m.data.get("title", "Untitled"),
            public_token=new_id().replace("-", ""),
        )
        db.add(todo)
        db.add(Event(id=new_id(), todo_id=todo.id, type=EventType.created.value,
                     body="Created task (offline)", actor_email=user.email))
    elif not _newer(m.updated_at, todo.updated_at):
        return "skipped"

    if m.action == "delete":
        todo.deleted = True
    else:
        before = snapshot(todo)
        for f in ("title", "text", "status", "position", "bucket_id", "parent_id"):
            if f in m.data:
                setattr(todo, f, m.data[f])
        # Any change to an existing todo is logged to the timeline and emailed to
        # watchers (not on first creation, which has its own 'created' event).
        if not is_new:
            log_todo_changes(db, todo, before, user)
    todo.updated_at = _norm(m.updated_at)
    return "applied"


def _apply_comment(db: DBSession, m: SyncMutation, user) -> str:
    # Comments are append-only; creating with a known id is idempotent.
    existing = db.get(Event, m.id)
    if existing is not None:
        return "skipped"
    todo = db.get(Todo, m.data.get("todo_id"))
    if todo is None:
        raise ValueError("Todo not found for comment")
    db.add(
        Event(
            id=m.id,
            todo_id=todo.id,
            type=EventType.comment.value,
            body=m.data.get("body", ""),
            actor_email=user.email,
            created_at=_norm(m.updated_at),
            updated_at=_norm(m.updated_at),
        )
    )
    # Advance the todo to the comment's client time (never past it), so a separately
    # queued todo edit with a later timestamp still wins under last-write-wins.
    ts = _norm(m.updated_at)
    if todo.updated_at is None or ts > todo.updated_at:
        todo.updated_at = ts
    return "applied"


@router.get("/pull", response_model=SyncPullResponse)
def pull(since: datetime | None = None, db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    since_dt = _norm(since)

    buckets = (
        db.query(Bucket)
        .filter(Bucket.owner_id == user.id, Bucket.updated_at > since_dt)
        .all()
    )
    todos = (
        db.query(Todo)
        .filter(Todo.owner_id == user.id, Todo.updated_at > since_dt)
        .all()
    )
    attach_to_todos(db, todos)
    events = (
        db.query(Event)
        .join(Todo, Event.todo_id == Todo.id)
        .filter(Todo.owner_id == user.id, Event.updated_at > since_dt)
        .all()
    )
    attach_to_events(db, events)

    return SyncPullResponse(
        server_time=utcnow(), buckets=buckets, todos=todos, events=events
    )
