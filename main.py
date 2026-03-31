"""Entry point: runs FastAPI (uvicorn) + Telegram bot concurrently."""
from __future__ import annotations

import asyncio
import logging
import os
import signal

import uvicorn
from telegram import Update

import database as db

log = logging.getLogger(__name__)


async def _run_uvicorn():
    from api import app as fastapi_app
    port = int(os.getenv("PORT", 8080))
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def _run_bot():
    from bot import create_app
    ptb_app = create_app()
    stop = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows

    async with ptb_app:
        await ptb_app.start()
        await ptb_app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        log.info("Bot polling started")
        await stop.wait()
        await ptb_app.updater.stop()
        await ptb_app.stop()


async def _main():
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )
    db.init_db()
    await asyncio.gather(_run_uvicorn(), _run_bot())


if __name__ == "__main__":
    asyncio.run(_main())
