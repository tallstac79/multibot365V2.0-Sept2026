import aiosqlite
import os
from datetime import datetime

DB_PATH = None

async def init_db(db_file: str):
    global DB_PATH
    DB_PATH = db_file
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    async with aiosqlite.connect(db_file) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                tipster TEXT NOT NULL,
                match_name TEXT,
                team1 TEXT,
                team2 TEXT,
                tip TEXT,
                bet_type TEXT,
                category TEXT,
                given_odd REAL,
                final_odd REAL,
                bet_amount REAL,
                status TEXT DEFAULT 'placed',
                result TEXT,
                returned REAL,
                placement_seconds REAL,
                notes TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS balance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                balance REAL,
                unsettled_bets INTEGER
            )
        """)
        await db.commit()


async def record_bet(profile_name: str, tipster: str, match_name: str, team1: str,
                     team2: str, tip: str, bet_type: str, category: str,
                     given_odd: float, final_odd: float, bet_amount: float,
                     status: str, placement_seconds: float, notes: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO bets (timestamp, profile_name, tipster, match_name, team1, team2,
                              tip, bet_type, category, given_odd, final_odd, bet_amount,
                              status, placement_seconds, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            profile_name, tipster, match_name, team1, team2,
            tip, bet_type, category, given_odd, final_odd, bet_amount,
            status, placement_seconds, notes
        ))
        await db.commit()


async def record_balance(profile_name: str, balance: float, unsettled_bets: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO balance_log (timestamp, profile_name, balance, unsettled_bets)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), profile_name, balance, unsettled_bets))
        await db.commit()
