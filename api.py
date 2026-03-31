from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Optional
from urllib.parse import parse_qsl, unquote

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")


def get_user_id(request: Request) -> int:
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        raise HTTPException(401, "No init data")
    try:
        parsed = dict(parse_qsl(unquote(init_data), keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            raise ValueError("No hash")
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            raise ValueError("Hash mismatch")
        user = json.loads(parsed.get("user", "{}"))
        return int(user["id"])
    except Exception as e:
        raise HTTPException(401, str(e))


app = FastAPI()
db.init_db()


class TaskCreate(BaseModel):
    title: str
    priority: str = "medium"
    category: str = "Другое"
    deadline: Optional[str] = None
    deadline_time: Optional[str] = None
    notes: Optional[str] = None
    repeat: str = "none"
    remind_at: Optional[str] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    deadline: Optional[str] = None
    deadline_time: Optional[str] = None
    notes: Optional[str] = None
    repeat: Optional[str] = None
    remind_at: Optional[str] = None
    done: Optional[bool] = None

class SettingsUpdate(BaseModel):
    notify_times: Optional[str] = None
    notify_days_before: Optional[int] = None
    sort_by: Optional[str] = None


@app.get("/api/tasks")
def get_tasks(user_id: int = Depends(get_user_id)):
    s = db.get_settings(user_id)
    return db.get_tasks(user_id, sort_by=s.get("sort_by", "priority"))

@app.post("/api/tasks", status_code=201)
def create_task(body: TaskCreate, user_id: int = Depends(get_user_id)):
    task_id = db.add_task(
        user_id, body.title, body.priority, body.category,
        body.deadline, body.notes, body.repeat,
        deadline_time=body.deadline_time, remind_at=body.remind_at,
    )
    return db.get_task(task_id, user_id)

@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate, user_id: int = Depends(get_user_id)):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not db.update_task(task_id, user_id, **updates):
        raise HTTPException(404, "Task not found")
    return db.get_task(task_id, user_id)

@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, user_id: int = Depends(get_user_id)):
    if not db.delete_task(task_id, user_id):
        raise HTTPException(404, "Task not found")

@app.post("/api/tasks/{task_id}/done")
def mark_done(task_id: int, user_id: int = Depends(get_user_id)):
    task = db.mark_done(task_id, user_id)
    if not task:
        raise HTTPException(404, "Task not found or already done")
    new_ach = db.check_achievements(user_id)
    return {"task": task, "new_achievements": new_ach}

@app.post("/api/tasks/{task_id}/undone")
def mark_undone(task_id: int, user_id: int = Depends(get_user_id)):
    if not db.undone_task(task_id, user_id):
        raise HTTPException(404, "Task not found")
    return {"ok": True}

@app.get("/api/stats")
def get_stats(user_id: int = Depends(get_user_id)):
    return db.get_stats(user_id)

@app.get("/api/achievements")
def get_achievements(user_id: int = Depends(get_user_id)):
    db.check_achievements(user_id)
    unlocked = set(db.get_achievements(user_id))
    return [
        {"key": k, "emoji": e, "name": n, "desc": d, "unlocked": k in unlocked}
        for k, (e, n, d) in db.ACHIEVEMENTS.items()
    ]

@app.get("/api/settings")
def get_settings_api(user_id: int = Depends(get_user_id)):
    return db.get_settings(user_id)

@app.put("/api/settings")
def update_settings_api(body: SettingsUpdate, user_id: int = Depends(get_user_id)):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    db.update_settings(user_id, **updates)
    return db.get_settings(user_id)


# Static assets (must be mounted BEFORE the catch-all /app route)
_assets_dir = os.path.join(FRONTEND_DIST, "assets")
if os.path.isdir(_assets_dir):
    app.mount("/app/assets", StaticFiles(directory=_assets_dir), name="assets")

# Serve built frontend (catch-all — must come AFTER static mounts)
@app.get("/app/{full_path:path}")
async def serve_app(full_path: str = ""):
    index = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "Frontend not built. Run: cd frontend && npm install && npm run build"}

@app.get("/app")
async def serve_app_root():
    return await serve_app("")
