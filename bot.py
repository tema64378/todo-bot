from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime, date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters,
)
from telegram.request import HTTPXRequest

import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────
TITLE, PRIORITY, CATEGORY, DEADLINE, NOTES, REPEAT = range(6)
EDIT_FIELD, EDIT_VAL = range(6, 8)
SETT_MENU, SETT_TIME, SETT_DAYS = range(8, 11)
SUB_TITLE = 11
TMPL_SAVE_NAME = 12

# ── Constants ─────────────────────────────────────────────────
PHOTO_DONE    = "AgACAgIAAxkDAAN0acuV2IcLvqWjvv4Om47rYjCXrBAAAiMZaxuoj2BKqUvTPFRSePQBAAMCAAN4AAM6BA"
PHOTO_OVERDUE = "AgACAgIAAxkDAAN1acuV2Zo50-H5NS84qN1YfgABXcW6AAIkGWsbqI9gSnxreqeYb2ZiAQADAgADeAADOgQ"

PRI_EMOJI  = {"high": "🔴", "medium": "🟡", "low": "🟢"}
PRI_LABEL  = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}
REPEAT_LBL = {"none": "Не повторять", "daily": "Каждый день",
              "weekly": "Каждую неделю", "monthly": "Каждый месяц"}
CAT_EMOJI  = {"Работа": "💼", "Личное": "🏠", "Учёба": "📚",
              "Здоровье": "💪", "Финансы": "💰", "Другое": "📌"}

QUOTES = [
    "Начни сейчас — совершенство придёт в процессе.",
    "Маленький шаг каждый день — большой результат через год.",
    "Не откладывай на завтра то, что можно сделать сегодня.",
    "Дисциплина — это мост между целями и результатом.",
    "Фокус — это умение говорить «нет» тысяче вещей.",
    "Успех — это сумма маленьких усилий, повторяемых день за днём.",
    "Продуктивность — не значит быть занятым. Это значит быть эффективным.",
    "Каждая выполненная задача — шаг вперёд.",
    "Планируй работу и работай по плану.",
    "Тот, кто хочет — ищет возможности. Тот, кто не хочет — ищет причины.",
    "Действие — основа всего успеха.",
    "Самая длинная дорога начинается с первого шага.",
    "Хорошее начало — половина дела.",
    "Думай о прогрессе, а не о совершенстве.",
    "Вчера ты говорил «завтра». Сделай это сегодня!",
]


def get_daily_quote() -> str:
    return QUOTES[date.today().timetuple().tm_yday % len(QUOTES)]


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
    mark = "✅" if task["done"] else "⬜"
    cat  = CAT_EMOJI.get(task.get("category", "Другое"), "📌")
    pri  = PRI_EMOJI[task["priority"]]
    tags = ""
    if task.get("tags"):
        tags = "  " + " ".join(f"#{t}" for t in task["tags"].split(",") if t)
    return f"{prefix}{mark} {pri}{cat} {task['title']}{fmt_deadline(task['deadline'])}{tags}"


def task_detail(task: dict) -> str:
    cat  = f"{CAT_EMOJI.get(task.get('category','Другое'),'📌')} {task.get('category','Другое')}"
    pri  = f"{PRI_EMOJI[task['priority']]} {PRI_LABEL[task['priority']]}"
    dl   = (datetime.strptime(task["deadline"], "%Y-%m-%d").strftime("%d.%m.%Y")
            if task["deadline"] else "не задан")
    rep  = REPEAT_LBL.get(task.get("repeat", "none"), "—")
    tags = ("  " + " ".join(f"#{t}" for t in task["tags"].split(",") if t)
            if task.get("tags") else "")
    notes = f"\n📝 {task['notes']}" if task.get("notes") else ""
    return (f"*#{task['id']} {task['title']}*{tags}\n"
            f"⚡ {pri}  |  {cat}\n"
            f"📅 {dl}  |  🔁 {rep}{notes}")


def tasks_keyboard(tasks: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for t in tasks:
        if not t["done"]:
            rows.append([
                InlineKeyboardButton(f"✅ #{t['id']}", callback_data=f"done:{t['id']}"),
                InlineKeyboardButton(f"✏️",            callback_data=f"edit:{t['id']}"),
                InlineKeyboardButton(f"💤",            callback_data=f"snooze1:{t['id']}"),
                InlineKeyboardButton(f"🗑",            callback_data=f"del:{t['id']}"),
            ])
    return InlineKeyboardMarkup(rows)


def sort_keyboard(current: str) -> InlineKeyboardMarkup:
    options = [("⚡ Приоритет", "priority"), ("📅 Дедлайн", "deadline"), ("🕐 Дата", "created")]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            ("✓ " if current == v else "") + label,
            callback_data=f"sort:{v}",
        ) for label, v in options
    ]])


