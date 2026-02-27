import os
import logging
import asyncio
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, InputMediaPhoto, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TimedOut, Forbidden

# Загружаем переменные окружения
load_dotenv()

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_CHANNEL_ID = os.getenv("CHANNEL_ID", "-1002808898833")
DEFAULT_REQUIRED_CHANNEL_LINK = "https://t.me/GardenHorizonsStocks"

API_URL = os.getenv("API_URL", "https://garden-horizons-stock.dawidfc.workers.dev/api/stock")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "10"))
ADMIN_ID = 8025951500

# Часовой пояс Москвы (UTC+3)
MSK_TIMEZONE = timezone(timedelta(hours=3))

# База данных
if os.environ.get('RAILWAY_ENVIRONMENT'):
    DB_PATH = "/data/bot.db"
    logger.info(f"✅ Работаем на Railway, БД в /data/bot.db")
    try:
        os.makedirs('/data', exist_ok=True)
        logger.info(f"📁 Папка /data создана/существует")
    except Exception as e:
        logger.error(f"❌ Ошибка создания папки /data: {e}")
        DB_PATH = "/tmp/bot.db"
        logger.info(f"✅ Использую временную БД: {DB_PATH}")
else:
    DB_PATH = "bot.db"
    logger.info("✅ Локальная разработка, БД в bot.db")

# URL изображений
IMAGE_MAIN = "https://i.postimg.cc/J4JdrN5z/image.png"
IMAGE_SEEDS = "https://i.postimg.cc/pTf40Kcx/image.png"
IMAGE_GEAR = "https://i.postimg.cc/GmMcKnTc/image.png"
IMAGE_WEATHER = "https://i.postimg.cc/J4JdrN5z/image.png"

# Ссылки
BOT_LINK = "https://t.me/GardenHorizons_StocksBot"
CHAT_LINK = "https://t.me/GardenHorizons_Trade"

# Состояния для ConversationHandler
ADD_OP_CHANNEL_ID, ADD_OP_CHANNEL_NAME = range(2)
ADD_POST_CHANNEL_ID, ADD_POST_CHANNEL_NAME = range(2, 4)
MAILING_TEXT = 4

# Текст главного меню
MAIN_MENU_TEXT = (
    "🌱 <b>Привет! Я могу отслеживать стоки в игре Garden Horizons, "
    "и отправлять их тебе, круто да? 🔥</b>\n\n"
    "<b>Наш канал - @GardenHorizonsStocks</b>\n"
    "<b>Наш чат - @GardenHorizons_Trade</b>\n\n"
    "<b>👇 Выберите действие ниже 👇</b>"
)

# ========== СЛОВАРЬ ПЕРЕВОДОВ ==========
TRANSLATIONS = {
    "Carrot": "🥕 Морковь", "Corn": "🌽 Кукуруза", "Onion": "🧅 Лук",
    "Strawberry": "🍓 Клубника", "Mushroom": "🍄 Гриб", "Beetroot": "🍠 Свекла",
    "Tomato": "🍅 Помидор", "Apple": "🍎 Яблоко", "Rose": "🌹 Роза",
    "Wheat": "🌾 Пшеница", "Banana": "🍌 Банан", "Plum": "🍐 Слива",
    "Potato": "🥔 Картофель", "Cabbage": "🥬 Капуста", "Cherry": "🍒 Вишня",
    "Watering Can": "💧 Лейка", "Basic Sprinkler": "💦 Простой разбрызгиватель",
    "Harvest Bell": "🔔 Колокол сбора", "Turbo Sprinkler": "⚡ Турбо-разбрызгиватель",
    "Favorite Tool": "⭐ Любимый инструмент", "Super Sprinkler": "💎 Супер-разбрызгиватель",
    "fog": "🌫️ Туман", "rain": "🌧️ Дождь", "snow": "❄️ Снег",
    "storm": "⛈️ Шторм", "sandstorm": "🏜️ Песчаная буря", "starfall": "⭐ Звездопад"
}

ALLOWED_CHANNEL_ITEMS = ["Potato", "Cabbage", "Cherry"]
SEEDS_LIST = ["Carrot", "Corn", "Onion", "Strawberry", "Mushroom", "Beetroot", "Tomato", "Apple", "Rose", "Wheat", "Banana", "Plum", "Potato", "Cabbage", "Cherry"]
GEAR_LIST = ["Watering Can", "Basic Sprinkler", "Harvest Bell", "Turbo Sprinkler", "Favorite Tool", "Super Sprinkler"]
WEATHER_LIST = ["fog", "rain", "snow", "storm", "sandstorm", "starfall"]
RARE_ITEMS = ["Super Sprinkler", "Favorite Tool", "starfall"]

def translate(text: str) -> str:
    return TRANSLATIONS.get(text, text)

def is_rare(item_name: str) -> bool:
    return item_name in RARE_ITEMS

def is_allowed_for_main_channel(item_name: str) -> bool:
    return item_name in ALLOWED_CHANNEL_ITEMS

def is_weather_active(weather_data: Dict) -> bool:
    """Проверяет, активна ли погода с учетом времени окончания"""
    if not weather_data:
        return False
    
    if not weather_data.get("active"):
        return False
    
    end_timestamp = weather_data.get("endTimestamp")
    if end_timestamp:
        current_time = int(time.time())
        if current_time >= end_timestamp:
            return False
        else:
            return True
    
    return True

def get_msk_time_from_timestamp(timestamp: int) -> str:
    """Конвертирует timestamp в московское время"""
    try:
        dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        dt_msk = dt_utc.astimezone(MSK_TIMEZONE)
        return dt_msk.strftime("%H:%M:%S")
    except Exception as e:
        logger.error(f"❌ Ошибка конвертации времени: {e}")
        return "??:??:??"

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ==========

def init_database():
    """Создает все необходимые таблицы в базе данных"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        logger.info(f"✅ Подключение к БД успешно: {DB_PATH}")
        
        # Таблица пользователей
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen TEXT,
                notifications_enabled INTEGER DEFAULT 1
            )
        """)
        
        # Таблица обязательных каналов (ОП)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mandatory_channels (
                channel_id TEXT PRIMARY KEY,
                channel_name TEXT
            )
        """)
        
        # Таблица каналов для автопостинга
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posting_channels (
                channel_id TEXT PRIMARY KEY,
                name TEXT,
                username TEXT,
                added_at TEXT
            )
        """)
        
        # Таблица для истории отправленных уведомлений с update_id
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                item_name TEXT,
                quantity INTEGER,
                update_id TEXT,
                sent_at TEXT,
                UNIQUE(chat_id, item_name, quantity, update_id)
            )
        """)
        
        # Таблица для настроек пользователей по предметам
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_items (
                user_id INTEGER,
                item_name TEXT,
                enabled INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, item_name)
            )
        """)
        
        # Таблица для отслеживания отправленных предметов пользователям
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_sent_items (
                user_id INTEGER,
                item_name TEXT,
                quantity INTEGER,
                sent_at TEXT,
                update_id TEXT,
                PRIMARY KEY (user_id, item_name, update_id)
            )
        """)
        
        # Таблица для отслеживания уведомлений о погоде
        cur.execute("""
            CREATE TABLE IF NOT EXISTS weather_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                weather_type TEXT,
                status TEXT,
                update_id TEXT,
                sent_at TEXT,
                UNIQUE(weather_type, status, update_id)
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована успешно")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

db_initialized = init_database()

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ ==========

def get_db():
    return sqlite3.connect(DB_PATH)

# ----- ПОЛЬЗОВАТЕЛИ -----

def add_user_to_db(user_id: int, username: str = ""):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            cur.execute(
                "UPDATE users SET username = ? WHERE user_id = ?",
                (username, user_id)
            )
        else:
            cur.execute(
                "INSERT INTO users (user_id, username, first_seen) VALUES (?, ?, ?)",
                (user_id, username, datetime.now().isoformat())
            )
            for item in SEEDS_LIST + GEAR_LIST + WEATHER_LIST:
                cur.execute(
                    "INSERT INTO user_items (user_id, item_name, enabled) VALUES (?, ?, 1)",
                    (user_id, item)
                )
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка добавления пользователя {user_id}: {e}")

