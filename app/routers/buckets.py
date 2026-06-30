from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import STATUS_LABELS, Bucket, Event, EventType, Todo, TodoStatus, utcnow
from ..schemas import BucketCreate, BucketOut, BucketUpdate
from ..security import get_current_user, new_id
from ..services import get_owned_bucket, record_event, touch

router = APIRouter(prefix="/api/buckets", tags=["buckets"])


@router.get("", response_model=list[BucketOut])
def list_buckets(db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    return (
        db.query(Bucket)
        .filter(Bucket.owner_id == user.id, Bucket.deleted.is_(False))
        .order_by(Bucket.position, Bucket.created_at)
        .all()
    )


@router.post("", response_model=BucketOut, status_code=201)
def create_bucket(payload: BucketCreate, db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    bucket = Bucket(
        id=payload.id or new_id(),
        owner_id=user.id,
        name=payload.name,
        color=payload.color,
        position=payload.position,
    )
    db.add(bucket)
    db.commit()
    db.refresh(bucket)
    return bucket


@router.patch("/{bucket_id}", response_model=BucketOut)
def update_bucket(
    bucket_id: str, payload: BucketUpdate, db: DBSession = Depends(get_db), user=Depends(get_current_user)
):
    bucket = get_owned_bucket(db, bucket_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(bucket, field, value)
    touch(bucket)
    db.commit()
    db.refresh(bucket)
    return bucket


@router.delete("/{bucket_id}")
def delete_bucket(bucket_id: str, db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    bucket = get_owned_bucket(db, bucket_id, user)
    open_todos = (
        db.query(Todo).filter(Todo.bucket_id == bucket_id, Todo.deleted.is_(False)).count()
    )
    if open_todos:
        raise HTTPException(status_code=400, detail="Bucket is not empty")
    bucket.deleted = True
    touch(bucket)
    db.commit()
    return {"ok": True}


@router.post("/{bucket_id}/archive", response_model=BucketOut)
def archive_bucket(bucket_id: str, db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    """Archive a bucket: mark every task in it done and hide the bucket by default."""
    bucket = get_owned_bucket(db, bucket_id, user)
    bucket.archived = True
    touch(bucket)
    tasks = (
        db.query(Todo)
        .filter(Todo.bucket_id == bucket_id, Todo.deleted.is_(False), Todo.status != TodoStatus.done.value)
        .all()
    )
    for t in tasks:
        old = t.status
        t.status = TodoStatus.done.value
        t.completed_at = utcnow()
        record_event(
            db, t, EventType.status_changed,
            body=f"Status: {STATUS_LABELS.get(old, old)} → Done (bucket archived)",
            actor_email=user.email, meta={"from": old, "to": TodoStatus.done.value},
        )
        touch(t)
    db.commit()
    db.refresh(bucket)
    return bucket


@router.post("/{bucket_id}/unarchive", response_model=BucketOut)
def unarchive_bucket(bucket_id: str, db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    bucket = get_owned_bucket(db, bucket_id, user)
    bucket.archived = False
    touch(bucket)
    db.commit()
    db.refresh(bucket)
    return bucket


@router.post("/{bucket_id}/duplicate", response_model=BucketOut, status_code=201)
def duplicate_bucket(bucket_id: str, db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    """Copy a bucket and all its tasks (preserving the subtask hierarchy)."""
    src = get_owned_bucket(db, bucket_id, user)
    new_bucket = Bucket(
        id=new_id(), owner_id=user.id, name=f"{src.name} (copy)",
        color=src.color, position=src.position + 1,
    )
    db.add(new_bucket)

    tasks = (
        db.query(Todo)
        .filter(Todo.bucket_id == bucket_id, Todo.deleted.is_(False))
        .order_by(Todo.created_at)
        .all()
    )
    id_map = {t.id: new_id() for t in tasks}
    for t in tasks:
        clone = Todo(
            id=id_map[t.id],
            bucket_id=new_bucket.id,
            parent_id=id_map.get(t.parent_id),  # remap to the cloned parent
            owner_id=user.id,
            title=t.title,
            text=t.text,
            status=t.status,
            position=t.position,
            completed_at=t.completed_at,
            public_token=new_id().replace("-", ""),
        )
        db.add(clone)
        db.add(Event(id=new_id(), todo_id=clone.id, type=EventType.created.value,
                     body="Created task (duplicated)", actor_email=user.email))
    db.commit()
    db.refresh(new_bucket)
    return new_bucket
