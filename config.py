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

WHISPER_MODEL = "large-v3"
