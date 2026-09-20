"""
Multilogin X integration — launch profiles and connect Playwright via CDP.
"""
import aiohttp
import asyncio
from playwright.async_api import async_playwright
from core.logger import setup_logger

log = setup_logger("multilogin", "logs/multibot.log")


class MultiloginManager:
    def __init__(self, host: str, token: str):
        self.host = host.rstrip("/")
        self.token = token
        self.playwright = None
        self.connections = {}  # profile_id -> {browser, context, page}

    async def start_playwright(self):
        self.playwright = await async_playwright().start()

    async def stop_playwright(self):
        for pid, conn in self.connections.items():
            try:
                await conn["browser"].close()
            except Exception:
                pass
        self.connections.clear()
        if self.playwright:
            await self.playwright.stop()

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _sign_in(self, email: str, password: str) -> str:
        """Sign in to Multilogin X and get bearer token."""
        url = f"{self.host}/user/signin"
        payload = {"email": email, "password": password}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if "data" in data and "token" in data["data"]:
                    self.token = data["data"]["token"]
                    log.info("Signed in to Multilogin X")
                    return self.token
                log.error(f"Multilogin sign-in failed: {data}")
                return ""

    async def list_profiles(self, folder_id: str = "") -> list:
        """List browser profiles."""
        url = f"{self.host}/profile/search"
        params = {"is_removed": "false", "limit": 100, "offset": 0}
        if folder_id:
            params["folder_id"] = folder_id
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(), params=params) as resp:
                data = await resp.json()
                profiles = data.get("data", [])
                log.info(f"Found {len(profiles)} profiles")
                return profiles

    async def start_profile(self, profile_id: str, folder_id: str = "") -> str:
        """
        Start a Multilogin profile and return the CDP WebSocket URL.
        Returns the port or ws endpoint for Playwright connection.
        """
        url = f"{self.host}/profile/f/{folder_id}/p/{profile_id}/start?automation_type=playwright"
        if not folder_id:
            url = f"{self.host}/profile/start?automation_type=playwright&profile_id={profile_id}"

        log.info(f"Starting profile {profile_id}...")
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers()) as resp:
                data = await resp.json()
                if resp.status == 200 and "data" in data:
                    port = data["data"].get("port")
                    ws_url = data["data"].get("ws_url", "")
                    if ws_url:
                        log.info(f"Profile {profile_id} started, ws: {ws_url}")
                        return ws_url
                    elif port:
                        ws = f"ws://127.0.0.1:{port}"
                        log.info(f"Profile {profile_id} started on port {port}")
                        return ws
                log.error(f"Failed to start profile {profile_id}: {data}")
                return ""

    async def stop_profile(self, profile_id: str):
        """Stop a running Multilogin profile."""
        url = f"{self.host}/profile/stop?profile_id={profile_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    log.info(f"Profile {profile_id} stopped")
                else:
                    data = await resp.json()
                    log.error(f"Failed to stop profile {profile_id}: {data}")

    async def connect_playwright(self, profile_id: str, ws_endpoint: str):
        """Connect Playwright to a running Multilogin profile via CDP."""
        if not self.playwright:
            await self.start_playwright()

        try:
            browser = await self.playwright.chromium.connect_over_cdp(ws_endpoint)
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
                pages = context.pages
                page = pages[0] if pages else await context.new_page()
            else:
                context = await browser.new_context()
                page = await context.new_page()

            self.connections[profile_id] = {
                "browser": browser,
                "context": context,
                "page": page,
            }
            log.info(f"Playwright connected to profile {profile_id}")
            return page
        except Exception as e:
            log.error(f"Failed to connect Playwright to {profile_id}: {e}")
            return None

    async def launch_and_connect(self, profile_id: str, folder_id: str = ""):
        """Start a profile and connect Playwright in one call."""
        ws = await self.start_profile(profile_id, folder_id)
        if not ws:
            return None
        # Give the browser a moment to initialize
        await asyncio.sleep(3)
        return await self.connect_playwright(profile_id, ws)

    def get_page(self, profile_id: str):
        """Get the Playwright page for a profile."""
        conn = self.connections.get(profile_id)
        return conn["page"] if conn else None
