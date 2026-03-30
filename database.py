import sqlite3
from datetime import datetime
from typing import Optional

DB_PATH = "tasks.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                title       TEXT NOT NULL,
                priority    TEXT NOT NULL DEFAULT 'medium',
                deadline    TEXT,
                done        INTEGER NOT NULL DEFAULT 0,
                notified    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            )
        """)
        conn.commit()


def add_task(user_id: int, title: str, priority: str, deadline: Optional[str]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (user_id, title, priority, deadline, created_at) VALUES (?,?,?,?,?)",
            (user_id, title, priority, deadline, datetime.now().isoformat()),
        )
        conn.commit()
        return cur.lastrowid


def get_tasks(user_id: int, done: Optional[bool] = None):
    with get_conn() as conn:
        if done is None:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id=? ORDER BY done, deadline NULLS LAST, priority DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id=? AND done=? ORDER BY deadline NULLS LAST",
                (user_id, int(done)),
            ).fetchall()
        return [dict(r) for r in rows]


def get_task(task_id: int, user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def mark_done(task_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tasks SET done=1 WHERE id=? AND user_id=? AND done=0",
            (task_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_task(task_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0


def get_tasks_due_soon():
    """Return active tasks with deadline within the next 24 hours (not yet notified)."""
    with get_conn() as conn:
        now = datetime.now()
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE done=0
              AND notified=0
              AND deadline IS NOT NULL
              AND deadline <= ?
            """,
            (now.strftime("%Y-%m-%d 23:59"),),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_notified(task_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET notified=1 WHERE id=?", (task_id,))
        conn.commit()
