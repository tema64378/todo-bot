"""Entry point: runs FastAPI (uvicorn) in a thread + Telegram bot in asyncio."""
from __future__ import annotations

import asyncio
import logging
import os
import threading

import uvicorn

import database as db

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def _start_uvicorn(port: int) -> None:
    """Run uvicorn in its own thread with its own event loop."""
    from api import app as fastapi_app
    log.info("Starting web server on port %d", port)
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="info")


async def _run_bot_with_retry() -> None:
    """Run bot, restart on errors."""
    while True:
        try:
            from bot import create_app
            from telegram import Update

            ptb_app = create_app()
            async with ptb_app:
                await ptb_app.start()
                await ptb_app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=Update.ALL_TYPES,
                )
                log.info("Bot polling started")
                await asyncio.Event().wait()  # block until cancelled
        except asyncio.CancelledError:
            log.info("Bot task cancelled, shutting down")
            break
        except Exception as e:
            log.error("Bot crashed: %s. Restarting in 15s...", e)
            await asyncio.sleep(15)


async def _main() -> None:
    db.init_db()

    port = int(os.getenv("PORT", 8080))
    web_thread = threading.Thread(
        target=_start_uvicorn,
        args=(port,),
        daemon=True,
        name="uvicorn",
    )
    web_thread.start()
    log.info("Web thread started")

    await _run_bot_with_retry()


if __name__ == "__main__":
    asyncio.run(_main())