# ── /start ────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.get_settings(update.effective_user.id)
    await update.message.reply_text(
        "👋 *Привет! Я твой планировщик задач.*\n\n"
        "➕ /add — добавить задачу\n"
        "⚡ /q `текст` — быстрое добавление\n"
        "📋 /list — активные задачи\n"
        "📆 /today — на сегодня\n"
        "📅 /upcoming — ближайшие задачи\n"
        "🎯 /focus — самая важная задача\n"
        "🔍 /find `текст` — поиск\n"
        "🏷 /tag `#тег` — задачи по тегу\n"
        "📊 /stats — статистика\n"
        "🏆 /achievements — достижения\n"
        "📁 /categories — по категориям\n"
        "📋 /templates — шаблоны\n"
        "📤 /export — экспорт CSV\n"
        "⚙️ /settings — настройки\n\n"
        "✅ /done `ID` · 🗑 /delete `ID` · ✏️ /edit `ID`\n"
        "↩️ /undone `ID` · 📋 /copy `ID` · 📌 /subtasks `ID`",
        parse_mode="Markdown",
    )


# ── /q — быстрое добавление ───────────────────────────────────

async def cmd_quick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Использование: `/q Название [сегодня/завтра/ДД.ММ.ГГГГ] [высокий/низкий]`\n\n"
            "Пример: `/q Купить молоко завтра высокий`",
            parse_mode="Markdown",
        )
        return
    text = " ".join(ctx.args)
    title, priority, deadline, deadline_time = db.parse_quick_add(text)
    task_id = db.add_task(
        update.effective_user.id, title, priority, "Другое", deadline, None, "none"
    )
    dl_str = (datetime.strptime(deadline, "%Y-%m-%d").strftime("%d.%m.%Y")
              if deadline else "не задан")
    await update.message.reply_text(
        f"⚡ *Задача #{task_id} добавлена!*\n"
        f"📌 {title}\n"
        f"{PRI_EMOJI[priority]} {PRI_LABEL[priority]}  |  📅 {dl_str}",
        parse_mode="Markdown",
    )
    await _notify_new_achievements(update.message, update.effective_user.id)


# ── /add conversation ─────────────────────────────────────────

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Введи название задачи:\n_(поддерживаются #теги)_",
                                    parse_mode="Markdown")
    return TITLE


async def recv_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["title"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔴 Высокий", callback_data="pri:high"),
        InlineKeyboardButton("🟡 Средний",  callback_data="pri:medium"),
        InlineKeyboardButton("🟢 Низкий",   callback_data="pri:low"),
    ]])
    await update.message.reply_text("⚡ Приоритет:", reply_markup=kb)
    return PRIORITY


async def recv_priority(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["priority"] = q.data.split(":")[1]
    rows = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📌')} {c}", callback_data=f"cat:{c}")]
            for c in db.CATEGORIES]
    await q.edit_message_text("📁 Категория:", reply_markup=InlineKeyboardMarkup(rows))
    return CATEGORY


async def recv_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    ctx.user_data["category"] = q.data.split(":", 1)[1]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭ Без дедлайна", callback_data="dl:skip"),
        InlineKeyboardButton("📅 Сегодня",      callback_data="dl:today"),
        InlineKeyboardButton("⏰ Завтра",        callback_data="dl:tomorrow"),
    ]])
    await q.edit_message_text("📅 Дедлайн (*ДД.ММ.ГГГГ*) или выбери:",
                              parse_mode="Markdown", reply_markup=kb)
    return DEADLINE


async def recv_deadline_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["deadline"] = datetime.strptime(
            update.message.text.strip(), "%d.%m.%Y"
        ).strftime("%Y-%m-%d")
    except ValueError:
        await update.message.reply_text("❌ Формат: *ДД.ММ.ГГГГ*. Попробуй снова:",
                                        parse_mode="Markdown")
        return DEADLINE
    await update.message.reply_text("📝 Заметка к задаче (или /skip):")
    return NOTES


async def recv_deadline_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    val = q.data.split(":")[1]
    if val == "skip":
        ctx.user_data["deadline"] = None
    elif val == "today":
        ctx.user_data["deadline"] = date.today().strftime("%Y-%m-%d")
    elif val == "tomorrow":
        ctx.user_data["deadline"] = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    await q.edit_message_text("📝 Заметка к задаче (или напиши /skip):")
    return NOTES


async def recv_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["notes"] = None if text.lower() in ("/skip", "нет", "-") else text
    return await _ask_repeat(update.message)


async def skip_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["notes"] = None
    return await _ask_repeat(update.message)


async def _ask_repeat(msg):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Не повторять", callback_data="rep:none")],
        [InlineKeyboardButton("📅 Каждый день",   callback_data="rep:daily"),
         InlineKeyboardButton("📅 Каждую неделю", callback_data="rep:weekly")],
        [InlineKeyboardButton("📅 Каждый месяц",  callback_data="rep:monthly")],
    ])
    await msg.reply_text("🔁 Повторение:", reply_markup=kb)
    return REPEAT


