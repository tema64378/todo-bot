from __future__ import annotations

import logging
import os
from datetime import datetime, date

from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import database as db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
log = logging.getLogger(__name__)

# Conversation states
TITLE, PRIORITY, DEADLINE = range(3)

PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
PRIORITY_LABEL = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def fmt_task(task: dict, idx: int | None = None) -> str:
    prefix = f"{idx}. " if idx is not None else ""
    done_mark = "✅" if task["done"] else "⬜"
    pri = PRIORITY_EMOJI[task["priority"]]
    title = task["title"]
    deadline_str = ""
    if task["deadline"]:
        try:
            dl = datetime.strptime(task["deadline"], "%Y-%m-%d")
            delta = (dl.date() - date.today()).days
            if delta < 0:
                deadline_str = f"  ⚠️ просрочено ({dl.strftime('%d.%m.%Y')})"
            elif delta == 0:
                deadline_str = f"  🔔 сегодня!"
            elif delta == 1:
                deadline_str = f"  ⏰ завтра"
            else:
                deadline_str = f"  📅 {dl.strftime('%d.%m.%Y')}"
        except ValueError:
            deadline_str = f"  📅 {task['deadline']}"
    return f"{prefix}{done_mark} {pri} {title}{deadline_str}"


def tasks_keyboard(tasks: list[dict]) -> InlineKeyboardMarkup:
    """Keyboard with each task as a button (to mark done / delete)."""
    rows = []
    for t in tasks:
        if not t["done"]:
            rows.append([
                InlineKeyboardButton(f"✅ #{t['id']} выполнено", callback_data=f"done:{t['id']}"),
                InlineKeyboardButton(f"🗑 #{t['id']}", callback_data=f"del:{t['id']}"),
            ])
    return InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Привет! Я твой планировщик задач.*\n\n"
        "Что я умею:\n"
        "➕ /add — добавить задачу\n"
        "📋 /list — список активных задач\n"
        "📆 /today — задачи на сегодня\n"
        "📅 /upcoming — ближайшие задачи\n"
        "✅ /done — отметить выполненной\n"
        "🗑 /delete — удалить задачу\n"
        "📊 /all — все задачи включая выполненные\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────
# /add  (ConversationHandler)
# ─────────────────────────────────────────────

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Введи название задачи:")
    return TITLE


async def received_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["title"] = update.message.text.strip()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔴 Высокий", callback_data="pri:high"),
            InlineKeyboardButton("🟡 Средний", callback_data="pri:medium"),
            InlineKeyboardButton("🟢 Низкий",  callback_data="pri:low"),
        ]
    ])
    await update.message.reply_text("⚡ Выбери приоритет:", reply_markup=keyboard)
    return PRIORITY


async def received_priority(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["priority"] = query.data.split(":")[1]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Без дедлайна", callback_data="deadline:skip")]
    ])
    await query.edit_message_text(
        "📅 Введи дедлайн в формате *ДД.ММ.ГГГГ* или нажми кнопку:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return DEADLINE


async def received_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    raw = update.message.text.strip()
    deadline = None
    if raw.lower() not in ("нет", "-", "skip", "без"):
        try:
            dl = datetime.strptime(raw, "%d.%m.%Y")
            deadline = dl.strftime("%Y-%m-%d")
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат. Введи дату как *ДД.ММ.ГГГГ* или напиши «нет»:",
                parse_mode="Markdown",
            )
            return DEADLINE
    _save_task(user_id, ctx, deadline, update.message)
    return ConversationHandler.END


async def skip_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _save_task(user_id, ctx, None, query.message, edit=True)
    return ConversationHandler.END


def _save_task(user_id, ctx, deadline, msg, edit=False):
    import asyncio
    title = ctx.user_data["title"]
    priority = ctx.user_data["priority"]
    task_id = db.add_task(user_id, title, priority, deadline)
    pri_label = f"{PRIORITY_EMOJI[priority]} {PRIORITY_LABEL[priority]}"
    dl_str = datetime.strptime(deadline, "%Y-%m-%d").strftime("%d.%m.%Y") if deadline else "не задан"
    text = (
        f"✅ *Задача #{task_id} добавлена!*\n\n"
        f"📌 {title}\n"
        f"⚡ Приоритет: {pri_label}\n"
        f"📅 Дедлайн: {dl_str}"
    )
    # We schedule the coroutine correctly via the bot
    import asyncio
    if edit:
        asyncio.ensure_future(msg.edit_text(text, parse_mode="Markdown"))
    else:
        asyncio.ensure_future(msg.reply_text(text, parse_mode="Markdown"))


async def cancel_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Добавление задачи отменено.")
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /list, /all, /today, /upcoming
# ─────────────────────────────────────────────

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks(update.effective_user.id, done=False)
    if not tasks:
        await update.message.reply_text("🎉 Нет активных задач!")
        return
    lines = ["📋 *Активные задачи:*\n"]
    for i, t in enumerate(tasks, 1):
        lines.append(fmt_task(t, i))
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=tasks_keyboard(tasks),
    )


