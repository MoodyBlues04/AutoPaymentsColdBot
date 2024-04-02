import os

from dotenv import find_dotenv, load_dotenv

if not find_dotenv():
    exit("Переменные окружения не загружены, так как отсутствует файл .env")
else:
    load_dotenv()

USER_ID = os.getenv("user_id")
TELEGRAM_BOT = os.getenv("telegram_bot")
WALLETS = os.getenv("wallets")
API_KEY = os.getenv("api_key")
OWNER_WALLET_ID = os.getenv("owner_wallet_id")