async def recv_repeat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    repeat = q.data.split(":")[1]
    user_id = q.from_user.id
    d = ctx.user_data
    task_id = db.add_task(user_id, d["title"], d["priority"], d["category"],
                          d.get("deadline"), d.get("notes"), repeat,
                          deadline_time=d.get("deadline_time"),
                          remind_at=d.get("remind_at"))
    pri = f"{PRI_EMOJI[d['priority']]} {PRI_LABEL[d['priority']]}"
    dl_str = (datetime.strptime(d["deadline"], "%Y-%m-%d").strftime("%d.%m.%Y")
              if d.get("deadline") else "не задан")

    # Offer to save as template
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💾 Сохранить как шаблон", callback_data=f"tmpl_save:{task_id}"),
        InlineKeyboardButton("Не нужно", callback_data="tmpl_skip"),
    ]])
    await q.edit_message_text(
        f"✅ *Задача #{task_id} добавлена!*\n\n"
        f"📌 {d['title']}\n{pri}\n"
        f"📁 {CAT_EMOJI.get(d['category'],'📌')} {d['category']}\n"
        f"📅 {dl_str}  |  🔁 {REPEAT_LBL[repeat]}",
        parse_mode="Markdown", reply_markup=kb,
    )
    ctx.user_data.clear()
    ctx.user_data["last_task_id"] = task_id

    import asyncio
    asyncio.ensure_future(_notify_new_achievements_cb(q.message, user_id))
    return ConversationHandler.END


async def _notify_new_achievements_cb(msg, user_id: int):
    new = db.check_achievements(user_id)
    for key in new:
        emoji, name, desc = db.ACHIEVEMENTS[key]
        try:
            await msg.reply_text(
                f"🏆 *Достижение разблокировано!*\n{emoji} *{name}*\n_{desc}_",
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def _notify_new_achievements(msg, user_id: int):
    new = db.check_achievements(user_id)
    for key in new:
        emoji, name, desc = db.ACHIEVEMENTS[key]
        try:
            await msg.reply_text(
                f"🏆 *Достижение разблокировано!*\n{emoji} *{name}*\n_{desc}_",
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


# ── /list /all /today /upcoming ───────────────────────────────

async def _send_tasks(msg, tasks: list[dict], title: str, user_id: int):
    s = db.get_settings(user_id)
    sort_by = s.get("sort_by", "priority")
    tasks_sorted = db.get_tasks(user_id, done=False) if not tasks else tasks
    lines = [f"{title}\n"] + [fmt_task(t, i) for i, t in enumerate(tasks_sorted, 1)]
    kb = tasks_keyboard(tasks_sorted)
    # Add sort row
    sort_row = sort_keyboard(sort_by)
    combined = InlineKeyboardMarkup(kb.inline_keyboard + sort_row.inline_keyboard)
    await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=combined)


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = db.get_settings(user_id)
    tasks = db.get_tasks(user_id, done=False, sort_by=s.get("sort_by", "priority"))
    if not tasks:
        await update.message.reply_text("🎉 Нет активных задач!")
        return
    await _send_tasks(update.message, tasks, "📋 *Активные задачи:*", user_id)


async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks(update.effective_user.id)
    if not tasks:
        await update.message.reply_text("📭 Задач нет.")
        return
    lines = ["📊 *Все задачи:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=tasks_keyboard([t for t in tasks if not t["done"]]),
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


async def cmd_archive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks(update.effective_user.id, done=True)
    if not tasks:
        await update.message.reply_text("📭 Выполненных задач нет.")
        return
    lines = ["📂 *Архив выполненных:*\n"]
    for i, t in enumerate(tasks[:30], 1):
        done_at = ""
        if t.get("completed_at"):
            try:
                done_at = "  ✅ " + datetime.fromisoformat(t["completed_at"]).strftime("%d.%m")
            except Exception:
                pass
        lines.append(f"{i}. ✅ {PRI_EMOJI[t['priority']]} {t['title']}{done_at}")
    if len(tasks) > 30:
        lines.append(f"\n_...и ещё {len(tasks)-30} задач_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /focus ────────────────────────────────────────────────────

async def cmd_focus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks(update.effective_user.id, done=False, sort_by="deadline")
    if not tasks:
        await update.message.reply_text("🎉 Нет активных задач! Отдыхай.")
        return
    # Priority: overdue high → overdue any → today high → today any → upcoming high → any
    today = date.today().isoformat()
    def score(t):
        pri_score = {"high": 0, "medium": 1, "low": 2}[t["priority"]]
        dl = t["deadline"] or "9999-99-99"
        overdue = 1 if dl < today else 0
        return (0 if overdue else 1, pri_score, dl)
    top = sorted(tasks, key=score)[0]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Выполнено!", callback_data=f"done:{top['id']}"),
        InlineKeyboardButton("💤 Отложить на день", callback_data=f"snooze1:{top['id']}"),
    ]])
    await update.message.reply_text(
        f"🎯 *Фокус — самая важная задача:*\n\n{task_detail(top)}",
        parse_mode="Markdown", reply_markup=kb,
    )


