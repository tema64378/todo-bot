from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters,
)
from telegram.request import HTTPXRequest

import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────
TITLE, PRIORITY, CATEGORY, DEADLINE, NOTES, REPEAT = range(6)
EDIT_FIELD, EDIT_VAL = range(6, 8)
SETT_TIME = 8
SUB_TITLE = 9

# ── Constants ─────────────────────────────────────────────────
PRI_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
PRI_LABEL = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}
REPEAT_LABEL = {"none": "Не повторять", "daily": "Каждый день",
                "weekly": "Каждую неделю", "monthly": "Каждый месяц"}
CAT_EMOJI = {
    "Работа": "💼", "Личное": "🏠", "Учёба": "📚",
    "Здоровье": "💪", "Финансы": "💰", "Другое": "📌",
}


# ── Helpers ───────────────────────────────────────────────────

def fmt_deadline(dl_str: str | None) -> str:
    if not dl_str:
        return ""
    try:
        dl = datetime.strptime(dl_str, "%Y-%m-%d").date()
        delta = (dl - date.today()).days
        if delta < 0:
            return f"  ⚠️ просрочено {abs(delta)}д"
        if delta == 0:
            return "  🔔 сегодня!"
        if delta == 1:
            return "  ⏰ завтра"
        return f"  📅 {dl.strftime('%d.%m.%Y')}"
    except ValueError:
        return f"  📅 {dl_str}"


def fmt_task(task: dict, idx: int | None = None) -> str:
    prefix = f"{idx}. " if idx is not None else ""
    done_mark = "✅" if task["done"] else "⬜"
    cat = CAT_EMOJI.get(task.get("category", "Другое"), "📌")
    pri = PRI_EMOJI[task["priority"]]
    return f"{prefix}{done_mark} {pri}{cat} {task['title']}{fmt_deadline(task['deadline'])}"


def task_detail(task: dict) -> str:
    cat = f"{CAT_EMOJI.get(task.get('category','Другое'),'📌')} {task.get('category','Другое')}"
    pri = f"{PRI_EMOJI[task['priority']]} {PRI_LABEL[task['priority']]}"
    dl = datetime.strptime(task["deadline"], "%Y-%m-%d").strftime("%d.%m.%Y") \
        if task["deadline"] else "не задан"
    rep = REPEAT_LABEL.get(task.get("repeat", "none"), "—")
    notes = f"\n📝 {task['notes']}" if task.get("notes") else ""
    return (
        f"*#{task['id']} {task['title']}*\n"
        f"⚡ {pri}  |  {cat}\n"
        f"📅 Дедлайн: {dl}  |  🔁 {rep}"
        f"{notes}"
    )


def tasks_keyboard(tasks: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for t in tasks:
        if not t["done"]:
            rows.append([
                InlineKeyboardButton(f"✅ #{t['id']}", callback_data=f"done:{t['id']}"),
                InlineKeyboardButton(f"✏️ #{t['id']}", callback_data=f"edit:{t['id']}"),
                InlineKeyboardButton(f"🗑 #{t['id']}", callback_data=f"del:{t['id']}"),
            ])
    return InlineKeyboardMarkup(rows)


# ── /start ────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.get_settings(update.effective_user.id)  # init settings
    await update.message.reply_text(
        "👋 *Привет! Я твой планировщик задач.*\n\n"
        "➕ /add — добавить задачу\n"
        "📋 /list — активные задачи\n"
        "📆 /today — на сегодня\n"
        "📅 /upcoming — ближайшие 7 дней\n"
        "🔍 /find `текст` — поиск\n"
        "📊 /stats — статистика и стрик\n"
        "📁 /categories — по категориям\n"
        "📤 /export — экспорт в CSV\n"
        "⚙️ /settings — время уведомлений\n"
        "✅ /done `ID` — выполнено\n"
        "🗑 /delete `ID` — удалить\n"
        "✏️ /edit `ID` — редактировать\n"
        "📌 /subtasks `ID` — подзадачи",
        parse_mode="Markdown",
    )


# ── /add conversation ─────────────────────────────────────────

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Введи название задачи:")
    return TITLE


async def recv_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["title"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔴 Высокий", callback_data="pri:high"),
        InlineKeyboardButton("🟡 Средний",  callback_data="pri:medium"),
        InlineKeyboardButton("🟢 Низкий",   callback_data="pri:low"),
    ]])
    await update.message.reply_text("⚡ Выбери приоритет:", reply_markup=kb)
    return PRIORITY


