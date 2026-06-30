"""Background scheduler that applies due status changes and spawns recurring tasks.

Runs as an asyncio task started on app startup. Every minute it:

* applies ScheduledStatusChange rows whose ``scheduled_for`` (naive UTC) has
  passed: sets the todo's status, logs a timeline event, and notifies watchers; and
* materializes due RecurringTask rows into real todos and advances each to its
  next fire time.

Both changes propagate to clients through the normal sync pull (the affected
todos' ``updated_at`` is server-stamped on creation/update).
"""

import asyncio

from .database import SessionLocal
from .models import (
    STATUS_LABELS,
    Bucket,
    EventType,
    RecurringTask,
    ScheduledStatusChange,
    Todo,
    TodoStatus,
    User,
    utcnow,
)
from .recurrence import compute_next_run
from .security import new_id
from .services import add_watcher, notify_watchers, record_event, touch

POLL_SECONDS = 60


async def scheduler_loop() -> None:
    while True:
        try:
            apply_due()
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            print(f"[scheduler] error: {exc!r}", flush=True)
        try:
            materialize_recurring()
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            print(f"[scheduler] recurring error: {exc!r}", flush=True)
        await asyncio.sleep(POLL_SECONDS)


def apply_due() -> int:
    db = SessionLocal()
    try:
        now = utcnow()
        due = (
            db.query(ScheduledStatusChange)
            .filter(ScheduledStatusChange.applied.is_(False), ScheduledStatusChange.scheduled_for <= now)
            .all()
        )
        for sched in due:
            todo = db.get(Todo, sched.todo_id)
            if todo is not None and not todo.deleted and todo.status != sched.target_status:
                old = todo.status
                todo.status = sched.target_status
                todo.completed_at = now if sched.target_status == TodoStatus.done.value else None
                record_event(
                    db, todo, EventType.status_changed,
                    body=f"Status: {STATUS_LABELS.get(old, old)} → "
                    f"{STATUS_LABELS.get(sched.target_status, sched.target_status)} (scheduled)",
                    meta={"from": old, "to": sched.target_status},
                )
                touch(todo)
                notify_watchers(
                    db, todo,
                    f"Scheduled status change applied: {STATUS_LABELS.get(sched.target_status, sched.target_status)}.",
                )
            sched.applied = True
        if due:
            db.commit()
        return len(due)
    finally:
        db.close()


def materialize_recurring() -> int:
    """Create a todo for every active recurring task whose ``next_run`` has passed,
    then advance each to its next fire time."""
    db = SessionLocal()
    try:
        now = utcnow()
        due = (
            db.query(RecurringTask)
            .filter(RecurringTask.active.is_(True), RecurringTask.next_run <= now)
            .all()
        )
        for rec in due:
            user = db.get(User, rec.owner_id)
            bucket = db.get(Bucket, rec.bucket_id)
            if user is None or bucket is None or bucket.deleted:
                # The bucket was deleted (or the owner vanished): stop firing so we
                # don't spawn orphaned tasks every minute.
                rec.active = False
                continue

            todo = Todo(
                id=new_id(),
                bucket_id=rec.bucket_id,
                owner_id=rec.owner_id,
                title=rec.title,
                text=rec.text or "",
                status=rec.status,
                position=0,
                completed_at=now if rec.status == TodoStatus.done.value else None,
                public_token=new_id().replace("-", ""),
            )
            db.add(todo)
            record_event(
                db, todo, EventType.created,
                body="Created task (recurring automation)", actor_email=user.email,
            )
            if rec.watcher_email:
                add_watcher(db, todo, rec.watcher_email, actor=user)

            rec.last_run = now
            rec.next_run = compute_next_run(
                rec.frequency, rec.day_of_week, rec.day_of_month, rec.month_of_year,
                user.timezone, now,
            )
        if due:
            db.commit()
        return len(due)
    finally:
        db.close()
