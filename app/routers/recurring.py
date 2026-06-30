"""Recurring tasks ("Automation").

Owner-scoped templates that the background scheduler turns into real todos on a
daily/weekly/monthly/yearly cadence. Managed online (not part of offline sync);
the todos they spawn sync to clients normally.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models import RecurringTask, RepeatFreq, utcnow
from ..recurrence import compute_next_run
from ..schemas import RecurringTaskCreate, RecurringTaskOut, RecurringTaskUpdate
from ..security import get_current_user, new_id
from ..services import get_owned_bucket, valid_status

router = APIRouter(prefix="/api/recurring", tags=["recurring"])

_FREQUENCIES = {f.value for f in RepeatFreq}


def _validate_cadence(freq: str, dow: int | None, dom: int | None, moy: int | None) -> tuple:
    """Validate the frequency + the field it needs, returning normalized
    (day_of_week, day_of_month, month_of_year) with irrelevant fields nulled out."""
    if freq not in _FREQUENCIES:
        raise HTTPException(status_code=422, detail=f"Invalid frequency: {freq}")
    if freq == RepeatFreq.weekly.value:
        if dow is None:
            raise HTTPException(status_code=422, detail="Pick a weekday")
        return dow, None, None
    if freq == RepeatFreq.monthly.value:
        if dom is None:
            raise HTTPException(status_code=422, detail="Pick a day of the month")
        return None, dom, None
    if freq == RepeatFreq.yearly.value:
        if dom is None or moy is None:
            raise HTTPException(status_code=422, detail="Pick a month and day")
        return None, dom, moy
    return None, None, None  # daily


@router.get("", response_model=list[RecurringTaskOut])
def list_recurring(db: DBSession = Depends(get_db), user=Depends(get_current_user)):
    return (
        db.query(RecurringTask)
        .filter(RecurringTask.owner_id == user.id)
        .order_by(RecurringTask.created_at.desc())
        .all()
    )


@router.post("", response_model=RecurringTaskOut, status_code=201)
def create_recurring(
    payload: RecurringTaskCreate, db: DBSession = Depends(get_db), user=Depends(get_current_user)
):
    valid_status(payload.status)
    get_owned_bucket(db, payload.bucket_id, user)
    dow, dom, moy = _validate_cadence(
        payload.frequency, payload.day_of_week, payload.day_of_month, payload.month_of_year
    )
    rec = RecurringTask(
        id=new_id(),
        owner_id=user.id,
        title=payload.title,
        text=payload.text,
        status=payload.status,
        bucket_id=payload.bucket_id,
        watcher_email=(payload.watcher_email or None),
        frequency=payload.frequency,
        day_of_week=dow,
        day_of_month=dom,
        month_of_year=moy,
        active=payload.active,
        next_run=compute_next_run(payload.frequency, dow, dom, moy, user.timezone, utcnow()),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.patch("/{recurring_id}", response_model=RecurringTaskOut)
def update_recurring(
    recurring_id: str,
    payload: RecurringTaskUpdate,
    db: DBSession = Depends(get_db),
    user=Depends(get_current_user),
):
    rec = db.get(RecurringTask, recurring_id)
    if rec is None or rec.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Recurring task not found")

    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        valid_status(data["status"])
    if "bucket_id" in data and data["bucket_id"] is not None:
        get_owned_bucket(db, data["bucket_id"], user)
    if "watcher_email" in data:
        data["watcher_email"] = data["watcher_email"] or None

    # Re-validate the cadence whenever any cadence field is touched, and recompute
    # the next fire time so the change takes effect.
    cadence_fields = {"frequency", "day_of_week", "day_of_month", "month_of_year"}
    if cadence_fields & data.keys():
        freq = data.get("frequency", rec.frequency)
        dow = data.get("day_of_week", rec.day_of_week)
        dom = data.get("day_of_month", rec.day_of_month)
        moy = data.get("month_of_year", rec.month_of_year)
        dow, dom, moy = _validate_cadence(freq, dow, dom, moy)
        data["frequency"], data["day_of_week"], data["day_of_month"], data["month_of_year"] = (
            freq, dow, dom, moy,
        )

    for field, value in data.items():
        setattr(rec, field, value)
    rec.next_run = compute_next_run(
        rec.frequency, rec.day_of_week, rec.day_of_month, rec.month_of_year,
        user.timezone, utcnow(),
    )
    rec.updated_at = utcnow()
    db.commit()
    db.refresh(rec)
    return rec


@router.delete("/{recurring_id}")
def delete_recurring(
    recurring_id: str, db: DBSession = Depends(get_db), user=Depends(get_current_user)
):
    rec = db.get(RecurringTask, recurring_id)
    if rec is None or rec.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Recurring task not found")
    db.delete(rec)
    db.commit()
    return {"ok": True}