async def recv_priority(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["priority"] = q.data.split(":")[1]
    cats = db.CATEGORIES
    rows = [[InlineKeyboardButton(
        f"{CAT_EMOJI.get(c,'📌')} {c}", callback_data=f"cat:{c}"
    )] for c in cats]
    await q.edit_message_text("📁 Выбери категорию:",
                              reply_markup=InlineKeyboardMarkup(rows))
    return CATEGORY


async def recv_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["category"] = q.data.split(":", 1)[1]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭ Без дедлайна", callback_data="dl:skip")
    ]])
    await q.edit_message_text(
        "📅 Введи дедлайн *ДД.ММ.ГГГГ* или пропусти:",
        parse_mode="Markdown", reply_markup=kb,
    )
    return DEADLINE


async def recv_deadline_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        dl = datetime.strptime(raw, "%d.%m.%Y")
        ctx.user_data["deadline"] = dl.strftime("%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введи *ДД.ММ.ГГГГ* или /cancel:",
            parse_mode="Markdown",
        )
        return DEADLINE
    await update.message.reply_text(
        "📝 Добавь заметку к задаче (или /skip):"
    )
    return NOTES


async def recv_deadline_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["deadline"] = None
    await q.edit_message_text("📝 Добавь заметку к задаче (или напиши /skip):")
    return NOTES


async def recv_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["notes"] = None if text.lower() in ("/skip", "нет", "-") else text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Не повторять", callback_data="rep:none")],
        [InlineKeyboardButton("📅 Каждый день",  callback_data="rep:daily"),
         InlineKeyboardButton("📅 Каждую неделю", callback_data="rep:weekly")],
        [InlineKeyboardButton("📅 Каждый месяц", callback_data="rep:monthly")],
    ])
    await update.message.reply_text("🔁 Повторяющаяся задача?", reply_markup=kb)
    return REPEAT


async def recv_repeat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    repeat = q.data.split(":")[1]
    user_id = q.from_user.id
    d = ctx.user_data
    task_id = db.add_task(user_id, d["title"], d["priority"], d["category"],
                          d.get("deadline"), d.get("notes"), repeat)
    pri = f"{PRI_EMOJI[d['priority']]} {PRI_LABEL[d['priority']]}"
    dl_str = datetime.strptime(d["deadline"], "%Y-%m-%d").strftime("%d.%m.%Y") \
        if d.get("deadline") else "не задан"
    await q.edit_message_text(
        f"✅ *Задача #{task_id} добавлена!*\n\n"
        f"📌 {d['title']}\n"
        f"⚡ {pri}\n"
        f"📁 {CAT_EMOJI.get(d['category'],'📌')} {d['category']}\n"
        f"📅 {dl_str}  |  🔁 {REPEAT_LABEL[repeat]}",
        parse_mode="Markdown",
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


async def skip_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["notes"] = None
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Не повторять", callback_data="rep:none")],
        [InlineKeyboardButton("📅 Каждый день",  callback_data="rep:daily"),
         InlineKeyboardButton("📅 Каждую неделю", callback_data="rep:weekly")],
        [InlineKeyboardButton("📅 Каждый месяц", callback_data="rep:monthly")],
    ])
    await update.message.reply_text("🔁 Повторяющаяся задача?", reply_markup=kb)
    return REPEAT


# ── /list /all /today /upcoming ───────────────────────────────

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks(update.effective_user.id, done=False)
    if not tasks:
        await update.message.reply_text("🎉 Нет активных задач!")
        return
    lines = ["📋 *Активные задачи:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=tasks_keyboard(tasks)
    )


