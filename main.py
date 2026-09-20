"""
MultiBot365 — Multi-profile Bet365 automation with Multilogin integration.
"""
import asyncio
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from core.logger import setup_logger
from core.database import init_db
from core.multilogin import MultiloginManager
from core.orchestrator import Orchestrator
from core.telegram_listener import TelegramListener

log = setup_logger("main", config.LOG_FILE)


async def main():
    log.info("=" * 60)
    log.info("MultiBot365 starting...")
    log.info("=" * 60)

    # Initialize database
    await init_db(config.DB_FILE)
    log.info("Database initialized")

    # Initialize Multilogin manager
    ml = MultiloginManager(
        host=config.MULTILOGIN_HOST,
        token=config.MULTILOGIN_TOKEN,
    )
    await ml.start_playwright()
    log.info("Playwright started")

    # Initialize orchestrator
    orchestrator = Orchestrator(
        multilogin=ml,
        profiles_config=config.PROFILES,
        tipsters_config=config.TIPSTERS,
        stagger_min=config.STAGGER_MIN_SECONDS,
        stagger_max=config.STAGGER_MAX_SECONDS,
        time_off_hours=config.TIME_OFF_HOURS,
    )

    # Launch and connect all profiles
    connected = await orchestrator.launch_all_profiles()
    if connected == 0:
        log.error("No profiles connected! Check your Multilogin config.")
        log.error("Make sure:")
        log.error("  1. Multilogin X is running")
        log.error("  2. MULTILOGIN_TOKEN is set in config.py")
        log.error("  3. Profile IDs in PROFILES are correct")
        await ml.stop_playwright()
        return

    # Login to Bet365 on all profiles
    logged_in = await orchestrator.login_all()
    if logged_in == 0:
        log.error("No profiles logged in! Check credentials.")
        await orchestrator.shutdown()
        return

    log.info(f"Ready! {logged_in} profile(s) active")

    # Setup Telegram listener
    telegram = None
    if config.TELEGRAM_API_ID and config.TELEGRAM_BOT_TOKEN:
        telegram = TelegramListener(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            bot_token=config.TELEGRAM_BOT_TOKEN,
            chat_id=config.TELEGRAM_CHAT_ID,
            session_file=config.TELEGRAM_SESSION,
            tesseract_path=config.TESSERACT_PATH,
            on_tip_callback=orchestrator.distribute_tip,
            tipster_channels=getattr(config, 'TIPSTER_CHANNELS', {}),
        )
        await telegram.start()
        await telegram.send_message(
            f"MultiBot365 started!\n{logged_in} profile(s) active"
        )
        log.info("Telegram listener active")
    else:
        log.warning("Telegram not configured — running without tip listener")
        log.warning("Set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN in config.py")

    # Keep running
    log.info("Bot is running. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(60)
            # Periodic tasks
            for name, bot in orchestrator.bots.items():
                await bot.dismiss_popups()
                await bot.handle_restrictions()
    except KeyboardInterrupt:
        log.info("Shutdown requested...")
    finally:
        if telegram:
            await telegram.send_message("MultiBot365 shutting down...")
            await telegram.stop()
        await orchestrator.shutdown()
        log.info("MultiBot365 stopped.")


if __name__ == "__main__":
    asyncio.run(main())
