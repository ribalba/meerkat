"""External create-task API.

A single token-authenticated endpoint so other tools (cron, shortcuts, curl) can
drop a task into a user's account without a session cookie. The token (see the
"API" page in the app) is passed as the ``token`` query parameter and identifies
the owner; the created task syncs to the user's devices on the next pull.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import Bucket, EventType, Todo
from ..schemas import ApiTaskCreate, TodoOut
from ..security import get_user_by_api_token, new_id
from ..services import attach_to_todo, record_event, valid_status

router = APIRouter(prefix="/api", tags=["external"])


@router.post("/create", response_model=TodoOut, status_code=201)
def api_create_todo(
    payload: ApiTaskCreate,
    token: str = Query(..., description="Your API token (see the API page in the app)"),
    db: DBSession = Depends(get_db),
):
    user = get_user_by_api_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid API token")

    valid_status(db, user.id, payload.status)

    # Pick the target bucket: the one supplied (must be the caller's), else their
    # first non-archived bucket.
    if payload.bucket_id:
        bucket = db.get(Bucket, payload.bucket_id)
        if bucket is None or bucket.deleted or bucket.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Bucket not found")
    else:
        bucket = (
            db.query(Bucket)
            .filter(Bucket.owner_id == user.id, Bucket.deleted.is_(False), Bucket.archived.is_(False))
            .order_by(Bucket.position, Bucket.created_at)
            .first()
        )
        if bucket is None:
            raise HTTPException(status_code=400, detail="No bucket to add the task to")

    todo = Todo(
        id=new_id(),
        bucket_id=bucket.id,
        owner_id=user.id,
        title=payload.title,
        text=payload.text or "",
        status=payload.status,
        position=0,
        public_token=new_id().replace("-", ""),
    )
    db.add(todo)
    record_event(db, todo, EventType.created, body="Created task (API)", actor_email=user.email)
    db.commit()
    db.refresh(todo)
    return attach_to_todo(db, todo)
