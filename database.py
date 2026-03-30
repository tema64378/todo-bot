from __future__ import annotations

import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional, List

DB_PATH = "tasks.db"
CATEGORIES = ["Работа", "Личное", "Учёба", "Здоровье", "Финансы", "Другое"]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_col(conn, table, col, definition):
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
    except Exception:
        pass


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER NOT NULL,
                title        TEXT NOT NULL,
                priority     TEXT NOT NULL DEFAULT 'medium',
                category     TEXT NOT NULL DEFAULT 'Другое',
                deadline     TEXT,
                notes        TEXT,
                repeat       TEXT NOT NULL DEFAULT 'none',
                done         INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                created_at   TEXT NOT NULL
            )
        """)
        for col, defn in [
            ("category",     "TEXT NOT NULL DEFAULT 'Другое'"),
            ("notes",        "TEXT"),
            ("repeat",       "TEXT NOT NULL DEFAULT 'none'"),
            ("completed_at", "TEXT"),
        ]:
            _add_col(conn, "tasks", col, defn)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS subtasks (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                title   TEXT NOT NULL,
                done    INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id      INTEGER PRIMARY KEY,
                notify_times TEXT NOT NULL DEFAULT '09:00,21:00'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notify_log (
                user_id  INTEGER NOT NULL,
                log_date TEXT NOT NULL,
                log_time TEXT NOT NULL,
                PRIMARY KEY (user_id, log_date, log_time)
            )
        """)
        conn.commit()


# ── Settings ──────────────────────────────────────────────────

def get_settings(user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_settings WHERE user_id=?", (user_id,)
        ).fetchone()
        if row:
            return dict(row)
        conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return {"user_id": user_id, "notify_times": "09:00,21:00"}


