"""
Orchestrator — manages multiple Bet365 profiles and distributes tips across them.
"""
import asyncio
import random
from datetime import datetime

from core.multilogin import MultiloginManager
from core.antidetect import stagger_delay
from core.logger import setup_logger
from plugins.bet365 import Bet365

log = setup_logger("orchestrator", "logs/multibot.log")


class Orchestrator:
    def __init__(self, multilogin: MultiloginManager, profiles_config: list,
                 tipsters_config: dict, stagger_min: int = 10, stagger_max: int = 60,
                 time_off_hours: list = None):
        self.ml = multilogin
        self.profiles_config = profiles_config
        self.tipsters_config = tipsters_config
        self.stagger_min = stagger_min
        self.stagger_max = stagger_max
        self.time_off_hours = time_off_hours or []
        self.bots = {}  # profile_name -> Bet365 instance
        self.running = False

    async def launch_all_profiles(self) -> int:
        """Launch all enabled profiles and connect Playwright. Returns count of connected profiles."""
        connected = 0
        for profile in self.profiles_config:
            if not profile.get("enabled", True):
                log.info(f"Profile {profile['name']} is disabled, skipping")
                continue

            profile_id = profile["multilogin_profile_id"]
            if not profile_id:
                log.warning(f"Profile {profile['name']} has no Multilogin profile ID, skipping")
                continue

            log.info(f"Launching profile {profile['name']}...")
            page = await self.ml.launch_and_connect(profile_id)

            if page:
                bot = Bet365(
                    page=page,
                    profile_name=profile["name"],
                    username=profile["bet365_username"],
                    password=profile["bet365_password"],
                    region=profile.get("bet365_region", "com"),
                )
                self.bots[profile["name"]] = bot
                connected += 1
                log.info(f"Profile {profile['name']} connected!")
            else:
                log.error(f"Failed to connect profile {profile['name']}")

            # Small delay between profile launches
            await asyncio.sleep(2)

        log.info(f"{connected}/{len(self.profiles_config)} profiles connected")
        return connected

    async def login_all(self) -> int:
        """Log into Bet365 on all connected profiles. Returns count of successful logins."""
        logged_in = 0
        for name, bot in self.bots.items():
            success = await bot.login()
            if success:
                logged_in += 1
                log.info(f"[{name}] Login successful! Balance: {bot.balance}")
            else:
                log.error(f"[{name}] Login failed!")
            await asyncio.sleep(random.uniform(3, 8))  # Stagger logins
        log.info(f"{logged_in}/{len(self.bots)} profiles logged in")
        return logged_in

    def _is_time_off(self) -> bool:
        """Check if current hour is in the time-off window."""
        current_hour = datetime.now().hour
        return current_hour in self.time_off_hours

    def _calculate_bet_amount(self, tipster: str, tip_data: dict) -> float:
        """Calculate bet amount based on tipster config and tip data."""
        config = self.tipsters_config.get(tipster, {})
        if config.get("switch", "off") == "off":
            return 0.0

        # Fixed bet amount
        if "bet_amount" in config:
            amount = config["bet_amount"]
        # Multiplier-based
        elif "multiplier" in config and tip_data.get("stakes"):
            units = tip_data["stakes"][0]
            amount = units * config["multiplier"]
        elif "multiplier" in config:
            amount = config["multiplier"]  # Default 1 unit
        else:
            amount = 25  # Fallback

        # Cap at max
        max_bet = config.get("max_bet", 300)
        if max_bet > 0 and amount > max_bet:
            amount = max_bet

        return round(amount, 2)

    async def distribute_tip(self, tip_data: dict):
        """
        Distribute a tip to all active profiles with staggered timing.
        """
        if self._is_time_off():
            log.info("Currently in time-off hours, skipping tip")
            return

        if "command" in tip_data:
            await self._handle_command(tip_data["command"])
            return

        tipster = tip_data.get("tipster", "Custom")
        tipster_config = self.tipsters_config.get(tipster, {})
        if tipster_config.get("switch", "off") == "off":
            log.info(f"Tipster {tipster} is disabled, skipping")
            return

        bet_amount = self._calculate_bet_amount(tipster, tip_data)
        if bet_amount <= 0:
            log.info("Bet amount is 0, skipping")
            return

        min_odd = tip_data.get("min_odd", tipster_config.get("odd_limit", 0.0))

        # Build bet parameters
        match_name = tip_data.get("match", "")
        team1 = tip_data.get("team1", "")
        team2 = tip_data.get("team2", "")
        tip = tip_data.get("tip", "")
        category = tip_data.get("category", "")
        bet_type = tip_data.get("bet_type", "single")
        legs = tip_data.get("legs", [])  # For bet builders

        log.info(f"Distributing tip to {len(self.bots)} profile(s): {match_name} | {tip} | {bet_amount}")

        # Handle split stakes (e.g., TomsNBA sends ['1.25', '0.5'])
        stakes = tip_data.get("stakes", [])
        if tipster_config.get("split_stake") and len(stakes) > 1:
            log.info(f"Split stake enabled: placing {len(stakes)} separate bets")
            for stake_idx, stake_units in enumerate(stakes):
                split_amount = stake_units * tipster_config.get("multiplier", 1)
                split_amount = min(split_amount, tipster_config.get("max_bet", 300))
                split_amount = round(split_amount, 2)
                for i, (name, bot) in enumerate(self.bots.items()):
                    delay = stagger_delay(self.stagger_min, self.stagger_max) if (i > 0 or stake_idx > 0) else 0
                    profile_amount = split_amount * random.uniform(0.9, 1.1)
                    profile_amount = round(profile_amount, 2)
                    if bet_type == "betBuilder" and legs:
                        await self._place_betbuilder_with_delay(
                            bot, delay, match_name, team1, team2, legs,
                            profile_amount, min_odd, tipster
                        )
                    else:
                        await self._place_bet_with_delay(
                            bot, delay, match_name, team1, team2, tip,
                            category, profile_amount, min_odd, tipster, bet_type
                        )
            return

        # Standard single-amount distribution
        tasks = []
        for i, (name, bot) in enumerate(self.bots.items()):
            delay = 0 if i == 0 else stagger_delay(self.stagger_min, self.stagger_max)

            # Vary bet amount slightly per profile (+/- 10%) to avoid identical bets
            profile_amount = bet_amount * random.uniform(0.9, 1.1)
            profile_amount = round(profile_amount, 2)

            if bet_type == "betBuilder" and legs:
                tasks.append(self._place_betbuilder_with_delay(
                    bot, delay, match_name, team1, team2, legs,
                    profile_amount, min_odd, tipster
                ))
            else:
                tasks.append(self._place_bet_with_delay(
                    bot, delay, match_name, team1, team2, tip,
                    category, profile_amount, min_odd, tipster, bet_type
                ))

        # Run all profile bets concurrently (they have built-in stagger delays)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log results
        for (name, _), result in zip(self.bots.items(), results):
            if isinstance(result, Exception):
                log.error(f"[{name}] Bet placement error: {result}")
            else:
                log.info(f"[{name}] Bet result: {result.get('status', 'unknown')}")

    async def _place_bet_with_delay(self, bot: Bet365, delay: float,
                                     match: str, team1: str, team2: str,
                                     tip: str, category: str, bet_amount: float,
                                     min_odd: float, tipster: str, bet_type: str) -> dict:
        """Place a bet after a stagger delay."""
        if delay > 0:
            log.info(f"[{bot.profile_name}] Waiting {delay:.0f}s before placing bet...")
            await asyncio.sleep(delay)
        return await bot.execute_bet(match, team1, team2, tip, category,
                                      bet_amount, min_odd, tipster, bet_type)

    async def _place_betbuilder_with_delay(self, bot: Bet365, delay: float,
                                            match: str, team1: str, team2: str,
                                            legs: list, bet_amount: float,
                                            min_odd: float, tipster: str) -> dict:
        """Place a bet builder after a stagger delay."""
        if delay > 0:
            log.info(f"[{bot.profile_name}] Waiting {delay:.0f}s before placing bet builder...")
            await asyncio.sleep(delay)
        return await bot.execute_bet_builder(match, team1, team2, legs,
                                              bet_amount, min_odd, tipster)

    async def _handle_command(self, command: str):
        """Handle bot commands across all profiles."""
        if command == "balance":
            for name, bot in self.bots.items():
                balance = await bot.get_balance()
                log.info(f"[{name}] Balance: {balance}, Unsettled: {bot.unsettled_bets}")

        elif command == "reload":
            for name, bot in self.bots.items():
                try:
                    await bot.page.reload(wait_until="domcontentloaded")
                    log.info(f"[{name}] Page reloaded")
                except Exception as e:
                    log.error(f"[{name}] Reload error: {e}")

        elif command == "screenshot":
            import os
            os.makedirs("screenshots/bet365", exist_ok=True)
            for name, bot in self.bots.items():
                try:
                    path = f"screenshots/bet365/{name}_screenshot.png"
                    await bot.page.screenshot(path=path)
                    log.info(f"[{name}] Screenshot saved: {path}")
                except Exception as e:
                    log.error(f"[{name}] Screenshot error: {e}")

    async def get_all_balances(self) -> dict:
        """Get balances from all profiles."""
        balances = {}
        for name, bot in self.bots.items():
            balance = await bot.get_balance()
            balances[name] = {"balance": balance, "unsettled": bot.unsettled_bets}
        return balances

    async def shutdown(self):
        """Clean shutdown of all profiles."""
        log.info("Shutting down all profiles...")
        for name, bot in self.bots.items():
            try:
                await bot.logout()
            except Exception:
                pass
        await self.ml.stop_playwright()
        log.info("All profiles shut down")