# ── /done /undone /delete /copy ───────────────────────────────

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /done <ID>"); return
    try:
        tid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом."); return
    task = db.mark_done(tid, update.effective_user.id)
    if task:
        rep = " 🔁 Создана следующая задача!" if task.get("repeat") != "none" else ""
        await update.message.reply_photo(
            photo=PHOTO_DONE,
            caption=f"✅ *Задача #{tid} выполнена!*{rep}\n📌 {task['title']}",
            parse_mode="Markdown",
        )
        await _notify_new_achievements(update.message, update.effective_user.id)
    else:
        await update.message.reply_text(f"❌ Задача #{tid} не найдена или уже выполнена.")


async def cmd_undone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /undone <ID>"); return
    try:
        tid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом."); return
    if db.undone_task(tid, update.effective_user.id):
        await update.message.reply_text(f"↩️ Задача #{tid} возвращена в активные.")
    else:
        await update.message.reply_text(f"❌ Задача #{tid} не найдена.")


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /delete <ID>"); return
    try:
        tid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом."); return
    if db.delete_task(tid, update.effective_user.id):
        await update.message.reply_text(f"🗑 Задача #{tid} удалена.")
    else:
        await update.message.reply_text(f"❌ Задача #{tid} не найдена.")


async def cmd_copy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /copy <ID>"); return
    try:
        tid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом."); return
    new_id = db.copy_task(tid, update.effective_user.id)
    if new_id:
        await update.message.reply_text(f"📋 Создана копия задачи #{tid} → новая #{new_id}")
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
    q = update.callback_query; await q.answer()
    field = q.data.split(":")[1]
    ctx.user_data["edit_field"] = field
    if field == "priority":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔴 Высокий", callback_data="epv:high"),
            InlineKeyboardButton("🟡 Средний",  callback_data="epv:medium"),
            InlineKeyboardButton("🟢 Низкий",   callback_data="epv:low"),
        ]])
        await q.edit_message_text("⚡ Новый приоритет:", reply_markup=kb)
        return EDIT_VAL
    if field == "category":
        rows = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📌')} {c}", callback_data=f"epv:{c}")]
                for c in db.CATEGORIES]
        await q.edit_message_text("📁 Новая категория:", reply_markup=InlineKeyboardMarkup(rows))
        return EDIT_VAL
    prompts = {"title": "📝 Новое название:", "deadline": "📅 Новый дедлайн *ДД.ММ.ГГГГ* (или «нет»):",
               "notes": "📝 Новая заметка (или «нет»):"}
    await q.edit_message_text(prompts[field], parse_mode="Markdown")
    return EDIT_VAL


async def edit_recv_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    field = ctx.user_data.get("edit_field")
    tid   = ctx.user_data.get("edit_id")
    raw   = update.message.text.strip()
    value: str | None = raw
    if field == "deadline":
        if raw.lower() in ("нет", "-"):
            value = None
        else:
            try:
                value = datetime.strptime(raw, "%d.%m.%Y").strftime("%Y-%m-%d")
            except ValueError:
                await update.message.reply_text("❌ Формат: *ДД.ММ.ГГГГ*. Попробуй снова:",
                                                parse_mode="Markdown")
                return EDIT_VAL
    elif field == "notes":
        value = None if raw.lower() in ("нет", "-") else raw
    db.update_task(tid, update.effective_user.id, **{field: value})
    await update.message.reply_text("✅ Задача обновлена!")
    ctx.user_data.clear()
    return ConversationHandler.END


async def edit_recv_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    field = ctx.user_data.get("edit_field")
    tid   = ctx.user_data.get("edit_id")
    value = q.data.split(":", 1)[1]
    db.update_task(tid, q.from_user.id, **{field: value})
    await q.edit_message_text("✅ Задача обновлена!")
    ctx.user_data.clear()
    return ConversationHandler.END


# ── /find /tag ────────────────────────────────────────────────

async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /find <текст>"); return
    query = " ".join(ctx.args)
    tasks = db.search_tasks(update.effective_user.id, query)
    if not tasks:
        await update.message.reply_text(f"🔍 По запросу «{query}» ничего не найдено.")
        return
    lines = [f"🔍 *«{query}»:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=tasks_keyboard(tasks)
    )