async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks(update.effective_user.id)
    if not tasks:
        await update.message.reply_text("📭 Задач нет.")
        return
    lines = ["📊 *Все задачи:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=tasks_keyboard(tasks)
    )


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    tasks = [t for t in db.get_tasks(update.effective_user.id, done=False)
             if t["deadline"] and t["deadline"] <= today]
    if not tasks:
        await update.message.reply_text("✨ На сегодня задач нет.")
        return
    lines = ["📆 *На сегодня:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=tasks_keyboard(tasks)
    )


async def cmd_upcoming(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    in7 = (date.today() + timedelta(days=7)).isoformat()
    tasks = [t for t in db.get_tasks(update.effective_user.id, done=False)
             if t["deadline"] and t["deadline"] <= in7]
    if not tasks:
        await update.message.reply_text("✨ Ближайших задач нет.")
        return
    lines = ["📅 *Ближайшие 7 дней:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=tasks_keyboard(tasks)
    )


# ── /done /delete ─────────────────────────────────────────────

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /done <ID>")
        return
    try:
        tid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return
    task = db.mark_done(tid, update.effective_user.id)
    if task:
        rep_msg = " 🔁 Создана следующая задача!" if task.get("repeat") != "none" else ""
        await update.message.reply_text(f"✅ Задача #{tid} выполнена!{rep_msg}")
    else:
        await update.message.reply_text(f"❌ Задача #{tid} не найдена или уже выполнена.")


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /delete <ID>")
        return
    try:
        tid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return
    if db.delete_task(tid, update.effective_user.id):
        await update.message.reply_text(f"🗑 Задача #{tid} удалена.")
    else:
        await update.message.reply_text(f"❌ Задача #{tid} не найдена.")


# ── /edit conversation ────────────────────────────────────────

async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /edit <ID>")
        return ConversationHandler.END
    try:
        tid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return ConversationHandler.END
    task = db.get_task(tid, update.effective_user.id)
    if not task:
        await update.message.reply_text(f"❌ Задача #{tid} не найдена.")
        return ConversationHandler.END
    ctx.user_data["edit_id"] = tid
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Название",  callback_data="ef:title"),
         InlineKeyboardButton("⚡ Приоритет", callback_data="ef:priority")],
        [InlineKeyboardButton("📁 Категория", callback_data="ef:category"),
         InlineKeyboardButton("📅 Дедлайн",  callback_data="ef:deadline")],
        [InlineKeyboardButton("📝 Заметка",   callback_data="ef:notes")],
    ])
    await update.message.reply_text(
        f"{task_detail(task)}\n\n✏️ Что изменить?",
        parse_mode="Markdown", reply_markup=kb,
    )
    return EDIT_FIELD


async def edit_select_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    field = q.data.split(":")[1]
    ctx.user_data["edit_field"] = field

    if field == "priority":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔴 Высокий", callback_data="epv:high"),
            InlineKeyboardButton("🟡 Средний",  callback_data="epv:medium"),
            InlineKeyboardButton("🟢 Низкий",   callback_data="epv:low"),
        ]])
        await q.edit_message_text("⚡ Выбери новый приоритет:", reply_markup=kb)
        return EDIT_VAL

    if field == "category":
        rows = [[InlineKeyboardButton(
            f"{CAT_EMOJI.get(c,'📌')} {c}", callback_data=f"epv:{c}"
        )] for c in db.CATEGORIES]
        await q.edit_message_text("📁 Выбери новую категорию:",
                                  reply_markup=InlineKeyboardMarkup(rows))
        return EDIT_VAL

    prompts = {
        "title":    "📝 Введи новое название:",
        "deadline": "📅 Введи новый дедлайн *ДД.ММ.ГГГГ* (или «нет» чтобы убрать):",
        "notes":    "📝 Введи новую заметку (или «нет» чтобы убрать):",
    }
    await q.edit_message_text(prompts[field], parse_mode="Markdown")
    return EDIT_VAL