async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_tasks(update.effective_user.id)
    if not tasks:
        await update.message.reply_text("📭 Задач пока нет.")
        return
    lines = ["📊 *Все задачи:*\n"]
    for i, t in enumerate(tasks, 1):
        lines.append(fmt_task(t, i))
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=tasks_keyboard(tasks),
    )


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today = date.today().strftime("%Y-%m-%d")
    tasks = [
        t for t in db.get_tasks(update.effective_user.id, done=False)
        if t["deadline"] and t["deadline"] <= today
    ]
    if not tasks:
        await update.message.reply_text("✨ На сегодня задач нет.")
        return
    lines = ["📆 *Задачи на сегодня:*\n"]
    for i, t in enumerate(tasks, 1):
        lines.append(fmt_task(t, i))
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=tasks_keyboard(tasks),
    )


async def cmd_upcoming(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from datetime import timedelta
    in7 = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
    tasks = [
        t for t in db.get_tasks(update.effective_user.id, done=False)
        if t["deadline"] and t["deadline"] <= in7
    ]
    if not tasks:
        await update.message.reply_text("✨ Ближайших задач нет.")
        return
    lines = ["📅 *Задачи на ближайшие 7 дней:*\n"]
    for i, t in enumerate(tasks, 1):
        lines.append(fmt_task(t, i))
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=tasks_keyboard(tasks),
    )


# ─────────────────────────────────────────────
# /done, /delete (by command with ID)
# ─────────────────────────────────────────────

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /done <ID задачи>")
        return
    try:
        task_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return
    if db.mark_done(task_id, update.effective_user.id):
        await update.message.reply_text(f"✅ Задача #{task_id} выполнена!")
    else:
        await update.message.reply_text(f"❌ Задача #{task_id} не найдена или уже выполнена.")


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Использование: /delete <ID задачи>")
        return
    try:
        task_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return
    if db.delete_task(task_id, update.effective_user.id):
        await update.message.reply_text(f"🗑 Задача #{task_id} удалена.")
    else:
        await update.message.reply_text(f"❌ Задача #{task_id} не найдена.")


# ─────────────────────────────────────────────
# Inline button callbacks
# ─────────────────────────────────────────────

async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action, task_id_str = query.data.split(":")
    task_id = int(task_id_str)

    if action == "done":
        if db.mark_done(task_id, user_id):
            await query.answer(f"✅ Задача #{task_id} выполнена!", show_alert=False)
        else:
            await query.answer("Уже выполнена или не найдена.", show_alert=True)
    elif action == "del":
        if db.delete_task(task_id, user_id):
            await query.answer(f"🗑 Задача #{task_id} удалена.", show_alert=False)
        else:
            await query.answer("Не найдена.", show_alert=True)

    # Refresh the task list in the message
    tasks = db.get_tasks(user_id, done=False)
    if not tasks:
        await query.edit_message_text("🎉 Нет активных задач!")
        return
    lines = ["📋 *Активные задачи:*\n"]
    for i, t in enumerate(tasks, 1):
        lines.append(fmt_task(t, i))
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=tasks_keyboard(tasks),
    )


# ─────────────────────────────────────────────
# Scheduler: deadline notifications
# ─────────────────────────────────────────────

async def check_deadlines(app: Application):
    tasks = db.get_tasks_due_soon()
    for task in tasks:
        try:
            pri = PRIORITY_EMOJI[task["priority"]]
            dl = datetime.strptime(task["deadline"], "%Y-%m-%d")
            delta = (dl.date() - date.today()).days
            if delta < 0:
                when = f"просрочена ({dl.strftime('%d.%m.%Y')})"
            elif delta == 0:
                when = "срок истекает *сегодня*"
            else:
                when = f"срок истекает *завтра* ({dl.strftime('%d.%m.%Y')})"
            text = (
                f"🔔 *Напоминание о задаче #{task['id']}*\n\n"
                f"{pri} {task['title']}\n"
                f"⚠️ {when}\n\n"
                f"Отметить выполненной: /done {task['id']}"
            )
            await app.bot.send_message(
                chat_id=task["user_id"], text=text, parse_mode="Markdown"
            )
            db.mark_notified(task["id"])
        except Exception as e:
            log.error(f"Notification error for task {task['id']}: {e}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

async def post_init(app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_deadlines,
        trigger="interval",
        hours=1,
        args=[app],
        id="deadline_check",
    )
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    log.info("Планировщик запущен!")


async def post_shutdown(app: Application):
    scheduler = app.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан! Создай файл .env с BOT_TOKEN=...")

    db.init_db()

    from telegram.request import HTTPXRequest
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Conversation: add task
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_title)],
            PRIORITY: [CallbackQueryHandler(received_priority, pattern=r"^pri:")],
            DEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_deadline),
                CallbackQueryHandler(skip_deadline, pattern=r"^deadline:skip$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(add_conv)
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("upcoming", cmd_upcoming))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CallbackQueryHandler(button_callback, pattern=r"^(done|del):"))

    log.info("Бот запущен!")
    app.run_polling(
        drop_pending_updates=True,
        timeout=30,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