async def cmd_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /tag <тег>  (без #)"); return
    tag = ctx.args[0].lstrip("#")
    tasks = db.get_tasks_by_tag(update.effective_user.id, tag)
    if not tasks:
        await update.message.reply_text(f"🏷 Задач с тегом #{tag} не найдено.")
        return
    lines = [f"🏷 *#{tag}:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=tasks_keyboard(tasks)
    )


# ── /stats /achievements ──────────────────────────────────────

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = db.get_stats(update.effective_user.id)
    pct = round(s["done_all"] / s["total"] * 100) if s["total"] else 0
    streak_line = f"🔥 *{s['streak']} дн подряд!*" if s["streak"] > 1 else f"{s['streak']} дн"
    best = s["best_streak"]
    await update.message.reply_text(
        f"📊 *Твоя статистика:*\n\n"
        f"📋 Всего задач: {s['total']}\n"
        f"⬜ Активных: {s['active']}\n"
        f"⚠️ Просрочено: {s['overdue']}\n\n"
        f"✅ Выполнено всего: {s['done_all']} ({pct}%)\n"
        f"✅ За 7 дней: {s['done_week']}\n"
        f"✅ За 30 дней: {s['done_month']}\n\n"
        f"⚡ Стрик: {streak_line}\n"
        f"🏅 Рекорд стрика: {best} дн",
        parse_mode="Markdown",
    )


async def cmd_achievements(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.check_achievements(user_id)
    unlocked = set(db.get_achievements(user_id))
    lines = ["🏆 *Достижения:*\n"]
    for key, (emoji, name, desc) in db.ACHIEVEMENTS.items():
        if key in unlocked:
            lines.append(f"✅ {emoji} *{name}* — {desc}")
        else:
            lines.append(f"🔒 ~~{name}~~ — {desc}")
    lines.append(f"\n_Разблокировано: {len(unlocked)}/{len(db.ACHIEVEMENTS)}_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /categories ───────────────────────────────────────────────

async def cmd_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = db.get_categories_stats(update.effective_user.id)
    if not stats:
        await update.message.reply_text("📁 Категорий нет."); return
    lines = ["📁 *Категории:*\n"]
    rows = []
    for s in stats:
        if s["active"] > 0:
            cat = s["category"]
            lines.append(f"{CAT_EMOJI.get(cat,'📌')} {cat}: {s['active']} активных")
            rows.append([InlineKeyboardButton(
                f"{CAT_EMOJI.get(cat,'📌')} {cat} ({s['active']})",
                callback_data=f"showcat:{cat}",
            )])
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ── /subtasks conversation ────────────────────────────────────

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
    await update.message.reply_text("➕ Напиши название подзадачи или /cancel:")
    return SUB_TITLE


async def _show_subtasks(msg, task_id: int, task_title: str):
    subs = db.get_subtasks(task_id)
    lines = [f"📌 *{task_title}*\n"]
    rows = []
    if not subs:
        lines.append("_Подзадач пока нет_")
    for s in subs:
        lines.append(f"{'✅' if s['done'] else '⬜'} {s['title']}")
        rows.append([
            InlineKeyboardButton(
                f"{'↩️' if s['done'] else '✅'} {s['title'][:22]}",
                callback_data=f"sub_toggle:{s['id']}:{task_id}",
            ),
            InlineKeyboardButton("🗑", callback_data=f"sub_del:{s['id']}:{task_id}"),
        ])
    await msg.reply_text("\n".join(lines), parse_mode="Markdown",
                         reply_markup=InlineKeyboardMarkup(rows) if rows else None)


async def recv_subtask_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tid = ctx.user_data.get("sub_task_id")
    db.add_subtask(tid, update.message.text.strip())
    task = db.get_task(tid, update.effective_user.id)
    await _show_subtasks(update.message, tid, task["title"] if task else "Задача")
    await update.message.reply_text("➕ Ещё подзадачу или /cancel:")
    return SUB_TITLE


# ── /templates ────────────────────────────────────────────────

async def cmd_templates(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    templates = db.get_templates(update.effective_user.id)
    if not templates:
        await update.message.reply_text(
            "📋 Шаблонов нет.\n"
            "При создании задачи через /add предложу сохранить её как шаблон."
        )
        return
    lines = ["📋 *Шаблоны:*\n"]
    rows = []
    for t in templates:
        lines.append(f"• {t['name']} — {PRI_EMOJI[t['priority']]} {t['title']}")
        rows.append([
            InlineKeyboardButton(f"➕ {t['name']}", callback_data=f"tmpl_use:{t['id']}"),
            InlineKeyboardButton("🗑",              callback_data=f"tmpl_del:{t['id']}"),
        ])
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ── /settings ─────────────────────────────────────────────────

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = db.get_settings(user_id)
    times = s["notify_times"]
    days  = s.get("notify_days_before", 1)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 Изменить время уведомлений", callback_data="sett:time")],
        [InlineKeyboardButton("За 1 день", callback_data="sett_days:1"),
         InlineKeyboardButton("За 2 дня",  callback_data="sett_days:2"),
         InlineKeyboardButton("За 3 дня",  callback_data="sett_days:3"),
         InlineKeyboardButton("За 7 дней", callback_data="sett_days:7")],
    ])
    await update.message.reply_text(
        f"⚙️ *Настройки*\n\n"
        f"🕐 Уведомления: *{times}*\n"
        f"📅 Предупреждать за: *{days} дн до дедлайна*\n\n"
        f"Выбери что изменить:",
        parse_mode="Markdown", reply_markup=kb,
    )
    return SETT_MENU


async def sett_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "sett:time":
        await q.edit_message_text(
            "🕐 Введи время уведомлений через запятую.\n"
            "Пример: `09:00,13:00,21:00`",
            parse_mode="Markdown",
        )
        return SETT_TIME
    return SETT_MENU


async def recv_sett_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    valid = []
    for t in raw.split(","):
        try:
            datetime.strptime(t.strip(), "%H:%M")
            valid.append(t.strip())
        except ValueError:
            pass
    if not valid:
        await update.message.reply_text("❌ Формат: `09:00,21:00`", parse_mode="Markdown")
        return SETT_TIME
    db.update_settings(update.effective_user.id, notify_times=",".join(valid))
    await update.message.reply_text(
        f"✅ Уведомления настроены: *{', '.join(valid)}*\n"
        f"Буду присылать напоминания каждый день в это время!",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── /export ───────────────────────────────────────────────────

async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_all_tasks_csv(update.effective_user.id)
    if not tasks:
        await update.message.reply_text("📭 Нет задач для экспорта."); return
    buf = io.StringIO()
    fields = ["id", "title", "priority", "category", "tags",
              "deadline", "notes", "repeat", "done", "completed_at", "created_at"]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for t in tasks:
        writer.writerow({k: t.get(k, "") for k in fields})
    buf.seek(0)
    fname = f"tasks_{date.today().isoformat()}.csv"
    await update.message.reply_document(
        document=InputFile(io.BytesIO(buf.read().encode("utf-8-sig")), filename=fname),
        caption=f"📤 Экспорт — {len(tasks)} задач",
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
        if task:
            rep = " 🔁 Следующая задача создана!" if task.get("repeat") != "none" else ""
            try:
                await q.message.reply_photo(
                    photo=PHOTO_DONE,
                    caption=f"✅ *Задача #{tid} выполнена!*{rep}\n📌 {task['title']}",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
            new_ach = db.check_achievements(user_id)
            for key in new_ach:
                emoji, name, _ = db.ACHIEVEMENTS[key]
                try:
                    await q.message.reply_text(
                        f"🏆 *Достижение!* {emoji} *{name}*", parse_mode="Markdown"
                    )
                except Exception:
                    pass

    elif data.startswith("del:"):
        db.delete_task(int(data.split(":")[1]), user_id)

    elif data.startswith("snooze1:"):
        tid = int(data.split(":")[1])
        db.snooze_task(tid, user_id, days=1)
        await q.answer("💤 Отложено на 1 день", show_alert=True)

    elif data.startswith("snooze_all:"):
        days = int(data.split(":")[1])
        count = db.snooze_overdue(user_id, days)
        await q.answer(f"💤 {count} просроченных задач отложено на {days} дн", show_alert=True)

    elif data.startswith("edit:"):
        tid = int(data.split(":")[1])
        task = db.get_task(tid, user_id)
        if task:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Название",  callback_data=f"qef:{tid}:title"),
                 InlineKeyboardButton("⚡ Приоритет", callback_data=f"qef:{tid}:priority")],
                [InlineKeyboardButton("📅 Дедлайн",   callback_data=f"qef:{tid}:deadline")],
            ])
            await q.message.reply_text(f"{task_detail(task)}\n\n✏️ Что изменить?",
                                       parse_mode="Markdown", reply_markup=kb)
        return

    elif data.startswith("sort:"):
        sort_by = data.split(":")[1]
        db.update_settings(user_id, sort_by=sort_by)
        tasks = db.get_tasks(user_id, done=False, sort_by=sort_by)
        lines = ["📋 *Активные задачи:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
        kb = tasks_keyboard(tasks)
        sort_row = sort_keyboard(sort_by)
        combined = InlineKeyboardMarkup(kb.inline_keyboard + sort_row.inline_keyboard)
        try:
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=combined)
        except Exception:
            pass
        return

    elif data.startswith("showcat:"):
        cat = data.split(":", 1)[1]
        tasks = db.get_tasks(user_id, done=False, category=cat)
        lines = [f"📁 *{CAT_EMOJI.get(cat,'📌')} {cat}:*\n"] + \
                [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
        await q.message.reply_text("\n".join(lines), parse_mode="Markdown",
                                   reply_markup=tasks_keyboard(tasks))
        return

    elif data.startswith("tmpl_save:"):
        tid = int(data.split(":")[1])
        ctx.user_data["tmpl_task_id"] = tid
        await q.message.reply_text("💾 Введи название для шаблона:")
        # We store state in user_data, handle in message handler below
        ctx.user_data["awaiting_tmpl_name"] = True
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    elif data == "tmpl_skip":
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    elif data.startswith("tmpl_use:"):
        tid = int(data.split(":")[1])
        tmpl = db.get_template(tid, user_id)
        if tmpl:
            new_id = db.add_task(user_id, tmpl["title"], tmpl["priority"], tmpl["category"],
                                 None, tmpl.get("notes"), tmpl.get("repeat", "none"))
            await q.message.reply_text(
                f"✅ Задача #{new_id} создана из шаблона *{tmpl['name']}*!",
                parse_mode="Markdown",
            )
        return

    elif data.startswith("tmpl_del:"):
        tid = int(data.split(":")[1])
        db.delete_template(tid, user_id)
        await q.answer("🗑 Шаблон удалён", show_alert=False)
        templates = db.get_templates(user_id)
        if not templates:
            try:
                await q.edit_message_text("📋 Шаблонов нет.")
            except Exception:
                pass
            return
        lines = ["📋 *Шаблоны:*\n"]
        rows = []
        for t in templates:
            lines.append(f"• {t['name']} — {PRI_EMOJI[t['priority']]} {t['title']}")
            rows.append([
                InlineKeyboardButton(f"➕ {t['name']}", callback_data=f"tmpl_use:{t['id']}"),
                InlineKeyboardButton("🗑",              callback_data=f"tmpl_del:{t['id']}"),
            ])
        try:
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))
        except Exception:
            pass
        return

    elif data.startswith("sub_toggle:"):
        _, sid, tid = data.split(":")
        db.toggle_subtask(int(sid))
        task = db.get_task(int(tid), user_id)
        subs = db.get_subtasks(int(tid))
        lines = [f"📌 *{task['title'] if task else 'Задача'}*\n"]
        rows = []
        for s in subs:
            lines.append(f"{'✅' if s['done'] else '⬜'} {s['title']}")
            rows.append([
                InlineKeyboardButton(f"{'↩️' if s['done'] else '✅'} {s['title'][:22]}",
                                     callback_data=f"sub_toggle:{s['id']}:{tid}"),
                InlineKeyboardButton("🗑", callback_data=f"sub_del:{s['id']}:{tid}"),
            ])
        try:
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))
        except Exception:
            pass
        return

    elif data.startswith("sub_del:"):
        _, sid, tid = data.split(":")
        db.delete_subtask(int(sid))
        task = db.get_task(int(tid), user_id)
        subs = db.get_subtasks(int(tid))
        lines = [f"📌 *{task['title'] if task else 'Задача'}*\n"]
        rows = []
        if not subs:
            lines.append("_Подзадач нет_")
        for s in subs:
            lines.append(f"{'✅' if s['done'] else '⬜'} {s['title']}")
            rows.append([
                InlineKeyboardButton(f"{'↩️' if s['done'] else '✅'} {s['title'][:22]}",
                                     callback_data=f"sub_toggle:{s['id']}:{tid}"),
                InlineKeyboardButton("🗑", callback_data=f"sub_del:{s['id']}:{tid}"),
            ])
        try:
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows) if rows else None)
        except Exception:
            pass
        return

    # Refresh task list after done/del
    s = db.get_settings(user_id)
    tasks = db.get_tasks(user_id, done=False, sort_by=s.get("sort_by", "priority"))
    if not tasks:
        try:
            await q.edit_message_text("🎉 Нет активных задач!")
        except Exception:
            pass
        return
    lines = ["📋 *Активные задачи:*\n"] + [fmt_task(t, i) for i, t in enumerate(tasks, 1)]
    kb = tasks_keyboard(tasks)
    sort_row = sort_keyboard(s.get("sort_by", "priority"))
    combined = InlineKeyboardMarkup(kb.inline_keyboard + sort_row.inline_keyboard)
    try:
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=combined)
    except Exception:
        pass


