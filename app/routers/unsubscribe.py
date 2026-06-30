"""One-click email unsubscribe for task watchers.

A watcher's invite/update emails carry a link to ``/unsubscribe/{token}`` where the
token is the watcher's unguessable ``unsubscribe_token``. The GET shows a small
confirmation page (so an email client prefetching the link can't unsubscribe the
recipient by accident); the POST actually stops the watch.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..emailer import APP_NAME
from ..models import Watcher

router = APIRouter(tags=["unsubscribe"])


def _page(title: str, body_html: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{APP_NAME} · {title}</title>
  <style>
    body {{ margin:0; min-height:100vh; display:flex; align-items:center;
            justify-content:center; background:#f4f5f7; color:#1f2328;
            font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",
            Helvetica,Arial,sans-serif; line-height:1.55; }}
    .card {{ background:#fff; border:1px solid #e6e8eb; border-radius:12px;
             box-shadow:0 1px 3px rgba(27,31,36,.06); padding:2rem;
             max-width:440px; width:calc(100% - 2rem); text-align:center; }}
    h1 {{ font-size:1.4rem; margin:0 0 .6rem; }}
    p {{ color:#57606a; margin:0 0 1rem; }}
    .task {{ font-weight:600; color:#1f2328; }}
    button {{ font:inherit; font-weight:600; cursor:pointer; border:none;
              border-radius:8px; padding:.7rem 1.3rem; background:#2185d0;
              color:#fff; }}
    button:hover {{ background:#1a6fb0; }}
    .brand {{ margin-top:1.5rem; color:#8c959f; font-size:.85rem; }}
    .brand a {{ color:#2185d0; text-decoration:none; }}
  </style>
</head>
<body>
  <div class="card">
    {body_html}
    <div class="brand">{APP_NAME} · <a href="https://meerato.com">meerato.com</a></div>
  </div>
</body>
</html>""",
    )


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_confirm(token: str, db: DBSession = Depends(get_db)) -> HTMLResponse:
    watcher = db.query(Watcher).filter(Watcher.unsubscribe_token == token).one_or_none()
    if watcher is None:
        return _page(
            "Already unsubscribed",
            "<h1>You're all set</h1><p>You're no longer receiving updates for this task.</p>",
        )
    title = watcher.todo.title if watcher.todo else "this task"
    return _page(
        "Unsubscribe",
        f"""
        <h1>Stop watching this task?</h1>
        <p>You'll no longer get any email updates about
           <span class="task">"{title}"</span>.</p>
        <form method="post" action="/unsubscribe/{token}">
          <button type="submit">Unsubscribe me</button>
        </form>
        """,
    )


@router.post("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, db: DBSession = Depends(get_db)) -> HTMLResponse:
    watcher = db.query(Watcher).filter(Watcher.unsubscribe_token == token).one_or_none()
    if watcher is not None:
        db.delete(watcher)
        db.commit()
    return _page(
        "Unsubscribed",
        "<h1>You've been unsubscribed</h1>"
        "<p>You won't receive any more email updates about this task. "
        "You can close this tab.</p>",
    )
