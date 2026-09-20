"""
Bet365 plugin — handles all interaction with the Bet365 website.
"""
import asyncio
import random
import time
import re
from datetime import datetime
from playwright.async_api import Page, TimeoutError as PWTimeout

from plugins import bet365_selectors as S
from core.antidetect import random_point, human_delay, typing_delay
from core.logger import setup_logger
from core import database as db

log = setup_logger("bet365", "logs/multibot.log")

SCREENSHOT_DIR = "screenshots/bet365"


class Bet365:
    def __init__(self, page: Page, profile_name: str, username: str, password: str, region: str = "com"):
        self.page = page
        self.profile_name = profile_name
        self.username = username
        self.password = password
        self.region = region
        self.base_url = f"https://www.bet365.{region}"
        self.balance = 0.0
        self.unsettled_bets = 0

    # ----------------------------------------------------------------
    # POPUP HANDLING
    # ----------------------------------------------------------------
    async def dismiss_popups(self):
        """Dismiss any popups that might be blocking interaction."""
        popup_selectors = [
            (S.INTRO_POPUP_CLOSE, "Introductory Popup"),
            (S.COOKIES_ACCEPT, "Cookies"),
            (S.COOKIES_ACCEPT2, "Cookies2"),
            (S.REMAIN_LOGGED_IN, "Remain Logged In"),
            (S.REALITY_CHECK_REMAIN, "Reality Check"),
            (S.NO_THANKS, "No Thanks"),
            (S.CLOSE_BUTTON, "Close"),
            (S.CLOSE_BUTTON2, "Close2"),
            (S.LAST_LOGIN_BUTTON, "Last Login"),
            (S.NOT_INTERESTED, "Not Interested"),
            (S.INACTIVITY_LOGGED_OUT, "Inactivity Logged Out"),
        ]
        for selector, name in popup_selectors:
            try:
                el = self.page.locator(selector)
                if await el.count() > 0 and await el.first.is_visible():
                    await random_point(self.page, el.first)
                    log.info(f"[{self.profile_name}] {name} popup dismissed")
                    await human_delay(200, 500)
            except Exception:
                pass

    async def handle_restrictions(self) -> bool:
        """Handle the account restrictions modal. Returns True if it appeared."""
        try:
            modal = self.page.locator(S.RESTRICTIONS_MODAL)
            if await modal.count() > 0 and await modal.first.is_visible():
                log.warning(f"[{self.profile_name}] Account restrictions modal detected!")
                cont = self.page.locator(S.RESTRICTIONS_CONTINUE)
                if await cont.count() > 0:
                    await random_point(self.page, cont.first)
                    log.info(f"[{self.profile_name}] Restrictions continue clicked")
                return True
        except Exception:
            pass
        return False

    async def stop_video(self):
        """Stop any playing video to save resources."""
        try:
            vid = self.page.locator(S.VIDEO_PLAYING)
            if await vid.count() > 0:
                pitch = self.page.locator(S.VIDEO_PITCH_BUTTON)
                if await pitch.count() > 0:
                    await pitch.first.click()
                stop = self.page.locator(S.VIDEO_STOP_BUTTON)
                if await stop.count() > 0:
                    await stop.first.click()
                log.info(f"[{self.profile_name}] Video stopped")
        except Exception:
            pass

    # ----------------------------------------------------------------
    # LOGIN
    # ----------------------------------------------------------------
    async def is_logged_in(self) -> bool:
        """Check if we're already logged in by looking for the login button."""
        try:
            login_btn = self.page.locator(S.LOGIN_BUTTON)
            count = await login_btn.count()
            return count == 0  # If login button is NOT visible, we're logged in
        except Exception:
            return False

    async def login(self) -> bool:
        """Log into Bet365. Returns True on success."""
        log.info(f"[{self.profile_name}] Logging in...")
        try:
            await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            await self.dismiss_popups()

            # Check if already logged in
            if await self.is_logged_in():
                log.info(f"[{self.profile_name}] Already logged in!")
                await self._post_login()
                return True

            # Click login container to open login form
            login_container = self.page.locator(S.LOGIN_CONTAINER)
            if await login_container.count() > 0:
                await random_point(self.page, login_container.first)
                log.info(f"[{self.profile_name}] Login button clicked")
                await human_delay(500, 1000)

            # Wait for username field
            username_box = self.page.locator(S.USERNAME_INPUT)
            try:
                await username_box.wait_for(state="visible", timeout=10000)
            except PWTimeout:
                log.error(f"[{self.profile_name}] Login form did not appear!")
                return False

            # Type username
            await username_box.click()
            await human_delay(200, 400)
            await username_box.fill("")
            for char in self.username:
                await self.page.keyboard.type(char, delay=random.uniform(30, 100))
            log.info(f"[{self.profile_name}] Username entered")
            await human_delay(300, 600)

            # Type password
            password_box = self.page.locator(S.PASSWORD_INPUT)
            await password_box.click()
            await human_delay(200, 400)
            await password_box.fill("")
            for char in self.password:
                await self.page.keyboard.type(char, delay=random.uniform(30, 100))
            log.info(f"[{self.profile_name}] Password entered")
            await human_delay(300, 600)

            # Click login button at random point
            confirm = self.page.locator(S.CONFIRM_LOGIN_BUTTON)
            await random_point(self.page, confirm.first)
            log.info(f"[{self.profile_name}] Login button clicked in random point!")
            await human_delay(2000, 4000)

            # Verify login succeeded
            for attempt in range(15):
                await self.dismiss_popups()
                await self.handle_restrictions()

                balance_el = self.page.locator(S.BALANCE_DISPLAY)
                if await balance_el.count() > 0:
                    await self._post_login()
                    log.info(f"[{self.profile_name}] Logged in successfully! Balance: {self.balance}")
                    return True
                await asyncio.sleep(1)

            # Second attempt
            log.warning(f"[{self.profile_name}] First login attempt failed, retrying...")
            confirm2 = self.page.locator(S.CONFIRM_LOGIN_BUTTON)
            if await confirm2.count() > 0:
                await random_point(self.page, confirm2.first)
                await human_delay(3000, 5000)
                for attempt in range(10):
                    await self.dismiss_popups()
                    balance_el = self.page.locator(S.BALANCE_DISPLAY)
                    if await balance_el.count() > 0:
                        await self._post_login()
                        log.info(f"[{self.profile_name}] Logged in on 2nd try! Balance: {self.balance}")
                        return True
                    await asyncio.sleep(1)

            log.error(f"[{self.profile_name}] Failed to login after 2 tries!")
            return False

        except Exception as e:
            log.error(f"[{self.profile_name}] Login error: {e}")
            return False

    async def _post_login(self):
        """Actions after successful login — get balance, clean bet slip."""
        await self.dismiss_popups()
        await self.handle_restrictions()
        await self.get_balance()
        await self.clear_bet_slip()
        await self.stop_video()

    async def logout(self):
        """Log out of Bet365."""
        try:
            members = self.page.locator(S.MEMBERS_MENU)
            if await members.count() > 0:
                await members.first.click()
                await human_delay(500, 1000)
                logout_btn = self.page.locator(S.LOG_OUT)
                if await logout_btn.count() > 0:
                    await logout_btn.first.click()
                    log.info(f"[{self.profile_name}] Logged out")
        except Exception as e:
            log.error(f"[{self.profile_name}] Logout error: {e}")

    # ----------------------------------------------------------------
    # BALANCE
    # ----------------------------------------------------------------
    async def get_balance(self) -> float:
        """Read current balance and unsettled bets count."""
        try:
            bal = self.page.locator(S.BALANCE_DISPLAY)
            if await bal.count() > 0:
                text = await bal.first.inner_text()
                cleaned = re.sub(r'[^\d.]', '', text)
                self.balance = float(cleaned) if cleaned else 0.0

            bets = self.page.locator(S.MY_BETS_COUNT)
            if await bets.count() > 0:
                text = await bets.first.inner_text()
                self.unsettled_bets = int(re.sub(r'[^\d]', '', text)) if text.strip() else 0

            await db.record_balance(self.profile_name, self.balance, self.unsettled_bets)
        except Exception as e:
            log.error(f"[{self.profile_name}] Balance error: {e}")
        return self.balance

    # ----------------------------------------------------------------
    # NAVIGATION
    # ----------------------------------------------------------------
    async def navigate_to_sports(self):
        """Navigate to All Sports page."""
        await self.dismiss_popups()
        try:
            btn = self.page.locator(S.ALL_SPORTS)
            if await btn.count() > 0:
                await random_point(self.page, btn.first)
                log.info(f"[{self.profile_name}] Navigated to All Sports")
                await human_delay(1000, 2000)
        except Exception as e:
            log.error(f"[{self.profile_name}] Navigate to Sports error: {e}")

    async def navigate_to_inplay(self):
        """Navigate to In-Play page."""
        await self.dismiss_popups()
        try:
            btn = self.page.locator(S.IN_PLAY)
            if await btn.count() > 0:
                await random_point(self.page, btn.first)
                log.info(f"[{self.profile_name}] Navigated to In-Play")
                await human_delay(1000, 2000)
        except Exception as e:
            log.error(f"[{self.profile_name}] Navigate to In-Play error: {e}")

    # ----------------------------------------------------------------
    # BET SLIP MANAGEMENT
    # ----------------------------------------------------------------
    async def clear_bet_slip(self):
        """Clear any existing selections from the bet slip."""
        try:
            # Check for Done button (from previous bet)
            done = self.page.locator(S.DONE_BUTTON)
            if await done.count() > 0 and await done.first.is_visible():
                await done.first.click()
                await human_delay(300, 500)

            # Close insufficient funds popup
            insuf = self.page.locator(S.INSUFFICIENT_FUNDS_CLOSE)
            if await insuf.count() > 0 and await insuf.first.is_visible():
                await insuf.first.click()
                await human_delay(300, 500)

            # Remove multiple bets
            multi = self.page.locator(S.MULTIPLE_REMOVE)
            if await multi.count() > 0 and await multi.first.is_visible():
                await multi.first.click()
                await human_delay(300, 500)

            # Remove individual bets
            remove = self.page.locator(S.REMOVE_BUTTON)
            while await remove.count() > 1:
                # Close up arrow first
                up = self.page.locator(S.UP_ARROW)
                if await up.count() > 0:
                    await up.first.click()
                    await human_delay(200, 300)

                # Show options and remove all
                show = self.page.locator(S.SHOW_OPTIONS)
                if await show.count() > 0:
                    await show.first.click()
                    await human_delay(200, 300)
                    rem_all = self.page.locator(S.REMOVE_ALL)
                    if await rem_all.count() > 0:
                        await rem_all.first.click()
                        await human_delay(300, 500)
                        break
                break

            if await remove.count() == 1:
                await remove.first.click()
                await human_delay(200, 300)

        except Exception as e:
            log.debug(f"[{self.profile_name}] Clear bet slip: {e}")

    # ----------------------------------------------------------------
    # SEARCH & FIND MATCH
    # ----------------------------------------------------------------
    async def search_and_select_bet(self, search_text: str, category: str, tip: str) -> bool:
        """
        Use Bet365's search to find a bet.
        Returns True if the bet was found and clicked.
        """
        log.info(f"[{self.profile_name}] Searching for: {search_text}")
        try:
            await self.dismiss_popups()

            # Click search bar
            search_bar = self.page.locator(S.SEARCH_BAR)
            await search_bar.wait_for(state="visible", timeout=10000)
            await random_point(self.page, search_bar.first)
            await human_delay(500, 800)

            # Type search text
            search_input = self.page.locator(S.SEARCH_INPUT)
            await search_input.wait_for(state="visible", timeout=5000)
            await search_input.click()
            await human_delay(200, 400)

            for char in search_text:
                await self.page.keyboard.type(char, delay=random.uniform(30, 80))
            log.info(f"[{self.profile_name}] Search text typed")
            await human_delay(1500, 2500)

            # Check for no results
            no_results = self.page.locator(S.NO_SEARCH_RESULTS)
            if await no_results.count() > 0:
                log.warning(f"[{self.profile_name}] No search results!")
                return False

            # Look for matching bet
            cat_lower = category.lower()
            bet_selector = S.search_bet_participant(cat_lower, tip)
            bet = self.page.locator(bet_selector)

            if await bet.count() > 0:
                await random_point(self.page, bet.first)
                log.info(f"[{self.profile_name}] Bet found and clicked!")
                await human_delay(500, 1000)
                return True

            # Try View Event approach
            view_event = self.page.locator(S.VIEW_EVENT_TEXT)
            if await view_event.count() == 0:
                view_event = self.page.locator(S.VIEW_EVENT_BETS)

            if await view_event.count() > 0:
                await random_point(self.page, view_event.first)
                log.info(f"[{self.profile_name}] View Event clicked, navigating to event page")
                await human_delay(1500, 2500)
                return True  # Caller needs to find bet on event page

            log.warning(f"[{self.profile_name}] Match not found in search!")
            return False

        except Exception as e:
            log.error(f"[{self.profile_name}] Search error: {e}")
            return False

    # ----------------------------------------------------------------
    # PLACE BET
    # ----------------------------------------------------------------
    async def place_bet(self, bet_amount: float, min_odd: float = 0.0) -> dict:
        """
        Place a bet with the current selection on the bet slip.
        Returns dict with status, final_odd, and placement time.
        """
        start_time = time.time()
        result = {"status": "failed", "final_odd": 0.0, "seconds": 0.0, "message": ""}

        try:
            await self.dismiss_popups()
            await human_delay(500, 800)

            # Amount safety check
            if bet_amount <= 0:
                result["message"] = "Bet amount is 0"
                log.warning(f"[{self.profile_name}] Bet amount is 0, skipping")
                return result

            if bet_amount > 300:
                result["message"] = "Bet amount over 300"
                log.warning(f"[{self.profile_name}] Bet amount over 300, skipping")
                return result

            # Find and click stake input
            stake_box = self.page.locator(S.STAKE_INPUT)
            try:
                await stake_box.wait_for(state="visible", timeout=10000)
            except PWTimeout:
                result["message"] = "Stake box not found"
                log.error(f"[{self.profile_name}] Stake box not visible!")
                return result

            await stake_box.click()
            await human_delay(200, 400)
            log.info(f"[{self.profile_name}] Stake box clicked")

            # Type bet amount with human-like typing
            amount_str = f"{bet_amount:.2f}"
            for char in amount_str:
                await self.page.keyboard.type(char, delay=random.uniform(40, 120))
            log.info(f"[{self.profile_name}] Typing bet amount {amount_str}")
            await human_delay(500, 800)

            # Find Place Bet button
            place_btn = self.page.locator(S.PLACE_BET_BUTTON)
            try:
                await place_btn.wait_for(state="visible", timeout=10000)
            except PWTimeout:
                # Check for Update Stake
                update = self.page.locator(S.UPDATE_STAKE_BUTTON)
                if await update.count() > 0:
                    log.info(f"[{self.profile_name}] Update Stake button found")
                    await random_point(self.page, update.first)
                    await human_delay(1000, 2000)
                    await place_btn.wait_for(state="visible", timeout=10000)

            # Check if locked
            disabled = self.page.locator(S.ACCEPT_BUTTON_DISABLED)
            if await disabled.count() > 0:
                log.info(f"[{self.profile_name}] Place bet button is locked, waiting...")
                for _ in range(10):
                    await asyncio.sleep(1)
                    if await disabled.count() == 0:
                        break

            # Click Place Bet
            if await place_btn.count() > 0 and await place_btn.first.is_visible():
                await random_point(self.page, place_btn.first)
                log.info(f"[{self.profile_name}] Place bet button clicked!")
                await human_delay(2000, 3000)
            else:
                log.info(f"[{self.profile_name}] Place bet not clickable, checking accept changes...")

            # Handle odds changes / Accept Changes flow
            for attempt in range(3):
                # Check if bet was placed (Done button appears)
                done = self.page.locator(S.DONE_BUTTON)
                if await done.count() > 0:
                    result["status"] = "placed"
                    break

                # Check for accept changes
                accept_text = self.page.locator(S.ACCEPT_CHANGES_TEXT)
                if await accept_text.count() > 0:
                    text_content = await accept_text.first.inner_text()

                    if "Place Bet" in text_content:
                        # "Accept Changes and Place Bet"
                        log.info(f"[{self.profile_name}] Accept Changes AND Place Bet button found, clicking...")
                        await random_point(self.page, accept_text.first)
                        await human_delay(2000, 3000)
                    else:
                        # "Accept Changes" only (no place bet yet)
                        log.info(f"[{self.profile_name}] Accept Changes (no Place Bet) button found, clicking...")
                        await random_point(self.page, accept_text.first)
                        await human_delay(1500, 2500)

                        # Now look for Place Bet again
                        place_btn2 = self.page.locator(S.PLACE_BET_BUTTON)
                        if await place_btn2.count() > 0:
                            await random_point(self.page, place_btn2.first)
                            log.info(f"[{self.profile_name}] Place bet clicked after accept changes")
                            await human_delay(2000, 3000)

                # Check for accept message (price change info)
                msg = self.page.locator(S.ACCEPT_BUTTON_MESSAGE)
                if await msg.count() > 0:
                    msg_text = await msg.first.inner_text()
                    log.info(f"[{self.profile_name}] Accept message: {msg_text}")

                await asyncio.sleep(1)

            # Final check — did bet go through?
            done = self.page.locator(S.DONE_BUTTON)
            if await done.count() > 0:
                result["status"] = "placed"
                elapsed = time.time() - start_time
                minutes = int(elapsed // 60)
                seconds = int(elapsed % 60)
                result["seconds"] = elapsed
                log.info(f"[{self.profile_name}] Bet placed successfully in {minutes}m {seconds}s!")

                # Click Done
                await random_point(self.page, done.first)
                await human_delay(500, 800)

                # Refresh balance
                await self.get_balance()
            else:
                # Check insufficient funds
                insuf = self.page.locator(S.INSUFFICIENT_FUNDS_CLOSE)
                if await insuf.count() > 0:
                    result["message"] = "Insufficient funds"
                    log.warning(f"[{self.profile_name}] Insufficient funds!")
                    await insuf.first.click()
                else:
                    result["message"] = "Unable to place bet"
                    log.error(f"[{self.profile_name}] Bet not placed!")

                await self.clear_bet_slip()

        except Exception as e:
            result["message"] = str(e)
            log.error(f"[{self.profile_name}] Place bet error: {e}")

        return result

    # ----------------------------------------------------------------
    # EVENT PAGE NAVIGATION
    # ----------------------------------------------------------------
    async def navigate_to_event_tab(self, tab_name: str) -> bool:
        """Click a tab on the event page (Bet Builder, Player, Asian Lines, etc.)."""
        # Try pre-match style tab first
        tab_map = {
            "Bet Builder": (S.BET_BUILDER_TAB, S.IP_BET_BUILDER),
            "Player": (S.PLAYER_TAB, S.IP_PLAYER),
            "Asian Lines": (S.ASIAN_LINES_TAB, S.IP_ASIAN_LINES),
            "Corners": (S.CORNERS_TAB, S.IP_CORNERS),
            "Popular": (S.POPULAR_TAB, S.IP_POPULAR),
        }
        pre, ip = tab_map.get(tab_name, (None, None))
        if not pre:
            return False

        try:
            btn = self.page.locator(pre)
            if await btn.count() > 0:
                await random_point(self.page, btn.first)
                log.info(f"[{self.profile_name}] {tab_name} tab clicked")
                await human_delay(800, 1500)
                return True
            # Try in-play style
            btn2 = self.page.locator(ip)
            if await btn2.count() > 0:
                await random_point(self.page, btn2.first)
                log.info(f"[{self.profile_name}] {tab_name} tab clicked (in-play)")
                await human_delay(800, 1500)
                return True
            log.warning(f"[{self.profile_name}] {tab_name} tab not found!")
            return False
        except Exception as e:
            log.error(f"[{self.profile_name}] Navigate to {tab_name} error: {e}")
            return False

    async def open_category(self, category_name: str) -> bool:
        """Open a market category on the event page (e.g., Points O/U, Assists O/U)."""
        try:
            # Check if already open
            open_btn = self.page.locator(S.category_button_open(category_name))
            if await open_btn.count() > 0:
                log.info(f"[{self.profile_name}] {category_name} already open")
                # Scroll into view
                await open_btn.first.evaluate("element => element.scrollIntoView({})")
                await human_delay(300, 500)
                return True

            # Click to open
            btn = self.page.locator(S.category_button(category_name))
            if await btn.count() > 0:
                await btn.first.evaluate("element => element.scrollIntoView({})")
                await human_delay(300, 500)
                await random_point(self.page, btn.first)
                log.info(f"[{self.profile_name}] {category_name} clicked")
                await human_delay(500, 1000)
                return True

            log.warning(f"[{self.profile_name}] Category {category_name} not found!")
            return False
        except Exception as e:
            log.error(f"[{self.profile_name}] Open category error: {e}")
            return False

    async def find_player_and_select(self, category_name: str, player_name: str,
                                      line: float, direction: str = "Over") -> bool:
        """
        Find a player prop on the event page and click it.
        Used for Bet Builder and Player tab selections.
        """
        try:
            cat_selector = S.category_button(category_name)
            base = cat_selector + '"]/parent::*/parent::*/div[2]/div/div[1]/child::*'

            # Find player rows — check both BetBuilder and Participant styles
            bb_rows = f'{base}/div[2]/div/div[1]/div[contains(@class, "BetBuilder")]/div'
            p_rows = f'{base}/div[2]/div/div[1]/div[contains(@class, "Participant")]/div[2]'

            # Try BetBuilder rows first
            row_locator = self.page.locator(bb_rows)
            row_count = await row_locator.count()
            is_bb = True

            if row_count == 0:
                row_locator = self.page.locator(p_rows)
                row_count = await row_locator.count()
                is_bb = False

            log.info(f"[{self.profile_name}] Found {row_count} player rows in {category_name}")

            # Search through players
            for i in range(row_count):
                try:
                    row_text = await row_locator.nth(i).inner_text()
                    if player_name.lower() in row_text.lower():
                        log.info(f"[{self.profile_name}] Player {player_name} found at position {i+1}!")

                        # Now find the correct line/amount column
                        if is_bb:
                            amounts_sel = f'{base}/div[2]/div/div[1]/div[contains(@class, "BetBuilder")]'
                        else:
                            amounts_sel = f'{base}/div[2]/div/div[1]/div[contains(@class, "Participant")]'

                        amounts = self.page.locator(amounts_sel)
                        amounts_count = await amounts.count()
                        log.info(f"[{self.profile_name}] {amounts_count} amount options")

                        # Look for matching line value
                        for j in range(amounts_count):
                            try:
                                amount_text = await amounts.nth(j).inner_text()
                                if str(line) in amount_text:
                                    log.info(f"[{self.profile_name}] Line {line} found at position {j+1}")

                                    # Build selector for the clickable element
                                    if is_bb:
                                        click_sel = f'{base}/div[2]/div/div[{j+1}]/div[contains(@class, "BetBuilder") and not(contains(@class,"Suspended"))][{i+1}]'
                                    else:
                                        click_sel = f'{base}/div[2]/div/div[{j+1}]/div[contains(@class, "Participant") and not(contains(@class,"Suspended"))][{i+1}]'

                                    tip_el = self.page.locator(click_sel)
                                    if await tip_el.count() > 0:
                                        await random_point(self.page, tip_el.first)
                                        log.info(f"[{self.profile_name}] Player prop clicked!")
                                        await human_delay(500, 800)
                                        return True
                            except Exception:
                                continue

                        # If exact line not found, click first available for that player
                        log.warning(f"[{self.profile_name}] Exact line {line} not found, clicking first available")
                        if is_bb:
                            fallback = f'{base}/div[2]/div/div[2]/div[contains(@class, "BetBuilder") and not(contains(@class,"Suspended"))][{i+1}]'
                        else:
                            fallback = f'{base}/div[2]/div/div[2]/div[contains(@class, "Participant") and not(contains(@class,"Suspended"))][{i+1}]'
                        fb_el = self.page.locator(fallback)
                        if await fb_el.count() > 0:
                            await random_point(self.page, fb_el.first)
                            log.info(f"[{self.profile_name}] Fallback player prop clicked")
                            await human_delay(500, 800)
                            return True
                except Exception:
                    continue

            # Try "Show More" button if player not found
            show_more = self.page.locator(
                f'{cat_selector}"]/parent::*/parent::*/parent::*/parent::*//div[contains(@class, "ShowMore") and text()="Show more"]'
            )
            if await show_more.count() > 0:
                await show_more.first.click()
                log.info(f"[{self.profile_name}] Show More clicked, searching again...")
                await human_delay(800, 1200)
                # Recursive retry (once)
                return False  # Caller can retry

            log.warning(f"[{self.profile_name}] Player {player_name} not found in {category_name}")
            return False

        except Exception as e:
            log.error(f"[{self.profile_name}] Find player error: {e}")
            return False

    # ----------------------------------------------------------------
    # BET BUILDER FLOW
    # ----------------------------------------------------------------
    async def execute_bet_builder(self, match: str, team1: str, team2: str,
                                   legs: list, bet_amount: float, min_odd: float,
                                   tipster: str) -> dict:
        """
        Full bet builder placement:
        1. Search for match and navigate to event page
        2. Click Bet Builder tab
        3. Select each leg (player prop)
        4. Enter stake and place combined bet

        legs = [
            {"player": "Marcus Smart", "category": "Points O/U", "line": 14.5, "direction": "Over"},
            {"player": "Jayson Tatum", "category": "Rebounds O/U", "line": 8.5, "direction": "Over"},
        ]
        """
        log.info(f"[{self.profile_name}] === Bet Builder: {match} | {len(legs)} legs | {bet_amount} ===")

        # Ensure logged in
        if not await self.is_logged_in():
            success = await self.login()
            if not success:
                return {"status": "login_failed"}

        await self.dismiss_popups()
        await self.clear_bet_slip()

        # Search for match and go to event page
        search_text = match if match else f"{team1} {team2}".strip()
        found = await self._navigate_to_event(search_text)
        if not found:
            tip_str = " + ".join(f"{l['player']} {l['direction']} {l['line']}" for l in legs)
            await db.record_bet(
                self.profile_name, tipster, match, team1, team2, tip_str,
                "betBuilder", "", min_odd, 0.0, bet_amount, "not_found", 0.0
            )
            return {"status": "not_found"}

        # Navigate to Bet Builder or Player tab
        tab_found = await self.navigate_to_event_tab("Bet Builder")
        if not tab_found:
            tab_found = await self.navigate_to_event_tab("Player")
        if not tab_found:
            log.error(f"[{self.profile_name}] Neither Bet Builder nor Player tab found!")
            return {"status": "tab_not_found"}

        # Select each leg
        legs_selected = 0
        for i, leg in enumerate(legs):
            log.info(f"[{self.profile_name}] Selecting leg {i+1}/{len(legs)}: {leg['player']} {leg.get('direction', 'Over')} {leg['line']} ({leg['category']})")

            # Open the category
            opened = await self.open_category(leg["category"])
            if not opened:
                log.warning(f"[{self.profile_name}] Category {leg['category']} not found, trying alternatives...")
                # Try alternate names
                alt_names = {
                    "Points O/U": ["Points Over/Under", "Player Points"],
                    "Assists O/U": ["Assists Over/Under", "Player Assists"],
                    "Rebounds O/U": ["Rebounds Over/Under", "Player Rebounds"],
                    "Threes Made O/U": ["Threes Made Over/Under", "Player Threes Made"],
                }
                for alt in alt_names.get(leg["category"], []):
                    opened = await self.open_category(alt)
                    if opened:
                        break

            if not opened:
                log.error(f"[{self.profile_name}] Could not open category for leg {i+1}")
                continue

            # Find and click the player prop
            selected = await self.find_player_and_select(
                leg["category"], leg["player"], leg["line"], leg.get("direction", "Over")
            )
            if selected:
                legs_selected += 1
                await human_delay(500, 1000)
            else:
                log.warning(f"[{self.profile_name}] Leg {i+1} not found: {leg['player']}")

        log.info(f"[{self.profile_name}] {legs_selected}/{len(legs)} legs selected")

        if legs_selected == 0:
            await self.clear_bet_slip()
            return {"status": "no_legs_found"}

        # Place the combined bet
        result = await self.place_bet(bet_amount, min_odd)

        # Record
        tip_str = " + ".join(f"{l['player']} {l.get('direction', 'Over')} {l['line']}" for l in legs)
        await db.record_bet(
            self.profile_name, tipster, match, team1, team2, tip_str,
            "betBuilder", f"{legs_selected}/{len(legs)} legs", min_odd,
            result.get("final_odd", 0.0), bet_amount, result["status"],
            result.get("seconds", 0.0), result.get("message", "")
        )

        return result

    async def _navigate_to_event(self, search_text: str) -> bool:
        """Search for a match and navigate to its event page."""
        try:
            await self.dismiss_popups()

            # Click search bar
            search_bar = self.page.locator(S.SEARCH_BAR)
            await search_bar.wait_for(state="visible", timeout=10000)
            await random_point(self.page, search_bar.first)
            await human_delay(500, 800)

            # Type match name
            search_input = self.page.locator(S.SEARCH_INPUT)
            await search_input.wait_for(state="visible", timeout=5000)
            await search_input.click()
            await human_delay(200, 400)

            for char in search_text:
                await self.page.keyboard.type(char, delay=random.uniform(30, 80))
            log.info(f"[{self.profile_name}] Match typed: {search_text}")
            await human_delay(1500, 2500)

            # Check for no results
            no_results = self.page.locator(S.NO_SEARCH_RESULTS)
            if await no_results.count() > 0:
                log.warning(f"[{self.profile_name}] No search results for {search_text}!")
                return False

            # Find View Event button
            view_event = self.page.locator(S.VIEW_EVENT_TEXT)
            if await view_event.count() == 0:
                view_event = self.page.locator(S.VIEW_EVENT_BETS)

            if await view_event.count() > 0:
                await random_point(self.page, view_event.first)
                log.info(f"[{self.profile_name}] View Event clicked!")
                await human_delay(2000, 3000)

                # Check if match is live
                nav_buttons = self.page.locator(S.MARKET_NAV_BUTTONS)
                if await nav_buttons.count() > 0:
                    log.info(f"[{self.profile_name}] Event page loaded, match is live!")
                    return True

                # Wait a bit more for page to load
                await human_delay(1000, 2000)
                if await nav_buttons.count() > 0:
                    return True

                log.info(f"[{self.profile_name}] Event page loaded (pre-match)")
                return True

            log.warning(f"[{self.profile_name}] View Event not found!")
            return False

        except Exception as e:
            log.error(f"[{self.profile_name}] Navigate to event error: {e}")
            return False

    # ----------------------------------------------------------------
    # FULL BET FLOW
    # ----------------------------------------------------------------
    async def execute_bet(self, match: str, team1: str, team2: str, tip: str,
                          category: str, bet_amount: float, min_odd: float,
                          tipster: str, bet_type: str = "single") -> dict:
        """
        Full bet placement flow:
        1. Ensure logged in
        2. Search for match/bet
        3. Enter stake
        4. Place bet
        5. Record result
        """
        log.info(f"[{self.profile_name}] === Executing bet: {match} | {tip} | {bet_amount} ===")

        # Route bet builders to dedicated flow
        if bet_type == "betBuilder" and isinstance(tip, list):
            return await self.execute_bet_builder(
                match, team1, team2, tip, bet_amount, min_odd, tipster
            )

        # Ensure logged in
        if not await self.is_logged_in():
            success = await self.login()
            if not success:
                return {"status": "login_failed"}

        await self.dismiss_popups()
        await self.clear_bet_slip()

        # Search for the bet
        search_text = match if match else f"{team1} {team2}".strip()
        found = await self.search_and_select_bet(search_text, category, tip)

        if not found:
            # Retry once
            log.info(f"[{self.profile_name}] Retrying search...")
            await human_delay(2000, 4000)
            await self.clear_bet_slip()
            found = await self.search_and_select_bet(search_text, category, tip)

        if not found:
            log.error(f"[{self.profile_name}] Bet not found after retry!")
            await db.record_bet(
                self.profile_name, tipster, match, team1, team2, tip,
                bet_type, category, min_odd, 0.0, bet_amount, "not_found", 0.0
            )
            return {"status": "not_found"}

        # Place the bet
        result = await self.place_bet(bet_amount, min_odd)

        # Record to database
        await db.record_bet(
            self.profile_name, tipster, match, team1, team2, tip,
            bet_type, category, min_odd, result.get("final_odd", 0.0),
            bet_amount, result["status"], result.get("seconds", 0.0),
            result.get("message", "")
        )

        return result
