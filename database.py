from __future__ import annotations

import re
import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional, List

DB_PATH = "tasks.db"
CATEGORIES = ["Работа", "Личное", "Учёба", "Здоровье", "Финансы", "Другое"]

ACHIEVEMENTS = {
    "first_task":  ("🌱", "Первая задача",        "Создал первую задачу"),
    "done_10":     ("🥉", "10 задач выполнено",    "Выполнил 10 задач"),
    "done_50":     ("🥈", "50 задач выполнено",    "Выполнил 50 задач"),
    "done_100":    ("🥇", "100 задач выполнено",   "Выполнил 100 задач"),
    "streak_7":    ("🔥", "Неделя без остановки",  "Стрик 7 дней подряд"),
    "streak_30":   ("💎", "Месяц без остановки",   "Стрик 30 дней подряд"),
    "early_bird":  ("⚡", "Сделал заранее",        "Выполнил задачу раньше дедлайна"),
}


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
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                title           TEXT NOT NULL,
                priority        TEXT NOT NULL DEFAULT 'medium',
                category        TEXT NOT NULL DEFAULT 'Другое',
                tags            TEXT,
                deadline        TEXT,
                notes           TEXT,
                repeat          TEXT NOT NULL DEFAULT 'none',
                done            INTEGER NOT NULL DEFAULT 0,
                completed_at    TEXT,
                created_at      TEXT NOT NULL
            )
        """)
        for col, defn in [
            ("category",     "TEXT NOT NULL DEFAULT 'Другое'"),
            ("tags",         "TEXT"),
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
                user_id            INTEGER PRIMARY KEY,
                notify_times       TEXT NOT NULL DEFAULT '09:00,21:00',
                notify_days_before INTEGER NOT NULL DEFAULT 1,
                sort_by            TEXT NOT NULL DEFAULT 'priority',
                best_streak        INTEGER NOT NULL DEFAULT 0
            )
        """)
        for col, defn in [
            ("notify_days_before", "INTEGER NOT NULL DEFAULT 1"),
            ("sort_by",            "TEXT NOT NULL DEFAULT 'priority'"),
            ("best_streak",        "INTEGER NOT NULL DEFAULT 0"),
        ]:
            _add_col(conn, "user_settings", col, defn)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notify_log (
                user_id  INTEGER NOT NULL,
                log_date TEXT NOT NULL,
                log_time TEXT NOT NULL,
                PRIMARY KEY (user_id, log_date, log_time)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER NOT NULL,
                name     TEXT NOT NULL,
                title    TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                category TEXT NOT NULL DEFAULT 'Другое',
                notes    TEXT,
                repeat   TEXT NOT NULL DEFAULT 'none',
                UNIQUE(user_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id     INTEGER NOT NULL,
                achievement TEXT NOT NULL,
                achieved_at TEXT NOT NULL,
                PRIMARY KEY (user_id, achievement)
            )
        """)
        conn.commit()


# ── Helpers ───────────────────────────────────────────────────

def extract_tags(title: str) -> str:
    tags = re.findall(r'#(\w+)', title)
    return ",".join(tags) if tags else ""


def parse_quick_add(text: str) -> tuple[str, str, Optional[str]]:
    """Parse 'Buy milk tomorrow high' → (title, priority, deadline)."""
    priority_map = {
        "высокий": "high", "высок": "high", "важно": "high", "срочно": "high",
        "high": "high", "низкий": "low", "низк": "low", "low": "low",
        "средний": "medium", "medium": "medium",
    }
    priority = "medium"
    deadline = None
    keep = []
    for word in text.split():
        w = word.lower().rstrip("!.,")
        if w in priority_map:
            priority = priority_map[w]
        elif w == "сегодня":
            deadline = date.today().strftime("%Y-%m-%d")
        elif w == "завтра":
            deadline = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        elif w == "послезавтра":
            deadline = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        else:
            try:
                deadline = datetime.strptime(word, "%d.%m.%Y").strftime("%Y-%m-%d")
            except ValueError:
                keep.append(word)
    title = " ".join(keep) or text
    return title, priority, deadline


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
        return {"user_id": user_id, "notify_times": "09:00,21:00",
                "notify_days_before": 1, "sort_by": "priority", "best_streak": 0}


def update_settings(user_id: int, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO user_settings (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING",
            (user_id,)
        )
        conn.execute(f"UPDATE user_settings SET {sets} WHERE user_id=?", vals)
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
                "INSERT INTO notify_log VALUES (?,?,?)", (user_id, today, log_time)
            )
            conn.commit()
        except Exception:
            pass


def cleanup_old_logs():
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM notify_log WHERE log_date<?", (week_ago,))
        conn.commit()


# ── Tasks ─────────────────────────────────────────────────────

def add_task(user_id: int, title: str, priority: str, category: str,
             deadline: Optional[str], notes: Optional[str], repeat: str) -> int:
    tags = extract_tags(title)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tasks
               (user_id, title, priority, category, tags, deadline, notes, repeat, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, title, priority, category, tags, deadline, notes, repeat,
             datetime.now().isoformat()),
        )
        conn.commit()
        return cur.lastrowid


def get_tasks(user_id: int, done: Optional[bool] = None,
              category: Optional[str] = None, sort_by: str = "priority") -> List[dict]:
    order = {
        "priority": ("CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,"
                     " deadline NULLS LAST"),
        "deadline": "deadline NULLS LAST, CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END",
        "created":  "created_at DESC",
    }.get(sort_by, "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END")
    with get_conn() as conn:
        q = "SELECT * FROM tasks WHERE user_id=?"
        p: list = [user_id]
        if done is not None:
            q += " AND done=?"
            p.append(int(done))
        if category:
            q += " AND category=?"
            p.append(category)
        q += f" ORDER BY done, {order}"
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
    if "title" in kwargs:
        kwargs["tags"] = extract_tags(kwargs["title"])
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


def undone_task(task_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tasks SET done=0, completed_at=NULL WHERE id=? AND user_id=? AND done=1",
            (task_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def copy_task(task_id: int, user_id: int) -> Optional[int]:
    task = get_task(task_id, user_id)
    if not task:
        return None
    return add_task(user_id, task["title"], task["priority"], task["category"],
                    task["deadline"], task["notes"], task["repeat"])


def snooze_task(task_id: int, user_id: int, days: int = 1) -> bool:
    task = get_task(task_id, user_id)
    if not task or task["done"]:
        return False
    if task["deadline"]:
        dl = datetime.strptime(task["deadline"], "%Y-%m-%d").date()
        new_dl = (dl + timedelta(days=days)).strftime("%Y-%m-%d")
    else:
        new_dl = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")
    return update_task(task_id, user_id, deadline=new_dl)


def snooze_overdue(user_id: int, days: int = 1):
    today = date.today().isoformat()
    tasks = [t for t in get_tasks(user_id, done=False)
             if t["deadline"] and t["deadline"] < today]
    for t in tasks:
        snooze_task(t["id"], user_id, days)
    return len(tasks)


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
               AND (title LIKE ? OR notes LIKE ? OR tags LIKE ?)
               ORDER BY deadline NULLS LAST""",
            (user_id, f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()
        return [dict(r) for r in rows]


def get_tasks_by_tag(user_id: int, tag: str) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE user_id=? AND done=0 AND tags LIKE ?",
            (user_id, f"%{tag}%"),
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
        return [dict(r) for r in conn.execute(
            "SELECT * FROM subtasks WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()]


def toggle_subtask(subtask_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT done FROM subtasks WHERE id=?", (subtask_id,)).fetchone()
        if not row:
            return False
        conn.execute("UPDATE subtasks SET done=? WHERE id=?", (1 - row[0], subtask_id))
        conn.commit()
        return True


def delete_subtask(subtask_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM subtasks WHERE id=?", (subtask_id,))
        conn.commit()
        return cur.rowcount > 0


# ── Templates ─────────────────────────────────────────────────

def save_template(user_id: int, name: str, task: dict) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO templates (user_id, name, title, priority, category, notes, repeat)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(user_id, name) DO UPDATE SET
                   title=excluded.title, priority=excluded.priority,
                   category=excluded.category, notes=excluded.notes, repeat=excluded.repeat""",
                (user_id, name, task["title"], task["priority"],
                 task.get("category", "Другое"), task.get("notes"), task.get("repeat", "none")),
            )
            conn.commit()
            return True
        except Exception:
            return False


def get_templates(user_id: int) -> List[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM templates WHERE user_id=? ORDER BY name", (user_id,)
        ).fetchall()]


def get_template(template_id: int, user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM templates WHERE id=? AND user_id=?", (template_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def delete_template(template_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM templates WHERE id=? AND user_id=?", (template_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0


# ── Achievements ──────────────────────────────────────────────

def get_achievements(user_id: int) -> List[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT achievement FROM achievements WHERE user_id=?", (user_id,)
        ).fetchall()
        return [r[0] for r in rows]


def award_achievement(user_id: int, key: str) -> bool:
    """Returns True if newly awarded."""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO achievements (user_id, achievement, achieved_at) VALUES (?,?,?)",
                (user_id, key, datetime.now().isoformat()),
            )
            conn.commit()
            return True
        except Exception:
            return False


def check_achievements(user_id: int) -> List[str]:
    """Check all achievements, return list of newly unlocked keys."""
    new_achievements = []
    existing = set(get_achievements(user_id))

    with get_conn() as conn:
        total_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        done_count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1", (user_id,)
        ).fetchone()[0]

        # Streak calc
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

        # Early bird: completed before deadline
        early = conn.execute(
            """SELECT COUNT(*) FROM tasks
               WHERE user_id=? AND done=1 AND deadline IS NOT NULL
               AND DATE(completed_at) < deadline""",
            (user_id,),
        ).fetchone()[0]

    checks = [
        ("first_task",  total_tasks >= 1),
        ("done_10",     done_count >= 10),
        ("done_50",     done_count >= 50),
        ("done_100",    done_count >= 100),
        ("streak_7",    streak >= 7),
        ("streak_30",   streak >= 30),
        ("early_bird",  early >= 1),
    ]
    for key, condition in checks:
        if condition and key not in existing:
            if award_achievement(user_id, key):
                new_achievements.append(key)

    # Update best streak
    s = get_settings(user_id)
    if streak > s.get("best_streak", 0):
        update_settings(user_id, best_streak=streak)

    return new_achievements


# ── Notifications ─────────────────────────────────────────────

def get_tasks_to_notify(user_id: int) -> dict:
    s = get_settings(user_id)
    days_before = s.get("notify_days_before", 1)
    today_str = date.today().isoformat()
    soon_str = (date.today() + timedelta(days=days_before)).isoformat()
    active = get_tasks(user_id, done=False)
    result: dict = {"overdue": [], "today": [], "soon": []}
    for t in active:
        if not t["deadline"]:
            continue
        if t["deadline"] < today_str:
            result["overdue"].append(t)
        elif t["deadline"] == today_str:
            result["today"].append(t)
        elif t["deadline"] <= soon_str:
            result["soon"].append(t)
    return result


# ── Stats ─────────────────────────────────────────────────────

def get_stats(user_id: int) -> dict:
    s = get_settings(user_id)
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

    if streak > s.get("best_streak", 0):
        update_settings(user_id, best_streak=streak)
        s["best_streak"] = streak

    return {
        "total": total, "active": active, "done_all": done_all,
        "done_week": done_week, "done_month": done_month,
        "overdue": overdue, "streak": streak,
        "best_streak": s.get("best_streak", streak),
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
        return [dict(r) for r in conn.execute(
            "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()]