async def edit_recv_val_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    field = ctx.user_data.get("edit_field")
    tid = ctx.user_data.get("edit_id")
    raw = update.message.text.strip()
    value: str | None = raw

    if field == "deadline":
        if raw.lower() in ("нет", "-", "skip"):
            value = None
        else:
            try:
                value = datetime.strptime(raw, "%d.%m.%Y").strftime("%Y-%m-%d")
            except ValueError:
                await update.message.reply_text(
                    "❌ Формат: *ДД.ММ.ГГГГ*. Попробуй снова:", parse_mode="Markdown"
                )
                return EDIT_VAL
    elif field == "notes":
        value = None if raw.lower() in ("нет", "-") else raw

    db.update_task(tid, update.effective_user.id, **{field: value})
    await update.message.reply_text("✅ Задача обновлена!")
    ctx.user_data.clear()
    return ConversationHandler.END


async def edit_recv_val_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    field = ctx.user_data.get("edit_field")
    tid = ctx.user_data.get("edit_id")
    value = q.data.split(":", 1)[1]
    db.update_task(tid, q.from_user.id, **{field: value})
    await q.edit_message_text("✅ Задача обновлена!")
    ctx.user_data.clear()
    return ConversationHandler.END


# ── /find ─────────────────────────────────────────────────────

async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /find <текст>")
        return
    query = " ".join(ctx.args)
    tasks = db.search_tasks(update.effective_user.id, query)
    if not tasks:
        await update.message.reply_text(f"🔍 По запросу «{query}» ничего не найдено.")
        return
    lines = [f"🔍 *Результаты поиска «{query}»:*\n"] + \
            [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=tasks_keyboard(tasks)
    )


# ── /stats ────────────────────────────────────────────────────

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = db.get_stats(update.effective_user.id)
    pct = round(s["done_all"] / s["total"] * 100) if s["total"] else 0
    streak_str = f"🔥 *{s['streak']} дн подряд!*" if s["streak"] > 1 else f"{s['streak']} дн"
    await update.message.reply_text(
        f"📊 *Твоя статистика:*\n\n"
        f"📋 Всего задач: {s['total']}\n"
        f"⬜ Активных: {s['active']}\n"
        f"⚠️ Просрочено: {s['overdue']}\n\n"
        f"✅ Выполнено всего: {s['done_all']} ({pct}%)\n"
        f"✅ За 7 дней: {s['done_week']}\n"
        f"✅ За 30 дней: {s['done_month']}\n\n"
        f"⚡ Стрик выполнения: {streak_str}",
        parse_mode="Markdown",
    )


# ── /categories ───────────────────────────────────────────────

async def cmd_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = db.get_categories_stats(update.effective_user.id)
    if not stats:
        await update.message.reply_text("📁 Категорий нет.")
        return
    lines = ["📁 *Категории:*\n"]
    rows = []
    for s in stats:
        if s["active"] > 0:
            cat = s["category"]
            lines.append(
                f"{CAT_EMOJI.get(cat,'📌')} {cat}: {s['active']} активных"
            )
            rows.append([InlineKeyboardButton(
                f"{CAT_EMOJI.get(cat,'📌')} {cat} ({s['active']})",
                callback_data=f"showcat:{cat}",
            )])
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ── /subtasks ─────────────────────────────────────────────────

async def cmd_subtasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /subtasks <ID>")
        return ConversationHandler.END
    try:
        tid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return ConversationHandler.END
    task = db.get_task(tid, update.effective_user.id)
    if not task:
        await update.message.reply_text(f"❌ Задача #{tid} не найдена.")
        return ConversationHandler.END
    ctx.user_data["sub_task_id"] = tid
    await _show_subtasks(update.message, tid, task["title"])
    await update.message.reply_text(
        "➕ Напиши название подзадачи или /cancel чтобы выйти:"
    )
    return SUB_TITLE