def update_notify_times(user_id: int, times: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO user_settings (user_id, notify_times) VALUES (?,?)
            ON CONFLICT(user_id) DO UPDATE SET notify_times=excluded.notify_times
        """, (user_id, times))
        conn.commit()


def get_all_active_user_ids() -> List[int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM tasks WHERE done=0"
        ).fetchall()
        return [r[0] for r in rows]


# ── Notify log ────────────────────────────────────────────────

def was_notified(user_id: int, log_time: str) -> bool:
    today = date.today().isoformat()
    with get_conn() as conn:
        return bool(conn.execute(
            "SELECT 1 FROM notify_log WHERE user_id=? AND log_date=? AND log_time=?",
            (user_id, today, log_time)
        ).fetchone())


def log_notification(user_id: int, log_time: str):
    today = date.today().isoformat()
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO notify_log (user_id, log_date, log_time) VALUES (?,?,?)",
                (user_id, today, log_time)
            )
            conn.commit()
        except Exception:
            pass


def cleanup_old_logs():
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM notify_log WHERE log_date < ?", (week_ago,))
        conn.commit()


# ── Tasks ─────────────────────────────────────────────────────

def add_task(user_id: int, title: str, priority: str, category: str,
             deadline: Optional[str], notes: Optional[str], repeat: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tasks
               (user_id, title, priority, category, deadline, notes, repeat, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (user_id, title, priority, category, deadline, notes, repeat,
             datetime.now().isoformat()),
        )
        conn.commit()
        return cur.lastrowid


def get_tasks(user_id: int, done: Optional[bool] = None,
              category: Optional[str] = None) -> List[dict]:
    with get_conn() as conn:
        q = "SELECT * FROM tasks WHERE user_id=?"
        p: list = [user_id]
        if done is not None:
            q += " AND done=?"
            p.append(int(done))
        if category:
            q += " AND category=?"
            p.append(category)
        q += (" ORDER BY done,"
              " CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,"
              " deadline NULLS LAST")
        return [dict(r) for r in conn.execute(q, p).fetchall()]


def get_task(task_id: int, user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def update_task(task_id: int, user_id: int, **kwargs) -> bool:
    if not kwargs:
        return False
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [task_id, user_id]
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE tasks SET {sets} WHERE id=? AND user_id=?", vals
        )
        conn.commit()
        return cur.rowcount > 0


def mark_done(task_id: int, user_id: int) -> Optional[dict]:
    task = get_task(task_id, user_id)
    if not task or task["done"]:
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET done=1, completed_at=? WHERE id=? AND user_id=?",
            (datetime.now().isoformat(), task_id, user_id),
        )
        conn.commit()
    if task["repeat"] != "none" and task["deadline"]:
        _create_repeat(task)
    return task


def _create_repeat(task: dict):
    dl = datetime.strptime(task["deadline"], "%Y-%m-%d").date()
    if task["repeat"] == "daily":
        next_dl = dl + timedelta(days=1)
    elif task["repeat"] == "weekly":
        next_dl = dl + timedelta(weeks=1)
    elif task["repeat"] == "monthly":
        m = dl.month % 12 + 1
        y = dl.year + (1 if dl.month == 12 else 0)
        next_dl = dl.replace(year=y, month=m)
    else:
        return
    add_task(task["user_id"], task["title"], task["priority"], task["category"],
             next_dl.strftime("%Y-%m-%d"), task["notes"], task["repeat"])


def delete_task(task_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0


def search_tasks(user_id: int, query: str) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM tasks WHERE user_id=? AND done=0
               AND (title LIKE ? OR notes LIKE ?)
               ORDER BY deadline NULLS LAST""",
            (user_id, f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Subtasks ──────────────────────────────────────────────────

def add_subtask(task_id: int, title: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO subtasks (task_id, title) VALUES (?,?)", (task_id, title)
        )
        conn.commit()
        return cur.lastrowid


def get_subtasks(task_id: int) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subtasks WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def toggle_subtask(subtask_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT done FROM subtasks WHERE id=?", (subtask_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE subtasks SET done=? WHERE id=?", (1 - row[0], subtask_id)
        )
        conn.commit()
        return True


def delete_subtask(subtask_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM subtasks WHERE id=?", (subtask_id,))
        conn.commit()
        return cur.rowcount > 0


# ── Notifications ─────────────────────────────────────────────

def get_tasks_to_notify(user_id: int) -> dict:
    today_str = date.today().isoformat()
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
    active = get_tasks(user_id, done=False)
    result: dict = {"overdue": [], "today": [], "tomorrow": []}
    for t in active:
        if not t["deadline"]:
            continue
        if t["deadline"] < today_str:
            result["overdue"].append(t)
        elif t["deadline"] == today_str:
            result["today"].append(t)
        elif t["deadline"] == tomorrow_str:
            result["tomorrow"].append(t)
    return result


# ── Stats ─────────────────────────────────────────────────────

def get_stats(user_id: int) -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        done_all = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1", (user_id,)
        ).fetchone()[0]
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        done_week = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND completed_at>=?",
            (user_id, week_ago),
        ).fetchone()[0]
        month_ago = (date.today() - timedelta(days=30)).isoformat()
        done_month = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND completed_at>=?",
            (user_id, month_ago),
        ).fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0", (user_id,)
        ).fetchone()[0]
        overdue = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0 AND deadline<?",
            (user_id, date.today().isoformat()),
        ).fetchone()[0]

        # Streak: consecutive days with at least one completion
        rows = conn.execute(
            """SELECT DATE(completed_at) as day FROM tasks
               WHERE user_id=? AND done=1 AND completed_at IS NOT NULL
               GROUP BY day ORDER BY day DESC""",
            (user_id,),
        ).fetchall()
        streak = 0
        check = date.today()
        for row in rows:
            d = date.fromisoformat(row[0])
            if d >= check - timedelta(days=1):
                streak += 1
                check = d
            else:
                break

        return {
            "total": total, "active": active, "done_all": done_all,
            "done_week": done_week, "done_month": done_month,
            "overdue": overdue, "streak": streak,
        }


def get_categories_stats(user_id: int) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT category,
               COUNT(*) as total,
               SUM(CASE WHEN done=0 THEN 1 ELSE 0 END) as active
               FROM tasks WHERE user_id=?
               GROUP BY category ORDER BY active DESC""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_tasks_csv(user_id: int) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
