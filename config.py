# ============================================================
# MultiBot365 Configuration
# ============================================================

# --- Telegram ---
TELEGRAM_API_ID = 0           # Get from https://my.telegram.org
TELEGRAM_API_HASH = ""
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = 0          # Your chat ID for notifications/commands
TELEGRAM_SESSION = "sessions/multibot"

# --- Tipster Channels ---
# Map Telegram channel/group IDs to tipster names.
# The bot will listen to ALL of these channels for tips.
# chat_id -> tipster name (must match a key in TIPSTERS dict)
TIPSTER_CHANNELS = {
    # -1001234567890: "TomsNBA",
    # -1009876543210: "Harley",
    # -1001111111111: "Xambroker",
    # Add more channel_id: "TipsterName" pairs as needed
}

# --- Multilogin X ---
MULTILOGIN_HOST = "http://localhost:45001"
MULTILOGIN_TOKEN = ""         # Bearer token from Multilogin X

# --- Profiles ---
# Each profile maps to one Bet365 account + one Multilogin browser profile
PROFILES = [
    {
        "name": "Profile1",
        "multilogin_profile_id": "",   # UUID from Multilogin
        "bet365_username": "",
        "bet365_password": "",
        "bet365_region": "com",        # com, gr, etc.
        "max_bet_amount": 300,
        "enabled": True,
    },
    # Add more profiles as needed:
    # {
    #     "name": "Profile2",
    #     "multilogin_profile_id": "",
    #     "bet365_username": "",
    #     "bet365_password": "",
    #     "bet365_region": "com",
    #     "max_bet_amount": 300,
    #     "enabled": True,
    # },
]

# --- Tipsters ---
# Each tipster has a multiplier (or fixed bet amount), odd limit, and max bet
TIPSTERS = {
    "Harley":       {"switch": "on", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300, "cards": True},
    "Xambroker":    {"switch": "on", "men_bet": 25, "women_bet": 25, "odd_limit": 1.0, "max_bet": 300, "min_units": 1.5},
    "TomsNBA":      {"switch": "on", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300, "split_stake": True},
    "Andreas":      {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "Betol":        {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "Custom":       {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "DTP":          {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "Favori":       {"switch": "off", "bet_amount": 25, "odd_limit": 1.6, "max_bet": 300},
    "Fraetos":      {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "Genius":       {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "Goat":         {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "Kasper":       {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "Nakata":       {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "Outsider":     {"switch": "off", "bet_amount": 25, "odd_limit": 1.6, "max_bet": 300},
    "PIPS":         {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "TomsFootball": {"switch": "off", "multiplier": 50, "odd_limit": 1.6, "max_bet": 300},
    "VUA80":        {"switch": "off", "bet_amount": 25, "odd_limit": 1.6, "max_bet": 300},
}

# --- Timing ---
STAGGER_MIN_SECONDS = 10      # Min delay between profiles placing same bet
STAGGER_MAX_SECONDS = 60      # Max delay between profiles placing same bet
BET_PLACEMENT_TIMEOUT = 90    # Max seconds to wait for bet placement

# --- Anti-Detection ---
TIME_OFF_HOURS = [0, 1, 2, 3, 4, 5, 6, 7, 23]  # Don't bet during these hours

# --- General ---
BOT_ENABLED = True
REDUCED_ALERTS = False
BALANCE_ALERT_AMOUNT = 50
LOG_FILE = "logs/multibot.log"
DB_FILE = "core/bets.db"
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