async def _show_subtasks(msg, task_id: int, task_title: str):
    subs = db.get_subtasks(task_id)
    if not subs:
        text = f"📌 *{task_title}*\n\nПодзадач пока нет."
        await msg.reply_text(text, parse_mode="Markdown")
        return
    lines = [f"📌 *{task_title}* — подзадачи:\n"]
    rows = []
    for s in subs:
        mark = "✅" if s["done"] else "⬜"
        lines.append(f"{mark} {s['title']}")
        rows.append([
            InlineKeyboardButton(
                f"{'↩️' if s['done'] else '✅'} {s['title'][:20]}",
                callback_data=f"sub_toggle:{s['id']}:{task_id}",
            ),
            InlineKeyboardButton("🗑", callback_data=f"sub_del:{s['id']}:{task_id}"),
        ])
    await msg.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def recv_subtask_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = ctx.user_data.get("sub_task_id")
    title = update.message.text.strip()
    db.add_subtask(tid, title)
    task = db.get_task(tid, update.effective_user.id)
    await _show_subtasks(update.message, tid, task["title"] if task else "Задача")
    await update.message.reply_text("➕ Ещё подзадачу или /cancel:")
    return SUB_TITLE


# ── /settings conversation ────────────────────────────────────

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = db.get_settings(user_id)
    times = s["notify_times"]
    await update.message.reply_text(
        f"⚙️ *Настройки уведомлений*\n\n"
        f"Текущее время: *{times}*\n\n"
        f"Введи новое время уведомлений через запятую.\n"
        f"Пример: `09:00,13:00,21:00`\n\n"
        f"Уведомления приходят о просроченных задачах,\n"
        f"задачах на сегодня и на завтра.\n\n"
        f"Введи время или /cancel:",
        parse_mode="Markdown",
    )
    return SETT_TIME


async def recv_settings_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    times = [t.strip() for t in raw.split(",")]
    valid = []
    for t in times:
        try:
            datetime.strptime(t, "%H:%M")
            valid.append(t)
        except ValueError:
            pass
    if not valid:
        await update.message.reply_text(
            "❌ Неверный формат. Пример: `09:00,21:00`", parse_mode="Markdown"
        )
        return SETT_TIME
    db.update_notify_times(update.effective_user.id, ",".join(valid))
    await update.message.reply_text(
        f"✅ Уведомления настроены: *{', '.join(valid)}*\n"
        f"Буду присылать напоминания о дедлайнах в это время каждый день!",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── /export ───────────────────────────────────────────────────

async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_all_tasks_csv(update.effective_user.id)
    if not tasks:
        await update.message.reply_text("📭 Нет задач для экспорта.")
        return
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "id", "title", "priority", "category", "deadline",
        "notes", "repeat", "done", "completed_at", "created_at"
    ])
    writer.writeheader()
    for t in tasks:
        writer.writerow({k: t.get(k, "") for k in writer.fieldnames})
    buf.seek(0)
    filename = f"tasks_{date.today().isoformat()}.csv"
    await update.message.reply_document(
        document=InputFile(io.BytesIO(buf.read().encode("utf-8-sig")), filename=filename),
        caption=f"📤 Экспорт задач — {len(tasks)} шт.",
    )


# ── Inline button callbacks ───────────────────────────────────

