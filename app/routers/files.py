from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DBSession

from ..config import get_settings
from ..database import get_db
from ..models import Attachment, Event, EventType, Todo, Watcher
from ..schemas import AttachmentOut
from ..security import get_current_user, get_optional_user, new_id
from ..services import (
    display_name,
    get_owned_todo,
    notify_watchers,
    record_event,
    store_upload,
    touch,
)

router = APIRouter(prefix="/api/attachments", tags=["attachments"])
settings = get_settings()


def _resolve_todo_for_owner(db: DBSession, owner_type: str, owner_id: str) -> Todo:
    if owner_type == "todo":
        return db.get(Todo, owner_id)
    if owner_type == "event":
        event = db.get(Event, owner_id)
        return db.get(Todo, event.todo_id) if event else None
    raise HTTPException(status_code=422, detail="owner_type must be 'todo' or 'event'")


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    owner_type: str = Query(...),
    owner_id: str = Query(...),
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
    user=Depends(get_current_user),
):
    todo = _resolve_todo_for_owner(db, owner_type, owner_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="Attachment target not found")
    get_owned_todo(db, todo.id, user)  # access check

    data = await file.read()
    stored_name = store_upload(file.filename, data)

    attachment = Attachment(
        id=new_id(),
        owner_type=owner_type,
        owner_id=owner_id,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        content_type=file.content_type,
        size=len(data),
    )
    db.add(attachment)
    if owner_type == "todo":
        record_event(
            db, todo, EventType.file_added, body=f"Attached {attachment.filename}", actor_email=user.email
        )
        notify_watchers(
            db, todo, f"{display_name(user)} attached a file: {attachment.filename}.",
            exclude_email=user.email,
        )
        touch(todo)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/{attachment_id}")
def download_attachment(
    attachment_id: str,
    token: str | None = Query(default=None),  # public share token of the owning todo
    db: DBSession = Depends(get_db),
    user=Depends(get_optional_user),
):
    """Download a file, authorized either via a matching public share token or the
    session of a user who owns/watches the owning todo."""
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Not found")

    todo = _resolve_todo_for_owner(db, attachment.owner_type, attachment.owner_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="Not found")

    public_ok = bool(token and token == todo.public_token)
    if not public_ok and not _has_session_access(db, todo, user):
        raise HTTPException(status_code=403, detail="Not allowed")

    path = settings.upload_dir / attachment.stored_name
    if not path.exists():
        raise HTTPException(status_code=410, detail="File no longer available")
    return FileResponse(path, filename=attachment.filename, media_type=attachment.content_type)


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: str, db: DBSession = Depends(get_db), user=Depends(get_current_user)
):
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Not found")
    todo = _resolve_todo_for_owner(db, attachment.owner_type, attachment.owner_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="Not found")
    get_owned_todo(db, todo.id, user)  # access check

    (settings.upload_dir / attachment.stored_name).unlink(missing_ok=True)
    db.delete(attachment)
    if attachment.owner_type == "todo":
        record_event(
            db, todo, EventType.file_removed,
            body=f"Removed {attachment.filename}", actor_email=user.email,
        )
        touch(todo)
        notify_watchers(db, todo, f"A file was removed: {attachment.filename}.", exclude_email=user.email)
    db.commit()
    return {"ok": True}


def _has_session_access(db: DBSession, todo: Todo, user) -> bool:
    if user is None:
        return False
    if todo.owner_id == user.id:
        return True
    return (
        db.query(Watcher)
        .filter(Watcher.todo_id == todo.id, Watcher.email == user.email)
        .first()
        is not None
    )