def get_user_settings(user_id: int) -> Dict:
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute(
            "SELECT notifications_enabled FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = cur.fetchone()
        notifications_enabled = bool(result[0]) if result else True
        
        cur.execute(
            "SELECT item_name, enabled FROM user_items WHERE user_id = ?",
            (user_id,)
        )
        items = {row[0]: bool(row[1]) for row in cur.fetchall()}
        
        conn.close()
        
        return {
            'notifications_enabled': notifications_enabled,
            'seeds': {item: items.get(item, True) for item in SEEDS_LIST},
            'gear': {item: items.get(item, True) for item in GEAR_LIST},
            'weather': {item: items.get(item, True) for item in WEATHER_LIST}
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения настроек пользователя {user_id}: {e}")
        return {
            'notifications_enabled': True,
            'seeds': {item: True for item in SEEDS_LIST},
            'gear': {item: True for item in GEAR_LIST},
            'weather': {item: True for item in WEATHER_LIST}
        }

def update_user_setting(user_id: int, setting: str, value: Any):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        if setting == 'notifications_enabled':
            cur.execute(
                "UPDATE users SET notifications_enabled = ? WHERE user_id = ?",
                (1 if value else 0, user_id)
            )
        elif setting.startswith('seed_') or setting.startswith('gear_') or setting.startswith('weather_'):
            item_name = setting.replace('seed_', '').replace('gear_', '').replace('weather_', '')
            cur.execute(
                "UPDATE user_items SET enabled = ? WHERE user_id = ? AND item_name = ?",
                (1 if value else 0, user_id, item_name)
            )
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка обновления настройки {setting} для {user_id}: {e}")

def get_all_users() -> List[int]:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        users = [row[0] for row in cur.fetchall()]
        conn.close()
        return users
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка пользователей: {e}")
        return []

def get_users_count() -> int:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"❌ Ошибка получения количества пользователей: {e}")
        return 0

# ----- ОБЯЗАТЕЛЬНЫЕ КАНАЛЫ (ОП) -----

def get_mandatory_channels() -> List[Dict]:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_name FROM mandatory_channels ORDER BY channel_id")
        channels = [{'id': row[0], 'name': row[1]} for row in cur.fetchall()]
        conn.close()
        return channels
    except Exception as e:
        logger.error(f"❌ Ошибка получения каналов ОП: {e}")
        return []

def add_mandatory_channel(channel_id: str, channel_name: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO mandatory_channels (channel_id, channel_name) VALUES (?, ?)",
            (str(channel_id), channel_name)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка добавления канала ОП в БД: {e}")

def remove_mandatory_channel(channel_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM mandatory_channels WHERE channel_id = ?", (str(channel_id),))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка удаления канала ОП из БД: {e}")

# ----- КАНАЛЫ ДЛЯ АВТОПОСТИНГА -----

def get_posting_channels() -> List[Dict]:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, name, username FROM posting_channels ORDER BY added_at")
        channels = [
            {'id': row[0], 'name': row[1], 'username': row[2]}
            for row in cur.fetchall()
        ]
        conn.close()
        return channels
    except Exception as e:
        logger.error(f"❌ Ошибка получения каналов автопостинга: {e}")
        return []

def add_posting_channel(channel_id: str, name: str, username: str = None):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO posting_channels (channel_id, name, username, added_at) VALUES (?, ?, ?, ?)",
            (str(channel_id), name, username, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка добавления канала автопостинга в БД: {e}")

def remove_posting_channel(channel_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM posting_channels WHERE channel_id = ?", (str(channel_id),))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка удаления канала автопостинга из БД: {e}")

# ----- ОТПРАВЛЕННЫЕ УВЕДОМЛЕНИЯ -----

def was_item_sent_to_user(user_id: int, item_name: str, quantity: int, update_id: str) -> bool:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM user_sent_items WHERE user_id = ? AND item_name = ? AND quantity = ? AND update_id = ?",
            (user_id, item_name, quantity, update_id)
        )
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"❌ Ошибка проверки отправленного предмета: {e}")
        return False

def mark_item_sent_to_user(user_id: int, item_name: str, quantity: int, update_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO user_sent_items (user_id, item_name, quantity, sent_at, update_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, item_name, quantity, datetime.now().isoformat(), update_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка отметки отправленного предмета: {e}")

def was_item_sent(chat_id: int, item_name: str, quantity: int, update_id: str) -> bool:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM sent_items WHERE chat_id = ? AND item_name = ? AND quantity = ? AND update_id = ?",
            (chat_id, item_name, quantity, update_id)
        )
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"❌ Ошибка проверки отправленного: {e}")
        return False

def mark_item_sent(chat_id: int, item_name: str, quantity: int, update_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO sent_items (chat_id, item_name, quantity, update_id, sent_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, item_name, quantity, update_id, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        logger.info(f"📝 Отмечено в БД: канал {chat_id}, {item_name}={quantity}, update_id={update_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отметки отправленного: {e}")

def was_weather_notification_sent(weather_type: str, status: str, update_id: str) -> bool:
    """Проверяет, было ли уже отправлено уведомление о погоде"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM weather_notifications WHERE weather_type = ? AND status = ? AND update_id = ?",
            (weather_type, status, update_id)
        )
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"❌ Ошибка проверки уведомления о погоде: {e}")
        return False

def mark_weather_notification_sent(weather_type: str, status: str, update_id: str):
    """Отмечает, что уведомление о погоде отправлено"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO weather_notifications (weather_type, status, update_id, sent_at) VALUES (?, ?, ?, ?)",
            (weather_type, status, update_id, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
        logger.info(f"📝 Отмечено уведомление о погоде: {weather_type} - {status}")
    except Exception as e:
        logger.error(f"❌ Ошибка отметки уведомления о погоде: {e}")

# ----- СТАТИСТИКА -----

def get_stats() -> Dict:
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM users")
        users_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM mandatory_channels")
        op_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM posting_channels")
        post_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM sent_items")
        sent_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM user_sent_items")
        user_sent_count = cur.fetchone()[0]
        
        conn.close()
        
        return {
            'users': users_count,
            'op_channels': op_count,
            'posting_channels': post_count,
            'sent_notifications': sent_count,
            'user_sent_items': user_sent_count
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        return {
            'users': 0,
            'op_channels': 0,
            'posting_channels': 0,
            'sent_notifications': 0,
            'user_sent_items': 0
        }

# ========== КЛАССЫ ==========

@dataclass
class ItemSettings:
    enabled: bool = True
    
    def to_dict(self):
        return {'enabled': self.enabled}
    
    @classmethod
    def from_dict(cls, data):
        return cls(data.get('enabled', True))

@dataclass
class UserSettings:
    user_id: int
    username: str = ""
    notifications_enabled: bool = False
    seeds: Dict[str, ItemSettings] = field(default_factory=dict)
    gear: Dict[str, ItemSettings] = field(default_factory=dict)
    weather: Dict[str, ItemSettings] = field(default_factory=dict)
    is_admin: bool = False
    
    def __post_init__(self):
        db_settings = get_user_settings(self.user_id)
        self.notifications_enabled = db_settings['notifications_enabled']
        
        for seed in SEEDS_LIST:
            self.seeds[seed] = ItemSettings(enabled=db_settings['seeds'].get(seed, True))
        for gear in GEAR_LIST:
            self.gear[gear] = ItemSettings(enabled=db_settings['gear'].get(gear, True))
        for weather in WEATHER_LIST:
            self.weather[weather] = ItemSettings(enabled=db_settings['weather'].get(weather, True))
        
        self.is_admin = (self.user_id == ADMIN_ID)
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'username': self.username,
            'notifications_enabled': self.notifications_enabled,
            'seeds': {k: v.to_dict() for k, v in self.seeds.items()},
            'gear': {k: v.to_dict() for k, v in self.gear.items()},
            'weather': {k: v.to_dict() for k, v in self.weather.items()}
        }
    
    @classmethod
    def from_dict(cls, data):
        settings = cls(data['user_id'], data.get('username', ''))
        settings.notifications_enabled = data.get('notifications_enabled', False)
        
        for k, v in data.get('seeds', {}).items():
            if k in SEEDS_LIST:
                settings.seeds[k] = ItemSettings.from_dict(v)
        for k, v in data.get('gear', {}).items():
            if k in GEAR_LIST:
                settings.gear[k] = ItemSettings.from_dict(v)
        for k, v in data.get('weather', {}).items():
            if k in WEATHER_LIST:
                settings.weather[k] = ItemSettings.from_dict(v)
        
        settings.__post_init__()
        return settings

class UserManager:
    def __init__(self):
        self.users: Dict[int, UserSettings] = {}
        self.load_users()
    
    def load_users(self):
        user_ids = get_all_users()
        for user_id in user_ids:
            self.users[user_id] = UserSettings(user_id)
        logger.info(f"📥 Загружено {len(self.users)} пользователей из БД")
    
    def get_user(self, user_id: int, username: str = "") -> UserSettings:
        if user_id not in self.users:
            add_user_to_db(user_id, username)
            self.users[user_id] = UserSettings(user_id, username)
        elif username and self.users[user_id].username != username:
            self.users[user_id].username = username
            add_user_to_db(user_id, username)
        return self.users[user_id]
    
    def get_all_users(self) -> List[int]:
        return list(self.users.keys())
    
    def save_users(self):
        pass

class MessageQueue:
    def __init__(self, delay: float = 0.1):
        self.queue = asyncio.Queue()
        self.delay = delay
        self._task = None
        self.application = None
    
    async def start(self):
        self._task = asyncio.create_task(self._worker())
    
    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    async def _worker(self):
        while True:
            try:
                chat_id, text, parse_mode, photo = await self.queue.get()
                try:
                    if photo:
                        await self._send_photo_with_retry(chat_id, photo, text, parse_mode)
                    else:
                        await self._send_with_retry(chat_id, text, parse_mode)
                except Exception as e:
                    logger.error(f"Ошибка отправки в {chat_id}: {e}")
                finally:
                    self.queue.task_done()
                    await asyncio.sleep(self.delay)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в очереди: {e}")
                await asyncio.sleep(1)
    
    async def _send_with_retry(self, chat_id: int, text: str, parse_mode: str, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True
                )
                return
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TimedOut:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except Forbidden as e:
                logger.warning(f"⚠️ Не могу отправить сообщение в {chat_id}: {e}")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
    
    async def _send_photo_with_retry(self, chat_id: int, photo: str, caption: str, parse_mode: str, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                await self.application.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode=parse_mode
                )
                return
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TimedOut:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except Forbidden as e:
                logger.warning(f"⚠️ Не могу отправить фото в {chat_id}: {e}")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

# ========== MIDDLEWARE ==========
class SubscriptionMiddleware:
    """Middleware для проверки подписки на каналы"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
    
    async def __call__(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not user:
            return True
        
        # Логируем ВСЁ, что приходит
        if update.message:
            logger.info(f"📨 Middleware: ПОЛУЧЕНО СООБЩЕНИЕ от {user.id}: {update.message.text}")
        if update.callback_query:
            logger.info(f"📨 Middleware: ПОЛУЧЕН CALLBACK от {user.id}: {update.callback_query.data}")
        
        # Для команды /start - ВСЕГДА пропускаем
        if update.message and update.message.text and update.message.text.startswith('/start'):
            logger.info(f"🚀 Middleware: команда /start от {user.id} - ПРОПУСКАЮ БЕЗ ПРОВЕРКИ")
            return True
        
        # Пропускаем callback проверки подписки
        if update.callback_query and update.callback_query.data == "check_our_sub":
            logger.info(f"✅ Middleware: callback check_our_sub от {user.id} - ПРОПУСКАЮ БЕЗ ПРОВЕРКИ")
            return True
        
        # Пропускаем админа
        if user.id == ADMIN_ID:
            logger.info(f"👑 Middleware: админ {user.id} - ПРОПУСКАЮ БЕЗ ПРОВЕРКИ")
            return True
        
        # ДЛЯ ВСЕХ ОСТАЛЬНЫХ - ПРОВЕРЯЕМ ПОДПИСКУ
        logger.info(f"🔍 Middleware: проверяю подписку для {user.id}")
        
        # Получаем актуальные каналы
        channels = self.bot.reload_channels()
        
        # Если каналов нет - пропускаем
        if not channels:
            logger.info(f"📭 Middleware: нет каналов ОП, пропускаю {user.id}")
            return True
        
        # Проверяем подписку
        is_subscribed = await self.bot.check_our_subscriptions(user.id)
        
        if not is_subscribed:
            logger.info(f"❌ Middleware: пользователь {user.id} НЕ ПОДПИСАН, показываю сообщение")
            
            text = "📢 Для использования бота необходимо подписаться на каналы 👇\n\n"
            buttons = []
            
            for channel in channels:
                text += f"▪️ {channel['name']}\n"
                
                channel_id = channel['id']
                if channel_id.startswith('@'):
                    url = f"https://t.me/{channel_id.lstrip('@')}"
                else:
                    try:
                        chat = await self.bot.application.bot.get_chat(int(channel_id))
                        if chat.username:
                            url = f"https://t.me/{chat.username}"
                        else:
                            url = f"tg://resolve?domain={channel_id}"
                    except:
                        url = f"tg://resolve?domain={channel_id}"
                
                buttons.append([InlineKeyboardButton(text=f"📢 {channel['name']}", url=url)])
            
            buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_our_sub")])
            
            try:
                if update.message:
                    await update.message.reply_photo(
                        photo=IMAGE_MAIN,
                        caption=f"<b>{text}</b>",
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                    )
                elif update.callback_query:
                    try:
                        await update.callback_query.edit_message_media(
                            media=InputMediaPhoto(media=IMAGE_MAIN, caption=f"<b>{text}</b>", parse_mode='HTML'),
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                        )
                    except:
                        await update.callback_query.message.reply_photo(
                            photo=IMAGE_MAIN,
                            caption=f"<b>{text}</b>",
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                        )
            except Exception as e:
                logger.error(f"❌ Middleware: ошибка отправки сообщения: {e}")
            
            return False
        
        logger.info(f"✅ Middleware: пользователь {user.id} подписан, пропускаю")
        return True

class GardenHorizonsBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.user_manager = UserManager()
        self.last_data: Optional[Dict] = None
        self.mandatory_channels = get_mandatory_channels()
        self.posting_channels = get_posting_channels()
        self.mailing_text = None
        self.message_queue = MessageQueue(delay=0.1)
        self.message_queue.application = self.application
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        })
        
        self.setup_conversation_handlers()
        self.setup_handlers()
        
        # Создаем middleware
        self.subscription_middleware = SubscriptionMiddleware(self)
        
        # Сохраняем оригинальный метод process_update
        self.original_process_update = self.application.process_update
        # Переопределяем на наш
        self.application.process_update = self.process_update_with_middleware
        logger.info("✅ process_update переопределен на process_update_with_middleware, оригинал сохранён")
        
        logger.info(f"🤖 Бот инициализирован. Админ ID: {ADMIN_ID}")
        logger.info(f"📢 Каналов ОП: {len(self.mandatory_channels)}")
        logger.info(f"📢 Каналов автопостинга: {len(self.posting_channels)}")
    
    async def process_update_with_middleware(self, update: Update):
        """Обертка для process_update с middleware - ИСПРАВЛЕНО (без рекурсии)"""
        logger.info(f"⚡⚡⚡ process_update_with_middleware ВЫЗВАН для update_id: {update.update_id}")
        
        # Если есть сообщение
        if update.message:
            logger.info(f"⚡ Входящее сообщение: {update.message.text} от {update.effective_user.id}")
        # Если есть callback
        if update.callback_query:
            logger.info(f"⚡ Входящий callback: {update.callback_query.data} от {update.effective_user.id}")
        
        try:
            context = ContextTypes.DEFAULT_TYPE(self.application)
            
            # Применяем middleware
            should_continue = await self.subscription_middleware(update, context)
            logger.info(f"⚡ Middleware решение: should_continue={should_continue}")
            
            if should_continue:
                logger.info(f"⚡ Передаю управление в original_process_update")
                await self.original_process_update(update)
                logger.info(f"⚡ Управление возвращено из original_process_update")
            else:
                logger.info(f"⚡ Middleware заблокировал обработку")
                
        except Exception as e:
            logger.error(f"⚡ КРИТИЧЕСКАЯ ОШИБКА в process_update_with_middleware: {e}", exc_info=True)
    
    def reload_channels(self):
        """Перезагружает каналы из БД"""
        self.mandatory_channels = get_mandatory_channels()
        self.posting_channels = get_posting_channels()
        return self.mandatory_channels
    
    # ========== ФУНКЦИЯ ПРОВЕРКИ ПОДПИСКИ ==========
    async def get_chat_id_safe(self, identifier):
        """Безопасное получение ID чата"""
        try:
            chat = await self.application.bot.get_chat(identifier)
            return chat.id
        except Exception as e:
            logger.error(f"Ошибка при получении чата {identifier}: {e}")
            if isinstance(identifier, str) and identifier.lstrip('-').isdigit():
                return int(identifier)
            return identifier
    
    async def check_our_subscriptions(self, user_id: int) -> bool:
        """Проверка подписки на каналы"""
        channels = self.mandatory_channels
        
        if not channels:
            return True
        
        for channel in channels:
            channel_id_str = channel['id']
            
            try:
                chat_id = await self.get_chat_id_safe(channel_id_str)
                
                if chat_id is None:
                    return False
                
                member = await self.application.bot.get_chat_member(chat_id, user_id)
                status = member.status
                
                if status not in ["member", "administrator", "creator", "restricted"]:
                    return False
                    
            except Exception as e:
                logger.error(f"❌ Ошибка проверки подписки: {e}")
                return False
        
        return True
    
    def setup_conversation_handlers(self):
        """Создание ConversationHandler"""
        
        # Диалог добавления канала в ОП
        self.add_op_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.add_op_start, pattern="^add_op$")],
            states={
                ADD_OP_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_op_id)],
                ADD_OP_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_op_name)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_op)],
            name="add_op_conversation",
            persistent=False
        )
        
        # Диалог добавления канала для автопостинга
        self.add_post_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.add_post_start, pattern="^add_post$")],
            states={
                ADD_POST_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_post_id)],
                ADD_POST_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_post_name)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_post)],
            name="add_post_conversation",
            persistent=False
        )
        
        # Диалог рассылки
        self.mailing_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.mailing_start, pattern="^mailing$")],
            states={
                MAILING_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.mailing_get_text)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_mailing)],
            name="mailing_conversation",
            persistent=False
        )
    
    def setup_handlers(self):
        """Настройка обработчиков - РАЗДЕЛЬНЫЙ ПОРЯДОК"""
        
        # 1. СНАЧАЛА команды
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("stock", self.cmd_stock))
        self.application.add_handler(CommandHandler("notifications_on", self.cmd_notifications_on))
        self.application.add_handler(CommandHandler("notifications_off", self.cmd_notifications_off))
        self.application.add_handler(CommandHandler("menu", self.cmd_menu))
        self.application.add_handler(CommandHandler("admin", self.cmd_admin))
        
        # 2. ПОТОМ ConversationHandler
        self.application.add_handler(self.add_op_conv)
        self.application.add_handler(self.add_post_conv)
        self.application.add_handler(self.mailing_conv)
        
        # 3. ПОТОМ обработчик пользовательских callback'ов
        self.application.add_handler(CallbackQueryHandler(self.handle_user_callback))
        
        # 4. ПОТОМ обработчик сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("✅ Обработчики зарегистрированы")
    
    # ========== ФУНКЦИИ ОТМЕНЫ ==========
    
    async def cancel_op(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ <b>Добавление канала отменено</b>", parse_mode='HTML')
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def cancel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ <b>Добавление канала отменено</b>", parse_mode='HTML')
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def cancel_mailing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ <b>Рассылка отменена</b>", parse_mode='HTML')
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    # ========== КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ ==========
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"🚀🚀🚀 cmd_start ВЫЗВАН для {user.id}")
        self.user_manager.get_user(user.id, user.username or user.first_name)
        await self.show_main_menu(update)
    
    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_main_menu(update)
    
    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        await self.show_main_settings(update, settings)
    
    async def cmd_stock(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html("<b>🔍 Получаю актуальные данные...</b>")
        data = self.fetch_api_data(force=True)
        if not data:
            await update.message.reply_html("<b>❌ Ошибка получения данных</b>")
            return
        
        message = self.format_stock_message(data)
        if message:
            keyboard = [[InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_html(message, reply_markup=reply_markup)
    
    async def cmd_notifications_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        settings.notifications_enabled = True
        update_user_setting(user.id, 'notifications_enabled', True)
        await update.message.reply_html("<b>✅ Уведомления успешно включены!</b>")
    
    async def cmd_notifications_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        settings.notifications_enabled = False
        update_user_setting(user.id, 'notifications_enabled', False)
        await update.message.reply_html("<b>❌ Уведомления успешно выключены</b>")
    
    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        if not settings.is_admin:
            await update.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return
        
        self.reload_channels()
        await self.show_admin_panel(update)
    
    # ========== АДМИН-ПАНЕЛЬ ==========
    
    async def show_admin_panel(self, update: Update):
        """Показ админ-панели"""
        users_count = get_users_count()
        
        text = (
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
            f"👥 <b>Пользователей в боте:</b> {users_count}\n"
            f"🔐 <b>Каналов ОП:</b> {len(self.mandatory_channels)}\n"
            f"📢 <b>Каналов для автопостинга:</b> {len(self.posting_channels)}\n\n"
            "<b>Выберите действие:</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔐 УПРАВЛЕНИЕ ОП", callback_data="admin_op")],
            [InlineKeyboardButton("📢 УПРАВЛЕНИЕ АВТОПОСТИНГОМ", callback_data="admin_post")],
            [InlineKeyboardButton("📧 РАССЫЛКА", callback_data="mailing")],
            [InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="admin_stats")],
            [InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
        ]
        
        if update.message:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_admin_panel_callback(self, query):
        """Показ админ-панели из callback"""
        users_count = get_users_count()
        
        text = (
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
            f"👥 <b>Пользователей в боте:</b> {users_count}\n"
            f"🔐 <b>Каналов ОП:</b> {len(self.mandatory_channels)}\n"
            f"📢 <b>Каналов для автопостинга:</b> {len(self.posting_channels)}\n\n"
            "<b>Выберите действие:</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔐 УПРАВЛЕНИЕ ОП", callback_data="admin_op")],
            [InlineKeyboardButton("📢 УПРАВЛЕНИЕ АВТОПОСТИНГОМ", callback_data="admin_post")],
            [InlineKeyboardButton("📧 РАССЫЛКА", callback_data="mailing")],
            [InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="admin_stats")],
            [InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
        ]
        
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ========== УПРАВЛЕНИЕ ОП ==========
    
    async def show_op_menu(self, query):
        """Меню управления ОП"""
        self.reload_channels()
        
        text = (
            "🔐 <b>УПРАВЛЕНИЕ ОБЯЗАТЕЛЬНОЙ ПОДПИСКОЙ (ОП)</b>\n\n"
            "<b>Каналы, на которые нужно подписаться для доступа к боту</b>\n\n"
            "<b>Выберите действие:</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("➕ ДОБАВИТЬ КАНАЛ", callback_data="add_op")],
            [InlineKeyboardButton("🗑 УДАЛИТЬ КАНАЛ", callback_data="op_remove")],
            [InlineKeyboardButton("📋 СПИСОК КАНАЛОВ", callback_data="op_list")],
            [InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_panel")]
        ]
        
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def add_op_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало добавления канала в ОП"""
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        
        if user_id != ADMIN_ID:
            await query.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return ConversationHandler.END
        
        await query.message.reply_text(
            "📢 <b>Добавление канала в обязательную подписку</b>\n\n"
            "Отправьте <b>@username</b> канала или перешлите сообщение:",
            parse_mode='HTML'
        )
        return ADD_OP_CHANNEL_ID
    
    async def add_op_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        channel_id = update.message.text.strip()
        
        context.user_data['op_channel_id'] = channel_id
        await update.message.reply_text("✏️ <b>Теперь отправьте название канала</b> (для отображения):", parse_mode='HTML')
        return ADD_OP_CHANNEL_NAME
    
    async def add_op_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        channel_name = update.message.text.strip()
        channel_id = context.user_data.get('op_channel_id')
        
        try:
            if channel_id.startswith('@'):
                chat = await self.application.bot.get_chat(channel_id)
            else:
                chat = await self.application.bot.get_chat(int(channel_id))
            
            bot_member = await self.application.bot.get_chat_member(chat.id, self.application.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "❌ <b>Бот не является администратором этого канала!</b>\n"
                    "Сделайте бота админом и попробуйте снова.",
                    parse_mode='HTML'
                )
                await self.show_admin_panel(update)
                return ConversationHandler.END
            
            final_id = f"@{chat.username}" if chat.username else str(chat.id)
            add_mandatory_channel(final_id, channel_name)
            
            self.reload_channels()
            
            await update.message.reply_text(
                f"✅ <b>Канал {channel_name} добавлен в обязательную подписку!</b>",
                parse_mode='HTML'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Ошибка:</b> {e}", parse_mode='HTML')
        
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def show_op_remove(self, query):
        """Показ списка каналов для удаления из ОП"""
        self.reload_channels()
        
        if not self.mandatory_channels:
            await query.message.reply_text("📭 <b>Нет каналов для удаления</b>", parse_mode='HTML')
            return
        
        text = "🗑 <b>Выберите канал для удаления из ОП:</b>"
        keyboard = []
        for ch in self.mandatory_channels:
            keyboard.append([InlineKeyboardButton(f"❌ {ch['name']}", callback_data=f"op_del_{ch['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_op")])
        
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def delete_op_channel(self, query):
        """Удаление канала из ОП"""
        channel_id = query.data.replace('op_del_', '')
        remove_mandatory_channel(channel_id)
        self.reload_channels()
        await query.answer("✅ Канал удален из ОП!")
        await self.show_op_remove(query)
    
    async def show_op_list(self, query):
        """Показ списка каналов ОП"""
        self.reload_channels()
        
        if not self.mandatory_channels:
            text = "📭 <b>Нет каналов в обязательной подписке</b>"
        else:
            text = "<b>📋 КАНАЛЫ ОБЯЗАТЕЛЬНОЙ ПОДПИСКИ (ОП)</b>\n\n"
            for ch in self.mandatory_channels:
                text += f"• <b>{ch['name']}</b> (ID: <code>{ch['id']}</code>)\n"
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_op")]]
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ========== УПРАВЛЕНИЕ АВТОПОСТИНГОМ ==========
    
    async def show_post_menu(self, query):
        """Меню управления автопостингом"""
        self.reload_channels()
        
        text = (
            "📢 <b>УПРАВЛЕНИЕ АВТОПОСТИНГОМ</b>\n\n"
            "<b>Каналы, в которые бот будет отправлять уведомления</b>\n\n"
            "<b>Выберите действие:</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("➕ ДОБАВИТЬ КАНАЛ", callback_data="add_post")],
            [InlineKeyboardButton("🗑 УДАЛИТЬ КАНАЛ", callback_data="post_remove")],
            [InlineKeyboardButton("📋 СПИСОК КАНАЛОВ", callback_data="post_list")],
            [InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_panel")]
        ]
        
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def add_post_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало добавления канала в автопостинг"""
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        
        if user_id != ADMIN_ID:
            await query.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return ConversationHandler.END
        
        await query.message.reply_text(
            "📢 <b>Добавление канала для автопостинга</b>\n\n"
            "Отправьте <b>ID канала</b> или <b>username</b> (@channel):",
            parse_mode='HTML'
        )
        return ADD_POST_CHANNEL_ID
    
    async def add_post_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        channel_id = update.message.text.strip()
        
        context.user_data['post_channel_id'] = channel_id
        await update.message.reply_text("✏️ <b>Теперь отправьте название канала</b> (для отображения):", parse_mode='HTML')
        return ADD_POST_CHANNEL_NAME
    
    async def add_post_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        channel_name = update.message.text.strip()
        channel_id = context.user_data.get('post_channel_id')
        
        try:
            if channel_id.startswith('@'):
                chat = await self.application.bot.get_chat(channel_id)
            else:
                chat = await self.application.bot.get_chat(int(channel_id))
            
            bot_member = await self.application.bot.get_chat_member(chat.id, self.application.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "❌ <b>Бот не является администратором этого канала!</b>\n"
                    "Сделайте бота админом и попробуйте снова.",
                    parse_mode='HTML'
                )
                await self.show_admin_panel(update)
                return ConversationHandler.END
            
            add_posting_channel(str(chat.id), channel_name, chat.username)
            self.reload_channels()
            
            await update.message.reply_text(
                f"✅ <b>Канал {channel_name} добавлен для автопостинга!</b>",
                parse_mode='HTML'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Ошибка:</b> {e}", parse_mode='HTML')
        
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def show_post_remove(self, query):
        """Показ списка каналов для удаления из автопостинга"""
        self.reload_channels()
        
        if not self.posting_channels:
            await query.message.reply_text("📭 <b>Нет каналов для удаления</b>", parse_mode='HTML')
            await self.show_post_menu(query)
            return
        
        text = "🗑 <b>Выберите канал для удаления из автопостинга:</b>"
        keyboard = []
        for ch in self.posting_channels:
            keyboard.append([InlineKeyboardButton(f"❌ {ch['name']}", callback_data=f"post_del_{ch['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_post")])
        
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def delete_post_channel(self, query):
        """Удаление канала из автопостинга"""
        channel_id = query.data.replace('post_del_', '')
        remove_posting_channel(channel_id)
        self.reload_channels()
        await query.answer("✅ Канал удален из автопостинга!")
        await self.show_post_remove(query)
    
    async def show_post_list(self, query):
        """Показ списка каналов автопостинга"""
        self.reload_channels()
        
        if not self.posting_channels:
            text = "📭 <b>Нет каналов для автопостинга</b>"
        else:
            text = "<b>📢 КАНАЛЫ ДЛЯ АВТОПОСТИНГА</b>\n\n"
            for ch in self.posting_channels:
                text += f"• <b>{ch['name']}</b> (ID: <code>{ch['id']}</code>)\n"
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_post")]]
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ========== РАССЫЛКА ==========
    
    async def mailing_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало рассылки"""
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        
        if user_id != ADMIN_ID:
            await query.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return ConversationHandler.END
        
        if 'mailing_text' in context.user_data:
            del context.user_data['mailing_text']
        
        await query.message.reply_text(
            "📧 <b>Рассылка</b>\n\nВведите текст для рассылки:",
            parse_mode='HTML'
        )
        return MAILING_TEXT
    
    async def mailing_get_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        
        context.user_data['mailing_text'] = text
        
        keyboard = [
            [InlineKeyboardButton("✅ ОТПРАВИТЬ", callback_data="mailing_yes"),
             InlineKeyboardButton("❌ ОТМЕНИТЬ", callback_data="mailing_no")]
        ]
        
        await update.message.reply_text(
            f"<b>📧 Подтверждение рассылки</b>\n\n{text}\n\n<b>Отправить?</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return ConversationHandler.END
    
    async def mailing_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение и отправка рассылки"""
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        
        if query.data == "mailing_no":
            await query.message.reply_text("❌ <b>Рассылка отменена</b>", parse_mode='HTML')
            await self.show_admin_panel_callback(query)
            return
        
        text = context.user_data.get('mailing_text', '')
        if not text:
            await query.message.reply_text("❌ <b>Ошибка: текст не найден</b>", parse_mode='HTML')
            await self.show_admin_panel_callback(query)
            return
        
        await query.message.reply_text("📧 <b>Начинаю рассылку...</b>", parse_mode='HTML')
        
        success = 0
        failed = 0
        users = get_all_users()
        
        for uid in users:
            try:
                await self.application.bot.send_message(
                    chat_id=uid,
                    text=f"<b>📢 РАССЫЛКА</b>\n\n{text}",
                    parse_mode='HTML'
                )
                success += 1
                await asyncio.sleep(0.05)
            except Forbidden as e:
                failed += 1
                logger.warning(f"⚠️ Пользователь {uid} заблокировал бота, пропускаем")
            except Exception as e:
                failed += 1
                logger.error(f"❌ Ошибка отправки пользователю {uid}: {e}")
        
        await query.message.reply_text(
            f"<b>📊 ОТЧЕТ О РАССЫЛКЕ</b>\n\n"
            f"✅ <b>Успешно:</b> {success}\n"
            f"❌ <b>Ошибок:</b> {failed}\n"
            f"👥 <b>Всего:</b> {len(users)}",
            parse_mode='HTML'
        )
        
        if 'mailing_text' in context.user_data:
            del context.user_data['mailing_text']
        
        await self.show_admin_panel_callback(query)
    
    # ========== СТАТИСТИКА ==========
    
    async def show_stats(self, query):
        """Показ статистики"""
        users_count = get_users_count()
        
        text = (
            "<b>📊 СТАТИСТИКА БОТА</b>\n\n"
            f"👥 <b>Всего пользователей:</b> {users_count}\n"
            f"🔐 <b>Каналов ОП:</b> {len(self.mandatory_channels)}\n"
            f"📢 <b>Каналов для автопостинга:</b> {len(self.posting_channels)}"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_panel")]]
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    # ========== ОСНОВНОЕ МЕНЮ ==========
    
    async def show_main_menu(self, update: Update):
        """Показ главного меню"""
        user = update.effective_user
        logger.info(f"🌱🌱🌱 show_main_menu вызван для {user.id}")
        settings = self.user_manager.get_user(user.id)
        
        text = MAIN_MENU_TEXT
        
        keyboard = [
            [InlineKeyboardButton("⚙️ АВТО-СТОК", callback_data="menu_settings"),
             InlineKeyboardButton("📦 СТОК", callback_data="menu_stock")],
            [InlineKeyboardButton("🔔 УВЕДОМЛЕНИЯ ВКЛ", callback_data="notifications_on"),
             InlineKeyboardButton("🔕 УВЕДОМЛЕНИЯ ВЫКЛ", callback_data="notifications_off")]
        ]
        
        if settings.is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        reply_markup_remove = ReplyKeyboardMarkup([[]], resize_keyboard=True)
        
        if update.message:
            # Для обычного сообщения - показываем "Обновляю меню"
            await update.message.reply_text("🔄 <b>Обновляю меню...</b>", reply_markup=reply_markup_remove, parse_mode='HTML')
            await update.message.reply_photo(photo=IMAGE_MAIN, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        elif update.callback_query:
            # Для callback - просто показываем меню без лишних сообщений
            await self.show_main_menu_callback(update.callback_query)
    
    async def show_main_menu_callback(self, query):
        """Показ главного меню из callback"""
        user = query.from_user
        logger.info(f"🌱 show_main_menu_callback вызван для {user.id}")
        settings = self.user_manager.get_user(user.id)
        
        text = MAIN_MENU_TEXT
        
        keyboard = [
            [InlineKeyboardButton("⚙️ АВТО-СТОК", callback_data="menu_settings"),
             InlineKeyboardButton("📦 СТОК", callback_data="menu_stock")],
            [InlineKeyboardButton("🔔 УВЕДОМЛЕНИЯ ВКЛ", callback_data="notifications_on"),
             InlineKeyboardButton("🔕 УВЕДОМЛЕНИЯ ВЫКЛ", callback_data="notifications_off")]
        ]
        
        if settings.is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            await query.message.reply_photo(photo=IMAGE_MAIN, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_main_settings(self, update: Update, settings: UserSettings):
        """Показ настроек"""
        status = "🔔 ВКЛ" if settings.notifications_enabled else "🔕 ВЫКЛ"
        text = f"<b>⚙️ АВТО-СТОК</b>\n\n<b>Уведомления: {status}</b>\n\nВыберите категорию:"
        keyboard = [
            [InlineKeyboardButton("🌱 СЕМЕНА", callback_data="settings_seeds"),
             InlineKeyboardButton("⚙️ СНАРЯЖЕНИЕ", callback_data="settings_gear")],
            [InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather"),
             InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
        ]
        
        if update.message:
            await update.message.reply_photo(photo=IMAGE_MAIN, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        elif update.callback_query:
            await self.show_main_settings_callback(update.callback_query, settings)
    
    async def show_main_settings_callback(self, query, settings: UserSettings):
        """Показ настроек из callback"""
        status = "🔔 ВКЛ" if settings.notifications_enabled else "🔕 ВЫКЛ"
        text = f"<b>⚙️ АВТО-СТОК</b>\n\n<b>Уведомления: {status}</b>\n\nВыберите категорию:"
        keyboard = [
            [InlineKeyboardButton("🌱 СЕМЕНА", callback_data="settings_seeds"),
             InlineKeyboardButton("⚙️ СНАРЯЖЕНИЕ", callback_data="settings_gear")],
            [InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather"),
             InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
        ]
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            await query.message.reply_photo(photo=IMAGE_MAIN, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_seeds_settings(self, query, settings: UserSettings):
        """Показ настроек семян"""
        text = "<b>🌱 НАСТРОЙКИ СЕМЯН</b>\n\nНажмите на семя:"
        keyboard, row = [], []
        for seed_name in SEEDS_LIST:
            enabled = settings.seeds.get(seed_name, ItemSettings()).enabled
            status = "✅" if enabled else "❌"
            button_text = f"{status} {translate(seed_name)}"
            row.append(InlineKeyboardButton(button_text, callback_data=f"seed_toggle_{seed_name}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")])
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_SEEDS, caption=text, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            await query.message.reply_photo(photo=IMAGE_SEEDS, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_gear_settings(self, query, settings: UserSettings):
        """Показ настроек снаряжения"""
        text = "<b>⚙️ НАСТРОЙКИ СНАРЯЖЕНИЯ</b>\n\nНажмите на предмет:"
        keyboard, row = [], []
        for gear_name in GEAR_LIST:
            enabled = settings.gear.get(gear_name, ItemSettings()).enabled
            status = "✅" if enabled else "❌"
            button_text = f"{status} {translate(gear_name)}"
            row.append(InlineKeyboardButton(button_text, callback_data=f"gear_toggle_{gear_name}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")])
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_GEAR, caption=text, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            await query.message.reply_photo(photo=IMAGE_GEAR, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_weather_settings(self, query, settings: UserSettings):
        """Показ настроек погоды"""
        text = "<b>🌤️ НАСТРОЙКИ ПОГОДЫ</b>\n\nНажмите на погоду:"
        keyboard, row = [], []
        for weather_name in WEATHER_LIST:
            enabled = settings.weather.get(weather_name, ItemSettings()).enabled
            status = "✅" if enabled else "❌"
            button_text = f"{status} {translate(weather_name)}"
            row.append(InlineKeyboardButton(button_text, callback_data=f"weather_toggle_{weather_name}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")])
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_WEATHER, caption=text, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            await query.message.reply_photo(photo=IMAGE_WEATHER, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_stock_callback(self, query):
        """Показ текущего стока"""
        logger.info(f"📦 show_stock_callback вызван для {query.from_user.id}")
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_MAIN, caption="<b>🔍 Получаю данные...</b>", parse_mode='HTML')
            )
        except:
            pass
        
        data = self.fetch_api_data(force=True)
        if not data:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_MAIN, caption="<b>❌ Ошибка получения данных</b>", parse_mode='HTML')
            )
            return
        
        message = self.format_stock_message(data)
        if message:
            keyboard = [[InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]]
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_MAIN, caption=message, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def handle_seed_callback(self, query, settings: UserSettings):
        """Обработка настроек семян"""
        parts = query.data.split("_")
        if len(parts) >= 3:
            seed_name = "_".join(parts[2:])
            enabled = not settings.seeds[seed_name].enabled
            settings.seeds[seed_name].enabled = enabled
            update_user_setting(settings.user_id, f"seed_{seed_name}", enabled)
            await self.show_seeds_settings(query, settings)
    
    async def handle_gear_callback(self, query, settings: UserSettings):
        """Обработка настроек снаряжения"""
        parts = query.data.split("_")
        if len(parts) >= 3:
            gear_name = "_".join(parts[2:])
            enabled = not settings.gear[gear_name].enabled
            settings.gear[gear_name].enabled = enabled
            update_user_setting(settings.user_id, f"gear_{gear_name}", enabled)
            await self.show_gear_settings(query, settings)
    
    async def handle_weather_callback(self, query, settings: UserSettings):
        """Обработка настроек погоды"""
        parts = query.data.split("_")
        if len(parts) >= 3:
            weather_name = "_".join(parts[2:])
            enabled = not settings.weather[weather_name].enabled
            settings.weather[weather_name].enabled = enabled
            update_user_setting(settings.user_id, f"weather_{weather_name}", enabled)
            await self.show_weather_settings(query, settings)
    
    # ========== НОВЫЙ ОБРАБОТЧИК ПОЛЬЗОВАТЕЛЬСКИХ CALLBACK ==========
    
    async def handle_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ТОЛЬКО пользовательских кнопок (меню, настройки и т.д.)"""
        query = update.callback_query
        user = update.effective_user
        
        # СРАЗУ отвечаем, чтобы убрать "часики"
        await query.answer()
        
        logger.info(f"🔘🔘🔘 handle_user_callback ВЫЗВАН: {query.data} от {user.id}")
        
        # Получаем настройки пользователя
        settings = self.user_manager.get_user(user.id)
        
        # ===== ПРЯМАЯ ОБРАБОТКА ВСЕХ КНОПОК =====
        if query.data == "menu_stock":
            logger.info("📦 Обработка menu_stock")
            await self.show_stock_callback(query)
            return
        
        if query.data == "menu_main":
            logger.info("🏠 Обработка menu_main")
            await self.show_main_menu_callback(query)
            return
        
        if query.data == "menu_settings":
            logger.info("⚙️ Обработка menu_settings")
            await self.show_main_settings_callback(query, settings)
            return
        
        if query.data == "notifications_on":
            logger.info("🔔 Обработка notifications_on")
            settings.notifications_enabled = True
            update_user_setting(user.id, 'notifications_enabled', True)
            await query.message.reply_html("<b>✅ Уведомления включены!</b>")
            return
        
        if query.data == "notifications_off":
            logger.info("🔕 Обработка notifications_off")
            settings.notifications_enabled = False
            update_user_setting(user.id, 'notifications_enabled', False)
            await query.message.reply_html("<b>❌ Уведомления выключены</b>")
            return
        
        if query.data == "settings_seeds":
            logger.info("🌱 Обработка settings_seeds")
            await self.show_seeds_settings(query, settings)
            return
        
        if query.data == "settings_gear":
            logger.info("⚙️ Обработка settings_gear")
            await self.show_gear_settings(query, settings)
            return
        
        if query.data == "settings_weather":
            logger.info("🌤️ Обработка settings_weather")
            await self.show_weather_settings(query, settings)
            return
        
        # ===== ОБРАБОТКА ТОГГЛОВ =====
        if query.data.startswith("seed_toggle_"):
            logger.info(f"🌱 Обработка seed_toggle: {query.data}")
            await self.handle_seed_callback(query, settings)
            return
        
        if query.data.startswith("gear_toggle_"):
            logger.info(f"⚙️ Обработка gear_toggle: {query.data}")
            await self.handle_gear_callback(query, settings)
            return
        
        if query.data.startswith("weather_toggle_"):
            logger.info(f"🌤️ Обработка weather_toggle: {query.data}")
            await self.handle_weather_callback(query, settings)
            return
        
        # ===== ВАЖНО: check_our_sub ДО проверки на админа =====
        if query.data == "check_our_sub":
            logger.info(f"✅ Обработка check_our_sub для {user.id}")
            is_subscribed = await self.check_our_subscriptions(user.id)
            
            if is_subscribed:
                add_user_to_db(user.id, user.username or user.first_name)
                
                # Удаляем сообщение с кнопками
                try:
                    await query.message.delete()
                except:
                    pass
                
                # ✅ Отправляем подтверждение ОТДЕЛЬНЫМ сообщением
                await query.message.answer("✅ <b>Подписка подтверждена!</b>", parse_mode='HTML')
                
                # ✅ Отправляем главное меню отдельным сообщением (без "Обновляю меню")
                # Создаем фейковый update для show_main_menu
                class FakeMessage:
                    def __init__(self, chat):
                        self.chat = chat
                        self.from_user = user  # Добавляем from_user
                
                class FakeUpdate:
                    def __init__(self, chat, user):
                        self.effective_user = user
                        self.message = FakeMessage(chat)
                        self.callback_query = None
                
                fake_update = FakeUpdate(query.message.chat, user)
                await self.show_main_menu(fake_update)
            else:
                await query.answer("❌ Подписка не подтверждена!", show_alert=True)
            return
        
        # ===== АДМИН-КНОПКИ ===== (ЭТО ДОЛЖНО БЫТЬ ПОСЛЕ)
        if not settings.is_admin:
            logger.warning(f"⚠️ Неизвестный callback от не-админа: {query.data}")
            return
        
        if query.data == "admin_panel":
            logger.info("👑 Обработка admin_panel")
            await self.show_admin_panel_callback(query)
            return
        
        if query.data == "admin_op":
            logger.info("🔐 Обработка admin_op")
            await self.show_op_menu(query)
            return
        
        if query.data == "op_remove":
            logger.info("🗑 Обработка op_remove")
            await self.show_op_remove(query)
            return
        
        if query.data == "op_list":
            logger.info("📋 Обработка op_list")
            await self.show_op_list(query)
            return
        
        if query.data.startswith("op_del_"):
            logger.info(f"❌ Обработка op_del: {query.data}")
            await self.delete_op_channel(query)
            return
        
        if query.data == "admin_post":
            logger.info("📢 Обработка admin_post")
            await self.show_post_menu(query)
            return
        
        if query.data == "post_remove":
            logger.info("🗑 Обработка post_remove")
            await self.show_post_remove(query)
            return
        
        if query.data == "post_list":
            logger.info("📋 Обработка post_list")
            await self.show_post_list(query)
            return
        
        if query.data.startswith("post_del_"):
            logger.info(f"❌ Обработка post_del: {query.data}")
            await self.delete_post_channel(query)
            return
        
        if query.data == "admin_stats":
            logger.info("📊 Обработка admin_stats")
            await self.show_stats(query)
            return
        
        if query.data in ["mailing_yes", "mailing_no"]:
            logger.info(f"📧 Обработка mailing: {query.data}")
            await self.mailing_confirm(update, context)
            return
        
        logger.warning(f"⚠️ Неизвестный callback: {query.data}")
    
    # ========== ОБРАБОТКА СООБЩЕНИЙ ==========
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        text = update.message.text
        
        logger.info(f"📨 handle_message вызван для {user.id}: {text}")
        
        if any(key in context.user_data for key in ['op_channel_id', 'post_channel_id', 'mailing_text']):
            logger.info(f"⏩ Пользователь {user.id} в диалоге, пропускаю")
            return
        
        if text == "🏠 ГЛАВНОЕ МЕНЮ":
            logger.info(f"🏠 Возврат в главное меню пользователем {user.id}")
            reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await update.message.reply_text("🔄 <b>Возвращаюсь в главное меню...</b>", reply_markup=reply_markup, parse_mode='HTML')
            await self.show_main_menu(update)
    
    # ========== РАБОТА С API ==========
    
    def fetch_api_data(self, force=False) -> Optional[Dict]:
        try:
            rand = random.randint(1000, 9999)
            url = f"{API_URL}?r={rand}"
            if force:
                url = f"{API_URL}?t={int(datetime.now().timestamp())}&r={rand}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
            
            response = self.session.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            
            if data.get("ok") and "data" in data:
                return data["data"]
            return None
            
        except Exception as e:
            logger.error(f"❌ Ошибка API: {e}")
            return None
    
    def format_stock_message(self, data: Dict) -> Optional[str]:
        parts = []
        if "seeds" in data:
            seeds = []
            for s in data["seeds"]:
                if s["quantity"] > 0 and s["name"] in TRANSLATIONS:
                    translated = translate(s["name"])
                    seeds.append(f"  • <b>{translated}</b>: {s['quantity']} шт.")
            if seeds:
                parts.append("<b>🌱 СЕМЕНА:</b>\n" + "\n".join(seeds))
        if "gear" in data:
            gear = []
            for g in data["gear"]:
                if g["quantity"] > 0 and g["name"] in TRANSLATIONS:
                    translated = translate(g["name"])
                    gear.append(f"  • <b>{translated}</b>: {g['quantity']} шт.")
            if gear:
                parts.append("<b>⚙️ СНАРЯЖЕНИЕ:</b>\n" + "\n".join(gear))
        
        if "weather" in data:
            weather_data = data["weather"]
            if is_weather_active(weather_data):
                wtype = weather_data["type"]
                end_timestamp = weather_data.get("endTimestamp")
                
                if end_timestamp and wtype in TRANSLATIONS:
                    msk_time = get_msk_time_from_timestamp(end_timestamp)
                    parts.append(f"<b>{translate(wtype)} АКТИВНА</b> до {msk_time} (МСК)")
                elif wtype in TRANSLATIONS:
                    parts.append(f"<b>{translate(wtype)} АКТИВНА</b>")
        
        return "\n\n".join(parts) if parts else None
    
    def format_channel_message(self, item_name: str, quantity: int) -> str:
        translated = translate(item_name)
        return (
            f"✨ <b>{translated}</b>\n"
            f"📦 <b>Количество:</b> {quantity} шт.\n"
            f"━━━━━━━━━━━━━━\n"
            f"<a href='{DEFAULT_REQUIRED_CHANNEL_LINK}'>📢 Наш канал</a> | <a href='{BOT_LINK}'>🤖 Авто-сток</a> | <a href='{CHAT_LINK}'>💬 Наш чат</a>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👀 Включи уведомления в канале!"
        )
    
    def format_pm_message(self, items: List[tuple]) -> str:
        if not items:
            return None
        
        message = "<b>🔔 НОВЫЕ ПРЕДМЕТЫ В СТОКЕ</b>\n\n"
        
        weather_items = [i for i in items if i[0] in WEATHER_LIST]
        seed_items = [i for i in items if i[0] in SEEDS_LIST]
        gear_items = [i for i in items if i[0] in GEAR_LIST]
        
        for item_name, quantity in weather_items:
            translated = translate(item_name)
            message += f"<b>🌤️ Активна погода!</b> {translated}\n"
        
        for item_name, quantity in seed_items:
            translated = translate(item_name)
            message += f"<b>{translated}:</b> {quantity} шт.\n"
        
        for item_name, quantity in gear_items:
            translated = translate(item_name)
            message += f"<b>{translated}:</b> {quantity} шт.\n"
        
        return message
    
    def format_weather_started_message(self, weather_type: str, end_timestamp: int = None) -> str:
        """Формирует сообщение о начале погоды с московским временем"""
        translated = translate(weather_type)
        if end_timestamp:
            try:
                msk_time = get_msk_time_from_timestamp(end_timestamp)
                return f"<b>🌤️ Началась погода {translated}! Активна до {msk_time} (МСК)</b>"
            except:
                return f"<b>🌤️ Началась погода {translated}!</b>"
        return f"<b>🌤️ Началась погода {translated}!</b>"
    
    def format_weather_ended_message(self, weather_type: str) -> str:
        """Формирует сообщение о конце погоды"""
        translated = translate(weather_type)
        return f"<b>🌤️ Погода {translated} закончилась!</b>"
    
    def get_all_current_items(self, data: Dict) -> Dict[str, int]:
        all_items = {}
        
        if "seeds" in data:
            for item in data["seeds"]:
                name = item["name"]
                if name in TRANSLATIONS and item["quantity"] > 0:
                    all_items[name] = item["quantity"]
                    logger.info(f"📦 Найден предмет из API: {name} = {item['quantity']}")
        
        if "gear" in data:
            for item in data["gear"]:
                name = item["name"]
                if name in TRANSLATIONS and item["quantity"] > 0:
                    all_items[name] = item["quantity"]
                    logger.info(f"🔧 Найден предмет из API: {name} = {item['quantity']}")
        
        if "weather" in data:
            weather_data = data["weather"]
            if is_weather_active(weather_data):
                wtype = weather_data.get("type")
                if wtype and wtype in TRANSLATIONS:
                    all_items[wtype] = 1
                    logger.info(f"🌤️ Активная погода: {wtype}")
        
        logger.info(f"📊 Всего предметов из API: {len(all_items)}")
        return all_items
    
    def get_weather_change(self, old_data: Dict, new_data: Dict) -> tuple:
        """
        Определяет изменение погоды
        Возвращает (статус, тип_погоды, время_окончания)
        статус: 'started', 'ended', None
        """
        if not old_data or not new_data:
            return None, None, None
        
        old_weather = old_data.get("weather", {})
        new_weather = new_data.get("weather", {})
        
        old_active = is_weather_active(old_weather)
        new_active = is_weather_active(new_weather)
        
        old_type = old_weather.get("type") if old_active else None
        new_type = new_weather.get("type") if new_active else None
        new_end = new_weather.get("endTimestamp") if new_active else None
        
        # Погода началась
        if not old_active and new_active:
            return 'started', new_type, new_end
        
        # Погода закончилась
        if old_active and not new_active:
            return 'ended', old_type, None
        
        # Погода изменилась на другой тип
        if old_active and new_active and old_type != new_type:
            return 'ended', old_type, None
        
        return None, None, None
    
    def get_user_items_to_send(self, all_items: Dict[str, int], settings: UserSettings, user_id: int, update_id: str) -> List[tuple]:
        user_items = []
        
        for name, quantity in all_items.items():
            if name in SEEDS_LIST:
                if not settings.seeds.get(name, ItemSettings()).enabled:
                    continue
            elif name in GEAR_LIST:
                if not settings.gear.get(name, ItemSettings()).enabled:
                    continue
            elif name in WEATHER_LIST:
                if not settings.weather.get(name, ItemSettings()).enabled:
                    continue
            
            if not was_item_sent_to_user(user_id, name, quantity, update_id):
                user_items.append((name, quantity))
        
        return user_items
    
    # ========== ОСНОВНОЙ ЦИКЛ МОНИТОРИНГА ==========
    
    async def monitor_loop(self):
        logger.info("🚀 Запущен цикл мониторинга API")
        
        # ===== ТЕСТОВАЯ ДИАГНОСТИКА КАНАЛОВ ПРИ ЗАПУСКЕ =====
        try:
            logger.info("🔍========== ДИАГНОСТИКА КАНАЛОВ ==========")
            
            # Проверяем основной канал
            if MAIN_CHANNEL_ID:
                try:
                    chat = await self.application.bot.get_chat(int(MAIN_CHANNEL_ID))
                    bot_member = await self.application.bot.get_chat_member(int(MAIN_CHANNEL_ID), self.application.bot.id)
                    logger.info(f"📢 Основной канал: {chat.title} (ID: {MAIN_CHANNEL_ID})")
                    logger.info(f"   Статус бота: {bot_member.status}")
                    if bot_member.status in ['administrator', 'creator']:
                        logger.info(f"   ✅ Бот админ в основном канале")
                    else:
                        logger.error(f"   ❌ БОТ НЕ АДМИН В ОСНОВНОМ КАНАЛЕ! Статус: {bot_member.status}")
                except Exception as e:
                    logger.error(f"❌ Ошибка проверки основного канала: {e}")
            
            # Проверяем каналы автопостинга
            logger.info(f"📢 Каналов автопостинга: {len(self.posting_channels)}")
            for i, channel in enumerate(self.posting_channels):
                try:
                    chat = await self.application.bot.get_chat(int(channel['id']))
                    bot_member = await self.application.bot.get_chat_member(int(channel['id']), self.application.bot.id)
                    logger.info(f"📢 Канал {i+1}: {channel['name']} (ID: {channel['id']})")
                    logger.info(f"   Название: {chat.title}")
                    logger.info(f"   Статус бота: {bot_member.status}")
                    if bot_member.status in ['administrator', 'creator']:
                        logger.info(f"   ✅ Бот админ")
                    else:
                        logger.warning(f"   ⚠️ БОТ НЕ АДМИН! Уведомления в этот канал отправляться НЕ БУДУТ")
                except Exception as e:
                    logger.error(f"❌ Ошибка проверки канала {channel['name']}: {e}")
            
            logger.info("🔍========== ДИАГНОСТИКА ЗАВЕРШЕНА ==========")
        except Exception as e:
            logger.error(f"❌ Ошибка при диагностике: {e}")
        
        while True:
            try:
                start_time = datetime.now()
                new_data = self.fetch_api_data(force=True)
                
                if new_data and self.last_data:
                    # Переменные для отслеживания изменений
                    weather_changed = False
                    weather_info = None
                    weather_type = None
                    
                    # Проверяем изменения в погоде
                    weather_status, wtype, end_timestamp = self.get_weather_change(self.last_data, new_data)
                    
                    if weather_status and wtype:
                        update_id = f"weather_{weather_status}_{datetime.now().isoformat()}"
                        
                        if not was_weather_notification_sent(wtype, weather_status, update_id):
                            weather_changed = True
                            weather_type = wtype
                            if weather_status == 'started':
                                weather_info = self.format_weather_started_message(wtype, end_timestamp)
                            else:
                                weather_info = self.format_weather_ended_message(wtype)
                            
                            mark_weather_notification_sent(wtype, weather_status, update_id)
                    
                    # Проверяем изменения в стоке
                    if new_data.get("lastGlobalUpdate") != self.last_data.get("lastGlobalUpdate") or weather_changed:
                        if new_data.get("lastGlobalUpdate") != self.last_data.get("lastGlobalUpdate"):
                            logger.info(f"✅ Обнаружены изменения в API! Новый update_id: {new_data.get('lastGlobalUpdate')}")
                        else:
                            logger.info(f"✅ Обнаружены изменения в погоде!")
                        
                        all_items = self.get_all_current_items(new_data)
                        
                        if all_items or weather_info:
                            update_id = new_data.get('lastGlobalUpdate', datetime.now().isoformat())
                            
                            # Формируем сообщение для каналов (только сток)
                            main_channel_items = {}
                            for name, qty in all_items.items():
                                if is_allowed_for_main_channel(name):
                                    main_channel_items[name] = qty
                            
                            logger.info(f"📊 Предметов для каналов: {len(main_channel_items)}")
                            
                            # 1. Отправляем в ОСНОВНОЙ канал
                            if MAIN_CHANNEL_ID and main_channel_items:
                                logger.info(f"📢 НАЧАЛО отправки в ОСНОВНОЙ канал")
                                for name, qty in main_channel_items.items():
                                    logger.info(f"🔍 Проверка дубликата: {name}={qty}, update_id={update_id}")
                                    if not was_item_sent(int(MAIN_CHANNEL_ID), name, qty, update_id):
                                        msg = self.format_channel_message(name, qty)
                                        await self.message_queue.queue.put((int(MAIN_CHANNEL_ID), msg, 'HTML', None))
                                        mark_item_sent(int(MAIN_CHANNEL_ID), name, qty, update_id)
                                        logger.info(f"📢 В основной канал: {name} = {qty} (update_id: {update_id})")
                                    else:
                                        logger.info(f"⏭️ Предмет {name} = {qty} уже отправлен для update_id={update_id}")
                            
                            # 2. Отправляем в ДОПОЛНИТЕЛЬНЫЕ каналы (автопостинг)
                            logger.info(f"📢 НАЧАЛО отправки в каналы автопостинга. Всего каналов: {len(self.posting_channels)}")
                            for channel in self.posting_channels:
                                logger.info(f"🔍 Обрабатываю канал: {channel['name']} (ID: {channel['id']})")
                                
                                try:
                                    bot_member = await self.application.bot.get_chat_member(int(channel['id']), self.application.bot.id)
                                    logger.info(f"   Статус бота в канале: {bot_member.status}")
                                    
                                    if bot_member.status not in ['administrator', 'creator']:
                                        logger.warning(f"   ⚠️ Бот НЕ администратор в канале {channel['name']}, ПРОПУСКАЮ")
                                        continue
                                    else:
                                        logger.info(f"   ✅ Бот администратор в канале {channel['name']}, отправляю")
                                        
                                except Exception as e:
                                    logger.error(f"   ❌ Ошибка проверки прав в канале {channel['name']}: {e}")
                                    continue
                                
                                for name, qty in main_channel_items.items():
                                    if not was_item_sent(int(channel['id']), name, qty, update_id):
                                        msg = self.format_channel_message(name, qty)
                                        await self.message_queue.queue.put((int(channel['id']), msg, 'HTML', None))
                                        mark_item_sent(int(channel['id']), name, qty, update_id)
                                        logger.info(f"   📢 В канал автопостинга {channel['name']}: {name} = {qty}")
                                    else:
                                        logger.info(f"   ⏭️ Предмет {name} = {qty} уже отправлен в канал {channel['name']}")
                            
                            # 3. Отправляем пользователям (личные сообщения)
                            users = get_all_users()
                            logger.info(f"👥 Отправка пользователям: {len(users)}")
                            
                            for user_id in users:
                                settings = self.user_manager.get_user(user_id)
                                if await self.check_our_subscriptions(user_id) and settings.notifications_enabled:
                                    user_items = self.get_user_items_to_send(all_items, settings, user_id, update_id)
                                    
                                    message_parts = []
                                    
                                    if weather_info and weather_type and settings.weather.get(weather_type, ItemSettings()).enabled:
                                        message_parts.append(weather_info)
                                    
                                    if user_items:
                                        items_msg = self.format_pm_message(user_items)
                                        if items_msg:
                                            message_parts.append(items_msg)
                                    
                                    if message_parts:
                                        full_message = "\n\n".join(message_parts)
                                        await self.message_queue.queue.put((user_id, full_message, 'HTML', None))
                                        
                                        for name, qty in user_items:
                                            mark_item_sent_to_user(user_id, name, qty, update_id)
                            
                            self.last_data = new_data
                    
                elif new_data and not self.last_data:
                    self.last_data = new_data
                    logger.info(f"✅ Первые данные получены: {new_data.get('lastGlobalUpdate')}")
                
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(5, UPDATE_INTERVAL - elapsed)
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле: {e}", exc_info=True)
                await asyncio.sleep(UPDATE_INTERVAL)
    
    async def run(self):
        logger.info("Получение данных при запуске...")
        initial_data = self.fetch_api_data(force=True)
        if initial_data:
            self.last_data = initial_data
            logger.info(f"✅ Данные загружены: {initial_data.get('lastGlobalUpdate')}")
        else:
            logger.error("❌ НЕ УДАЛОСЬ ПОЛУЧИТЬ ДАННЫЕ API!")
        
        await self.message_queue.start()
        asyncio.create_task(self.monitor_loop())
        
        await self.application.initialize()
        await self.application.start()
        
        logger.info("🤖 Бот запущен")
        logger.info(f"📡 API: {API_URL}")
        logger.info(f"📱 Основной канал: {MAIN_CHANNEL_ID}")
        logger.info(f"👑 Админ: {ADMIN_ID}")
        
        await self.application.updater.start_polling()
        
        while True:
            await asyncio.sleep(10)

async def main():
    try:
        if not BOT_TOKEN:
            logger.error("❌ Нет BOT_TOKEN")
            return
        
        bot = GardenHorizonsBot(BOT_TOKEN)
        await bot.run()
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        await asyncio.sleep(2)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")