async def handle_tmpl_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle template name input outside of ConversationHandler."""
    if not ctx.user_data.get("awaiting_tmpl_name"):
        return
    ctx.user_data["awaiting_tmpl_name"] = False
    tid = ctx.user_data.pop("tmpl_task_id", None)
    name = update.message.text.strip()
    if not tid:
        return
    task = db.get_task(tid, update.effective_user.id)
    if task and db.save_template(update.effective_user.id, name, task):
        await update.message.reply_text(f"💾 Шаблон *«{name}»* сохранён! Используй /templates",
                                        parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Не удалось сохранить шаблон.")


# ── Notifications ─────────────────────────────────────────────

async def send_notification(app: Application, user_id: int, is_morning: bool = False):
    tasks = db.get_tasks_to_notify(user_id)
    if not any(tasks.values()):
        return

    has_overdue = bool(tasks["overdue"])

    lines = ["🔔 *Напоминание о задачах*\n"]

    if is_morning:
        lines.append(f"💡 _{get_daily_quote()}_\n")

    if tasks["overdue"]:
        lines.append(f"⚠️ *Просрочено — {len(tasks['overdue'])}:*")
        for t in tasks["overdue"]:
            dl = datetime.strptime(t["deadline"], "%Y-%m-%d").date()
            days_ago = (date.today() - dl).days
            lines.append(f"  {PRI_EMOJI[t['priority']]} {t['title']} (+{days_ago} дн)")
        lines.append("")

    if tasks["today"]:
        lines.append(f"📅 *На сегодня — {len(tasks['today'])}:*")
        for t in tasks["today"]:
            lines.append(f"  {PRI_EMOJI[t['priority']]} {t['title']}")
        lines.append("")

    if tasks["soon"]:
        lines.append(f"⏰ *Скоро — {len(tasks['soon'])}:*")
        for t in tasks["soon"]:
            lines.append(f"  {PRI_EMOJI[t['priority']]} {t['title']}{fmt_deadline(t['deadline'])}")

    lines.append("\n📋 /list · 🎯 /focus")

    kb = None
    if has_overdue:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💤 Отложить все просроченные на 1 день",
                                 callback_data="snooze_all:1"),
        ]])

    try:
        if has_overdue:
            await app.bot.send_photo(
                chat_id=user_id,
                photo=PHOTO_OVERDUE,
                caption="\n".join(lines),
                parse_mode="Markdown",
                reply_markup=kb,
            )
        else:
            await app.bot.send_message(
                chat_id=user_id, text="\n".join(lines),
                parse_mode="Markdown", reply_markup=kb,
            )
        log.info(f"Уведомление → {user_id}")
    except Exception as e:
        log.error(f"Ошибка уведомления {user_id}: {e}")


async def check_and_notify(app: Application):
    now = datetime.now()
    db.cleanup_old_logs()
    for user_id in db.get_all_active_user_ids():
        settings = db.get_settings(user_id)
        times = [t.strip() for t in settings["notify_times"].split(",")]
        for nt in times:
            if not nt:
                continue
            try:
                nt_h, nt_m = map(int, nt.split(":"))
                nt_dt = now.replace(hour=nt_h, minute=nt_m, second=0, microsecond=0)
                if abs((now - nt_dt).total_seconds()) <= 600 and not db.was_notified(user_id, nt):
                    is_morning = nt_h < 12
                    await send_notification(app, user_id, is_morning=is_morning)
                    db.log_notification(user_id, nt)
                    break
            except Exception as e:
                log.error(f"notify check error {user_id}: {e}")


# ── App setup ─────────────────────────────────────────────────

async def post_init(app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_notify, "interval", minutes=10, args=[app], id="notify")
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    log.info("Планировщик запущен (каждые 10 мин)")


async def post_shutdown(app: Application):
    s = app.bot_data.get("scheduler")
    if s and s.running:
        s.shutdown(wait=False)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан!")
    db.init_db()

    req = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    app = (Application.builder().token(BOT_TOKEN).request(req)
           .post_init(post_init).post_shutdown(post_shutdown).build())

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_title)],
            PRIORITY: [CallbackQueryHandler(recv_priority,   pattern=r"^pri:")],
            CATEGORY: [CallbackQueryHandler(recv_category,   pattern=r"^cat:")],
            DEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_deadline_text),
                CallbackQueryHandler(recv_deadline_cb, pattern=r"^dl:"),
            ],
            NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_notes),
                CommandHandler("skip", skip_notes),
            ],
            REPEAT: [CallbackQueryHandler(recv_repeat, pattern=r"^rep:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("edit", cmd_edit)],
        states={
            EDIT_FIELD: [CallbackQueryHandler(edit_select_field, pattern=r"^ef:")],
            EDIT_VAL:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_recv_text),
                CallbackQueryHandler(edit_recv_cb, pattern=r"^epv:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    sett_conv = ConversationHandler(
        entry_points=[CommandHandler("settings", cmd_settings)],
        states={
            SETT_MENU: [CallbackQueryHandler(sett_select, pattern=r"^sett:")],
            SETT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_sett_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    sub_conv = ConversationHandler(
        entry_points=[CommandHandler("subtasks", cmd_subtasks)],
        states={
            SUB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_subtask_title)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("q",            cmd_quick))
    app.add_handler(add_conv)
    app.add_handler(edit_conv)
    app.add_handler(sett_conv)
    app.add_handler(sub_conv)
    app.add_handler(CommandHandler("list",         cmd_list))
    app.add_handler(CommandHandler("all",          cmd_all))
    app.add_handler(CommandHandler("today",        cmd_today))
    app.add_handler(CommandHandler("upcoming",     cmd_upcoming))
    app.add_handler(CommandHandler("archive",      cmd_archive))
    app.add_handler(CommandHandler("focus",        cmd_focus))
    app.add_handler(CommandHandler("done",         cmd_done))
    app.add_handler(CommandHandler("undone",       cmd_undone))
    app.add_handler(CommandHandler("delete",       cmd_delete))
    app.add_handler(CommandHandler("copy",         cmd_copy))
    app.add_handler(CommandHandler("find",         cmd_find))
    app.add_handler(CommandHandler("tag",          cmd_tag))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("achievements", cmd_achievements))
    app.add_handler(CommandHandler("categories",   cmd_categories))
    app.add_handler(CommandHandler("templates",    cmd_templates))
    app.add_handler(CommandHandler("export",       cmd_export))
    app.add_handler(CallbackQueryHandler(button_callback))
    # Template name handler (after /add completes)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_tmpl_name
    ))

    log.info("Бот запущен!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
