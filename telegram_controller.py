import requests
import time
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_POLL_INTERVAL, TELEGRAM_CHAT_ID
from runtime_state import PAUSE_STATE
from telegram_notifier import TelegramNotifier

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
logger = logging.getLogger(__name__)

def get_updates(offset=None, timeout=25):
    params = {"timeout": timeout}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=timeout+5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error getting Telegram updates: {e}")
        return {"result": []}

def handle_callback(callback_query):
    data = callback_query.get("data") or ""
    user = callback_query.get("from", {}).get("username", "unknown")
    chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
    
    notifier = TelegramNotifier()
    
    if data == "PAUSE_NOW":
        PAUSE_STATE.pause()
        notifier.send_message(f"⏸️ Sistem duraklatıldı. (İstek: @{user})", chat_id=chat_id or TELEGRAM_CHAT_ID)
        logger.info(f"Sistem duraklatıldı. (İstek: @{user})")
    elif data == "RESUME":
        PAUSE_STATE.resume()
        notifier.send_message(f"▶️ Sistem devam ediyor. (İstek: @{user})", chat_id=chat_id or TELEGRAM_CHAT_ID)
        logger.info(f"Sistem devam ediyor. (İstek: @{user})")

def polling_loop():
    offset = None
    while True:
        try:
            res = get_updates(offset=offset, timeout=20)
            for update in res.get("result", []):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
        except Exception as e:
            logger.error(f"Error in Telegram polling loop: {e}")
            time.sleep(TELEGRAM_POLL_INTERVAL)