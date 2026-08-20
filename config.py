import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
USE_PROXY = os.getenv("USE_PROXY", "0")
PROXY_URL = os.getenv("PROXY_URL", "")
USE_SOCKS5 = os.getenv("USE_SOCKS5", "0")
SOCKS5_PROXY = os.getenv("SOCKS5_PROXY", "")
QWEN_PROXY = os.getenv("QWEN_PROXY", SOCKS5_PROXY if USE_SOCKS5 == "1" else "")
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "")
YOUTUBE_COOKIES_FROM_BROWSER = os.getenv("YOUTUBE_COOKIES_FROM_BROWSER", "")
YOUTUBE_EXTRACTOR_ARGS = os.getenv("YOUTUBE_EXTRACTOR_ARGS", "")
WHISPER_CACHE_DIR = os.getenv("WHISPER_CACHE_DIR", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(BASE_DIR, "bot_data.db")

QWEN_URL = "https://chat.qwen.ai"
QWEN_TIMEOUT = 420
QWEN_PROFILE_DIR = os.path.join(PROFILES_DIR, "qwen")
QWEN_MAX_PROMPT_CHARS = 131072
QWEN_PROMPT_OVERHEAD = 2000
QWEN_USER_AGENT = os.getenv(
    "QWEN_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
)
QWEN_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--lang=ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
]

WHISPER_MODEL = "large-v3"