async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    data = q.data

    if data.startswith("done:"):
        tid = int(data.split(":")[1])
        task = db.mark_done(tid, user_id)
        msg = f"✅ Задача #{tid} выполнена!" if task else "Уже выполнена."
        if task and task.get("repeat") != "none":
            msg += " 🔁 Создана следующая задача!"
        await q.answer(msg, show_alert=False)

    elif data.startswith("del:"):
        tid = int(data.split(":")[1])
        db.delete_task(tid, user_id)
        await q.answer(f"🗑 Задача #{tid} удалена.", show_alert=False)

    elif data.startswith("edit:"):
        tid = int(data.split(":")[1])
        task = db.get_task(tid, user_id)
        if task:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Название",  callback_data=f"qedit:{tid}:title"),
                 InlineKeyboardButton("⚡ Приоритет", callback_data=f"qedit:{tid}:priority")],
                [InlineKeyboardButton("📅 Дедлайн",   callback_data=f"qedit:{tid}:deadline")],
            ])
            await q.message.reply_text(
                f"{task_detail(task)}\n\n✏️ Что изменить?",
                parse_mode="Markdown", reply_markup=kb,
            )
        return

    elif data.startswith("showcat:"):
        cat = data.split(":", 1)[1]
        tasks = db.get_tasks(user_id, done=False, category=cat)
        lines = [f"📁 *{CAT_EMOJI.get(cat,'📌')} {cat}:*\n"] + \
                [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
        await q.message.reply_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=tasks_keyboard(tasks),
        )
        return

    elif data.startswith("sub_toggle:"):
        _, sid, tid = data.split(":")
        db.toggle_subtask(int(sid))
        task = db.get_task(int(tid), user_id)
        subs = db.get_subtasks(int(tid))
        rows = []
        for s in subs:
            rows.append([
                InlineKeyboardButton(
                    f"{'↩️' if s['done'] else '✅'} {s['title'][:20]}",
                    callback_data=f"sub_toggle:{s['id']}:{tid}",
                ),
                InlineKeyboardButton("🗑", callback_data=f"sub_del:{s['id']}:{tid}"),
            ])
        lines = [f"📌 *{task['title'] if task else 'Задача'}* — подзадачи:\n"]
        for s in subs:
            lines.append(f"{'✅' if s['done'] else '⬜'} {s['title']}")
        try:
            await q.edit_message_text(
                "\n".join(lines), parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        except Exception:
            pass
        return

    elif data.startswith("sub_del:"):
        _, sid, tid = data.split(":")
        db.delete_subtask(int(sid))
        task = db.get_task(int(tid), user_id)
        subs = db.get_subtasks(int(tid))
        if not subs:
            try:
                await q.edit_message_text(
                    f"📌 *{task['title'] if task else 'Задача'}*\n\nПодзадач нет.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
            return
        rows = []
        lines = [f"📌 *{task['title'] if task else 'Задача'}* — подзадачи:\n"]
        for s in subs:
            lines.append(f"{'✅' if s['done'] else '⬜'} {s['title']}")
            rows.append([
                InlineKeyboardButton(
                    f"{'↩️' if s['done'] else '✅'} {s['title'][:20]}",
                    callback_data=f"sub_toggle:{s['id']}:{tid}",
                ),
                InlineKeyboardButton("🗑", callback_data=f"sub_del:{s['id']}:{tid}"),
            ])
        try:
            await q.edit_message_text(
                "\n".join(lines), parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        except Exception:
            pass
        return

    # Refresh list after done/del
    tasks = db.get_tasks(user_id, done=False)
    if not tasks:
        try:
            await q.edit_message_text("🎉 Нет активных задач!")
        except Exception:
            pass
        return
    lines = ["📋 *Активные задачи:*\n"] + \
            [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    try:
        await q.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=tasks_keyboard(tasks),
        )
    except Exception:
        pass


# ── Notifications ─────────────────────────────────────────────

async def send_notification(app: Application, user_id: int):
    tasks = db.get_tasks_to_notify(user_id)
    if not any(tasks.values()):
        return

    lines = ["🔔 *Напоминание о задачах*\n"]

    if tasks["overdue"]:
        lines.append(f"⚠️ *Просрочено — {len(tasks['overdue'])} шт:*")
        for t in tasks["overdue"]:
            dl = datetime.strptime(t["deadline"], "%Y-%m-%d").date()
            days_ago = (date.today() - dl).days
            lines.append(f"  {PRI_EMOJI[t['priority']]} {t['title']} (+{days_ago} дн)")
        lines.append("")

    if tasks["today"]:
        lines.append(f"📅 *На сегодня — {len(tasks['today'])} шт:*")
        for t in tasks["today"]:
            lines.append(f"  {PRI_EMOJI[t['priority']]} {t['title']}")
        lines.append("")

    if tasks["tomorrow"]:
        lines.append(f"⏰ *На завтра — {len(tasks['tomorrow'])} шт:*")
        for t in tasks["tomorrow"]:
            lines.append(f"  {PRI_EMOJI[t['priority']]} {t['title']}")

    lines.append("\n📋 /list — открыть все задачи")

    try:
        await app.bot.send_message(
            chat_id=user_id,
            text="\n".join(lines),
            parse_mode="Markdown",
        )
        log.info(f"Уведомление отправлено пользователю {user_id}")
    except Exception as e:
        log.error(f"Не удалось отправить уведомление {user_id}: {e}")


async def check_and_notify(app: Application):
    now = datetime.now()
    db.cleanup_old_logs()
    user_ids = db.get_all_active_user_ids()

    for user_id in user_ids:
        settings = db.get_settings(user_id)
        notify_times = [t.strip() for t in settings["notify_times"].split(",")]

        for nt in notify_times:
            if not nt:
                continue
            try:
                nt_h, nt_m = map(int, nt.split(":"))
                nt_dt = now.replace(hour=nt_h, minute=nt_m, second=0, microsecond=0)
                diff = abs((now - nt_dt).total_seconds())
                if diff <= 600 and not db.was_notified(user_id, nt):
                    await send_notification(app, user_id)
                    db.log_notification(user_id, nt)
                    break  # one notification per check cycle per user
            except Exception as e:
                log.error(f"Ошибка проверки уведомлений {user_id}: {e}")


# ── App setup ─────────────────────────────────────────────────

async def post_init(app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_and_notify,
        trigger="interval",
        minutes=10,
        args=[app],
        id="notify_check",
    )
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    log.info("Планировщик запущен (проверка каждые 10 мин)")


async def post_shutdown(app: Application):
    s = app.bot_data.get("scheduler")
    if s and s.running:
        s.shutdown(wait=False)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан!")

    db.init_db()

    req = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(req)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # ── Add task conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_title)],
            PRIORITY: [CallbackQueryHandler(recv_priority, pattern=r"^pri:")],
            CATEGORY: [CallbackQueryHandler(recv_category, pattern=r"^cat:")],
            DEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_deadline_text),
                CallbackQueryHandler(recv_deadline_skip, pattern=r"^dl:skip$"),
            ],
            NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_notes),
                CommandHandler("skip", skip_notes),
            ],
            REPEAT: [CallbackQueryHandler(recv_repeat, pattern=r"^rep:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── Edit conversation
    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("edit", cmd_edit)],
        states={
            EDIT_FIELD: [CallbackQueryHandler(edit_select_field, pattern=r"^ef:")],
            EDIT_VAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_recv_val_text),
                CallbackQueryHandler(edit_recv_val_cb, pattern=r"^epv:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── Settings conversation
    sett_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", cmd_settings)],
        states={
            SETT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_settings_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── Subtasks conversation
    sub_conv = ConversationHandler(
        entry_points=[CommandHandler("subtasks", cmd_subtasks)],
        states={
            SUB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_subtask_title)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(add_conv)
    app.add_handler(edit_conv)
    app.add_handler(sett_conv)
    app.add_handler(sub_conv)
    app.add_handler(CommandHandler("list",       cmd_list))
    app.add_handler(CommandHandler("all",        cmd_all))
    app.add_handler(CommandHandler("today",      cmd_today))
    app.add_handler(CommandHandler("upcoming",   cmd_upcoming))
    app.add_handler(CommandHandler("done",       cmd_done))
    app.add_handler(CommandHandler("delete",     cmd_delete))
    app.add_handler(CommandHandler("find",       cmd_find))
    app.add_handler(CommandHandler("stats",      cmd_stats))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("export",     cmd_export))
    app.add_handler(CallbackQueryHandler(button_callback))

    log.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
