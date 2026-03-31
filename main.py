"""Entry point: runs FastAPI (uvicorn) + Telegram bot concurrently."""
from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

import database as db

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


async def _run_bot_with_retry():
    """Run bot in background, restart on errors."""
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
            log.error(f"Bot crashed: {e}. Restarting in 15s...")
            await asyncio.sleep(15)


async def _main():
    db.init_db()

    from api import app as fastapi_app

    port = int(os.getenv("PORT", 8080))
    config = uvicorn.Config(
        fastapi_app, host="0.0.0.0", port=port, log_level="info"
    )
    server = uvicorn.Server(config)

    # Bot runs as background task — its failure won't kill the web server
    bot_task = asyncio.create_task(_run_bot_with_retry())

    # Uvicorn is the primary blocking task
    await server.serve()

    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(_main())
