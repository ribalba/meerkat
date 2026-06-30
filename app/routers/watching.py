"""Tasks shared with the current user, linked by their email address.

A user "watches" a task when their email is on its watcher list (added by the
task's owner, or self-added via the public "View in the app" flow). These tasks
are owned by someone else, so they don't come down through offline sync; the app
fetches them online for the Watching page.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import Bucket, EventType, Todo, User, Watcher
from ..schemas import CommentCreate, EventOut, WatchedTaskOut
from ..security import get_current_user
from ..services import (
    attach_to_event,
    display_name,
    get_public_todo,
    notify_watchers,
    record_event,
    touch,
)

router = APIRouter(prefix="/api/watching", tags=["watching"])


def _watched_todo(db: DBSession, token: str, user) -> Todo:
    """Resolve a shared task by token, requiring the user to own or watch it."""
    todo = get_public_todo(db, token)
    if todo.owner_id != user.id:
        watches = (
            db.query(Watcher)
            .filter(Watcher.todo_id == todo.id, Watcher.email == user.email.lower())
            .first()
        )
        if watches is None:
            raise HTTPException(status_code=403, detail="You are not watching this task")
    return todo


@router.get("", response_model=list[WatchedTaskOut])
def list_watching(db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(Todo, Bucket, User)
        .join(Watcher, Watcher.todo_id == Todo.id)
        .join(Bucket, Bucket.id == Todo.bucket_id)
        .join(User, User.id == Todo.owner_id)
        .filter(
            Watcher.email == user.email.lower(),
            Todo.deleted.is_(False),
            Todo.owner_id != user.id,  # tasks I own already appear in my normal list
        )
        .order_by(Todo.updated_at.desc())
        .all()
    )
    return [
        WatchedTaskOut(
            id=todo.id,
            title=todo.title,
            status=todo.status,
            public_token=todo.public_token,
            bucket_name=bucket.name,
            owner_name=display_name(owner),
            updated_at=todo.updated_at,
        )
        for todo, bucket, owner in rows
    ]


@router.post("/{token}/comments", response_model=EventOut, status_code=201)
def comment_on_watched(
    token: str,
    payload: CommentCreate,
    db: DBSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Add a comment to a task shared with me, attributed to my account."""
    todo = _watched_todo(db, token, user)
    event = record_event(db, todo, EventType.comment, body=payload.body, actor_email=user.email)
    touch(todo)
    notify_watchers(db, todo, f"{display_name(user)} commented.", exclude_email=user.email)
    db.commit()
    db.refresh(event)
    return attach_to_event(db, event)
