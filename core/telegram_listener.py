"""
Telegram tip listener — receives tips from multiple Telegram channels and forwards to orchestrator.
Supports multiple tipster channels with per-channel tipster identification.
"""
import asyncio
import os
from telethon import TelegramClient, events
from PIL import Image
import pytesseract

from core.logger import setup_logger
from core.tip_parser import parse_generic_tip

log = setup_logger("telegram", "logs/multibot.log")


class TelegramListener:
    def __init__(self, api_id: int, api_hash: str, bot_token: str, chat_id: int,
                 session_file: str, tesseract_path: str, on_tip_callback=None,
                 tipster_channels: dict = None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.chat_id = chat_id  # Command/notification channel
        self.session_file = session_file
        self.tesseract_path = tesseract_path
        self.on_tip = on_tip_callback
        self.client = None
        self.bot_enabled = True

        # Map of channel_id -> tipster name
        self.tipster_channels = tipster_channels or {}

        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

    def _get_listen_chats(self) -> list:
        """Build list of all chat IDs to listen to."""
        chats = [self.chat_id] if self.chat_id else []
        for channel_id in self.tipster_channels:
            if channel_id not in chats:
                chats.append(channel_id)
        return chats

    async def start(self):
        """Start the Telegram client and listen for messages."""
        os.makedirs(os.path.dirname(self.session_file), exist_ok=True)
        self.client = TelegramClient(self.session_file, self.api_id, self.api_hash)
        await self.client.start(bot_token=self.bot_token)
        log.info("Telegram client started")

        listen_chats = self._get_listen_chats()

        @self.client.on(events.NewMessage(chats=listen_chats))
        async def handler(event):
            await self._handle_message(event)

        channel_count = len(self.tipster_channels)
        log.info(f"Listening on {len(listen_chats)} chat(s) ({channel_count} tipster channel(s))")

    async def _handle_message(self, event):
        """Process incoming Telegram messages."""
        try:
            text = ""
            source_chat_id = event.chat_id

            # If message has a photo, do OCR
            if event.message.photo:
                log.info("Photo message received! Processing with OCR...")
                img_path = "images/image.jpg"
                os.makedirs("images", exist_ok=True)
                await event.message.download_media(file=img_path)
                text = self._ocr_image(img_path)
                log.info(f"OCR text: {text}")

            elif event.message.text:
                text = event.message.text.strip()
                log.info(f"Text message received: {text[:100]}")

            if not text:
                return

            # Commands only from the main chat
            text_lower = text.lower().strip()
            if source_chat_id == self.chat_id:
                if await self._handle_command(text_lower, event):
                    return

            # Parse as a tip
            if not self.bot_enabled:
                log.info("Bot is disabled, ignoring tip")
                if source_chat_id == self.chat_id:
                    await self._reply(event, "Bot is disabled!")
                return

            tip_data = parse_generic_tip(text)
            tip_data["raw"] = text
            tip_data["message_id"] = event.message.id

            # Tag with tipster name from channel mapping
            if source_chat_id in self.tipster_channels:
                tip_data["tipster"] = self.tipster_channels[source_chat_id]
                log.info(f"Tip from channel {source_chat_id} -> tipster: {tip_data['tipster']}")

            log.info(f"Parsed tip: {tip_data}")

            if self.on_tip:
                await self.on_tip(tip_data)

        except Exception as e:
            log.error(f"Message handler error: {e}")

    def _ocr_image(self, image_path: str) -> str:
        """Extract text from image using Tesseract OCR."""
        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, config='--oem 3 --psm 6')
            return text.strip()
        except Exception as e:
            log.error(f"OCR error: {e}")
            return ""

    async def _handle_command(self, text: str, event) -> bool:
        """Handle bot commands. Returns True if it was a command."""
        if text == "ping":
            await self._reply(event, "Pong!")
            return True

        if text == "bot enable":
            self.bot_enabled = True
            await self._reply(event, "Bot enabled!")
            return True

        if text == "bot disable":
            self.bot_enabled = False
            await self._reply(event, "Bot disabled!")
            return True

        if text == "bot status":
            status = "enabled" if self.bot_enabled else "disabled"
            channels = len(self.tipster_channels)
            await self._reply(event, f"Bot is {status} | {channels} tipster channel(s)")
            return True

        if text == "balance":
            if self.on_tip:
                await self.on_tip({"command": "balance"})
            return True

        if text == "settings":
            if self.on_tip:
                await self.on_tip({"command": "settings"})
            return True

        if text == "screenshot":
            if self.on_tip:
                await self.on_tip({"command": "screenshot"})
            return True

        if text == "reload":
            if self.on_tip:
                await self.on_tip({"command": "reload"})
            return True

        if text.startswith("switch account"):
            if self.on_tip:
                await self.on_tip({"command": "switch_account"})
            return True

        if text == "channels":
            if self.tipster_channels:
                lines = ["Active tipster channels:"]
                for cid, name in self.tipster_channels.items():
                    lines.append(f"  {name}: {cid}")
                await self._reply(event, "\n".join(lines))
            else:
                await self._reply(event, "No tipster channels configured")
            return True

        if text == "commands":
            cmds = (
                "Available commands:\n"
                "- ping: Check if bot is running\n"
                "- bot enable/disable/status\n"
                "- balance: Get current balance\n"
                "- screenshot: Get browser screenshot\n"
                "- reload: Reload browser pages\n"
                "- settings: Show current settings\n"
                "- channels: List tipster channels\n"
                "- switch account: Switch active profile"
            )
            await self._reply(event, cmds)
            return True

        return False

    async def _reply(self, event, text: str):
        """Reply to a Telegram message."""
        try:
            await event.reply(text)
        except Exception as e:
            log.error(f"Reply error: {e}")

    async def send_message(self, text: str):
        """Send a message to the configured chat."""
        if self.client:
            try:
                await self.client.send_message(self.chat_id, text)
            except Exception as e:
                log.error(f"Send message error: {e}")

    async def send_photo(self, path: str, caption: str = ""):
        """Send a photo to the configured chat."""
        if self.client:
            try:
                await self.client.send_file(self.chat_id, path, caption=caption)
            except Exception as e:
                log.error(f"Send photo error: {e}")

    async def stop(self):
        """Disconnect the Telegram client."""
        if self.client:
            await self.client.disconnect()
            log.info("Telegram client stopped")
