"""User-defined (custom) statuses.

Additive to the four built-in statuses (Backlog/Now/Blocked/Done): a user can
define extra statuses that behave like the built-ins in the sidebar, task list
and dropdowns. Owner-scoped and edited online; the client fetches the list at
boot to build its full set of statuses.

Built-ins live in code and can't be edited or deleted here. Deleting a custom
status moves anything still using it back to the backlog so no row is left
pointing at a status that no longer exists.
"""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import (
    RESERVED_STATUS_VALUES,
    CustomStatus,
    RecurringTask,
    ScheduledStatusChange,
    Todo,
    TodoStatus,
    utcnow,
)
from ..schemas import CustomStatusCreate, CustomStatusOut, CustomStatusUpdate
from ..security import get_current_user, new_id

router = APIRouter(prefix="/api/statuses", tags=["statuses"])


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return slug[:30] or "status"


def _unique_value(db: DBSession, owner_id: str, label: str) -> str:
    """Slugify ``label`` into a value that collides with neither a built-in nor
    any of the owner's existing custom statuses (suffixing _2, _3, … if needed)."""
    base = _slugify(label)
    taken = {
        v for (v,) in db.query(CustomStatus.value).filter(CustomStatus.owner_id == owner_id)
    }
    candidate, n = base, 2
    while candidate in RESERVED_STATUS_VALUES or candidate in taken:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


@router.get("", response_model=list[CustomStatusOut])
def list_statuses(db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    return (
        db.query(CustomStatus)
        .filter(CustomStatus.owner_id == user.id)
        .order_by(CustomStatus.position, CustomStatus.created_at)
        .all()
    )


@router.post("", response_model=CustomStatusOut, status_code=201)
def create_status(
    payload: CustomStatusCreate, db: DBSession = Depends(get_db), user=Depends(get_current_user)
):
    cs = CustomStatus(
        id=new_id(),
        owner_id=user.id,
        value=_unique_value(db, user.id, payload.label),
        label=payload.label.strip(),
        color=payload.color or "grey",
        icon=(payload.icon or "").strip() or "circle",
        position=payload.position,
    )
    db.add(cs)
    db.commit()
    db.refresh(cs)
    return cs


@router.patch("/{status_id}", response_model=CustomStatusOut)
def update_status(
    status_id: str,
    payload: CustomStatusUpdate,
    db: DBSession = Depends(get_db),
    user=Depends(get_current_user),
):
    cs = db.get(CustomStatus, status_id)
    if cs is None or cs.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Status not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("label"):
        cs.label = data["label"].strip()
    if data.get("color"):
        cs.color = data["color"]
    if data.get("icon"):
        cs.icon = data["icon"].strip()
    if data.get("position") is not None:
        cs.position = data["position"]
    cs.updated_at = utcnow()
    db.commit()
    db.refresh(cs)
    return cs


@router.delete("/{status_id}")
def delete_status(status_id: str, db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    cs = db.get(CustomStatus, status_id)
    if cs is None or cs.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Status not found")

    fallback = TodoStatus.open.value
    now = utcnow()
    # Reassign anything still pointing at this status back to the backlog. Bump
    # todos' updated_at so the change propagates to clients on the next sync pull.
    for todo in (
        db.query(Todo).filter(Todo.owner_id == user.id, Todo.status == cs.value).all()
    ):
        todo.status = fallback
        todo.updated_at = now
    for rec in (
        db.query(RecurringTask)
        .filter(RecurringTask.owner_id == user.id, RecurringTask.status == cs.value)
        .all()
    ):
        rec.status = fallback
    (
        db.query(ScheduledStatusChange)
        .filter(
            ScheduledStatusChange.target_status == cs.value,
            ScheduledStatusChange.applied.is_(False),
            ScheduledStatusChange.todo_id.in_(
                db.query(Todo.id).filter(Todo.owner_id == user.id)
            ),
        )
        .update({ScheduledStatusChange.target_status: fallback}, synchronize_session=False)
    )

    db.delete(cs)
    db.commit()
    return {"ok": True}
