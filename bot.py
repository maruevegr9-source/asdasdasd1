import os
import logging
import asyncio
import random
import sqlite3
import time
import json
import re
import html
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict
from asyncio import Semaphore

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, InputMediaPhoto, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TimedOut, Forbidden, NetworkError

# Загружаем переменные окружения
load_dotenv()

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.WARNING,  # Только важные ошибки
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger('telegram').setLevel(logging.ERROR)
logging.getLogger('httpx').setLevel(logging.ERROR)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_CHANNEL_ID = os.getenv("CHANNEL_ID", "-1002808898833")
DEFAULT_REQUIRED_CHANNEL_LINK = "https://t.me/GardenHorizonsStocks"

# Данные для Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_CHANNELS = {
    'seeds': int(os.getenv("DISCORD_SEEDS_CHANNEL", "1474799488689377463")),
    'gear': int(os.getenv("DISCORD_GEAR_CHANNEL", "1474799504401236090")),
    'weather': int(os.getenv("DISCORD_WEATHER_CHANNEL", "1474799519706255510"))
}

API_URL = os.getenv("API_URL", "https://stock.gardenhorizonswiki.com/stock.json")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "10"))
ADMIN_ID = 8025951500

# Оптимизации
MAX_CONCURRENT_REQUESTS = 5
SUBSCRIPTION_CACHE_TTL = 300
BLACKLIST_CLEANUP_INTERVAL = 3600

# Часовой пояс Москвы (UTC+3)
MSK_TIMEZONE = timezone(timedelta(hours=3))

# База данных
if os.environ.get('RAILWAY_ENVIRONMENT'):
    DB_PATH = "/data/bot.db"
    try:
        os.makedirs('/data', exist_ok=True)
    except Exception as e:
        DB_PATH = "/tmp/bot.db"
else:
    DB_PATH = "bot.db"

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
    "Mango": "🥭 Манго", "Bamboo": "🎋 Бамбук",
    "Watering Can": "💧 Лейка", "Basic Sprinkler": "💦 Простой разбрызгиватель",
    "Harvest Bell": "🔔 Колокол сбора", "Turbo Sprinkler": "⚡ Турбо-разбрызгиватель",
    "Favorite Tool": "⭐ Любимый инструмент", "Super Sprinkler": "💎 Супер-разбрызгиватель",
    "Trowel": "🪓 Лопатка",
    "fog": "🌫️ Туман", "rain": "🌧️ Дождь", "snow": "❄️ Снег",
    "storm": "⛈️ Шторм", "sandstorm": "🏜️ Песчаная буря", "starfall": "⭐ Звездопад"
}

ALLOWED_CHANNEL_ITEMS = ["Potato", "Cabbage", "Cherry", "Mango", "Bamboo"]
SEEDS_LIST = ["Carrot", "Corn", "Onion", "Strawberry", "Mushroom", "Beetroot", "Tomato", "Apple", "Rose", "Wheat", "Banana", "Plum", "Potato", "Cabbage", "Cherry", "Mango", "Bamboo"]
GEAR_LIST = ["Watering Can", "Basic Sprinkler", "Harvest Bell", "Turbo Sprinkler", "Favorite Tool", "Super Sprinkler", "Trowel"]
WEATHER_LIST = ["fog", "rain", "snow", "storm", "sandstorm", "starfall"]
RARE_ITEMS = ["Super Sprinkler", "Favorite Tool", "starfall", "Mango", "Bamboo"]

def translate(text: str) -> str:
    return TRANSLATIONS.get(text, text)

def is_rare(item_name: str) -> bool:
    return item_name in RARE_ITEMS

def is_allowed_for_main_channel(item_name: str) -> bool:
    return item_name in ALLOWED_CHANNEL_ITEMS

def is_weather_active(weather_data: Dict) -> bool:
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
    try:
        dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        dt_msk = dt_utc.astimezone(MSK_TIMEZONE)
        return dt_msk.strftime("%H:%M")
    except Exception as e:
        return "??:??"

# ========== ФУНКЦИЯ ПРОВЕРКИ НОЧНОГО РЕЖИМА ==========
def is_night_time_msk() -> bool:
    now_msk = datetime.now(MSK_TIMEZONE)
    hour = now_msk.hour
    return 1 <= hour < 8

# ========== БАЗА ДАННЫХ ==========

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-20000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn

def clear_stocks_on_deploy():
    try:
        if os.environ.get('RAILWAY_ENVIRONMENT'):
            conn = get_db()
            cur = conn.cursor()
            stock_tables = ['sent_items', 'user_sent_items', 'weather_notifications', 'mailing_history']
            for table in stock_tables:
                cur.execute(f"DELETE FROM {table};")
            conn.commit()
            conn.close()
    except Exception as e:
        pass

def init_database():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen TEXT,
                notifications_enabled INTEGER DEFAULT 1
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mandatory_channels (
                channel_id TEXT PRIMARY KEY,
                channel_name TEXT
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posting_channels (
                channel_id TEXT PRIMARY KEY,
                name TEXT,
                username TEXT,
                added_at TEXT
            )
        """)
        
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
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_items (
                user_id INTEGER,
                item_name TEXT,
                enabled INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, item_name)
            )
        """)
        
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
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mailing_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                text TEXT,
                sent_at TEXT,
                success_count INTEGER,
                failed_count INTEGER,
                total_count INTEGER
            )
        """)
        
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sent_items_update ON sent_items(update_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_sent_items_update ON user_sent_items(update_id, user_id)")
        
        conn.commit()
        conn.close()
        
        clear_stocks_on_deploy()
        return True
        
    except Exception as e:
        return False

init_database()

# ========== МИГРАЦИЯ БАЗЫ ДАННЫХ ==========
try:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(sent_items)")
    columns = [column[1] for column in cur.fetchall()]
    
    if 'update_id' not in columns:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_items_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                item_name TEXT,
                quantity INTEGER,
                update_id TEXT,
                sent_at TEXT,
                UNIQUE(chat_id, item_name, quantity, update_id)
            )
        """)
        
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sent_items'")
        if cur.fetchone():
            cur.execute("""
                INSERT INTO sent_items_new (id, chat_id, item_name, quantity, sent_at)
                SELECT id, chat_id, item_name, quantity, sent_at FROM sent_items
            """)
            cur.execute("DROP TABLE sent_items")
            cur.execute("ALTER TABLE sent_items_new RENAME TO sent_items")
        else:
            cur.execute("ALTER TABLE sent_items_new RENAME TO sent_items")
        
        conn.commit()
    
    conn.close()
except Exception as e:
    pass

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С БД ==========

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
        pass

def get_user_settings(user_id: int) -> Dict:
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT u.notifications_enabled, ui.item_name, ui.enabled 
            FROM users u
            LEFT JOIN user_items ui ON u.user_id = ui.user_id
            WHERE u.user_id = ?
        """, (user_id,))
        
        rows = cur.fetchall()
        conn.close()
        
        if not rows:
            return {
                'notifications_enabled': True,
                'seeds': {item: True for item in SEEDS_LIST},
                'gear': {item: True for item in GEAR_LIST},
                'weather': {item: True for item in WEATHER_LIST}
            }
        
        notifications_enabled = bool(rows[0][0])
        items = {row[1]: bool(row[2]) for row in rows if row[1]}
        
        return {
            'notifications_enabled': notifications_enabled,
            'seeds': {item: items.get(item, True) for item in SEEDS_LIST},
            'gear': {item: items.get(item, True) for item in GEAR_LIST},
            'weather': {item: items.get(item, True) for item in WEATHER_LIST}
        }
    except Exception as e:
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
        pass

def get_all_users() -> List[int]:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        users = [row[0] for row in cur.fetchall()]
        conn.close()
        return users
    except Exception as e:
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
        return 0

def get_mandatory_channels() -> List[Dict]:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_name FROM mandatory_channels ORDER BY channel_id")
        channels = [{'id': row[0], 'name': row[1]} for row in cur.fetchall()]
        conn.close()
        return channels
    except Exception as e:
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
        pass

def remove_mandatory_channel(channel_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM mandatory_channels WHERE channel_id = ?", (str(channel_id),))
        conn.commit()
        conn.close()
    except Exception as e:
        pass

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
        pass

def remove_posting_channel(channel_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM posting_channels WHERE channel_id = ?", (str(channel_id),))
        conn.commit()
        conn.close()
    except Exception as e:
        pass

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
        pass

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
    except Exception as e:
        pass

def was_weather_notification_sent(weather_type: str, status: str, update_id: str) -> bool:
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
        return False

def mark_weather_notification_sent(weather_type: str, status: str, update_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO weather_notifications (weather_type, status, update_id, sent_at) VALUES (?, ?, ?, ?)",
            (weather_type, status, update_id, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        pass

def was_item_sent_in_this_update(item_name: str, quantity: int, update_id: str) -> bool:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM sent_items WHERE item_name = ? AND quantity = ? AND update_id = ?",
            (item_name, quantity, update_id)
        )
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        return False

def mark_item_sent_for_update(item_name: str, quantity: int, update_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO sent_items (chat_id, item_name, quantity, update_id, sent_at) VALUES (?, ?, ?, ?, ?)",
            (0, item_name, quantity, update_id, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        pass

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
        
        conn.close()
        
        return {
            'users': users_count,
            'op_channels': op_count,
            'posting_channels': post_count
        }
    except Exception as e:
        return {
            'users': 0,
            'op_channels': 0,
            'posting_channels': 0
        }

# ========== ОГРАНИЧИТЕЛЬ ЗАПРОСОВ ==========

class RateLimiter:
    def __init__(self, max_calls_per_second=30):
        self.max_calls = max_calls_per_second
        self.calls = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        async with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < 1.0]
            
            if len(self.calls) >= self.max_calls:
                wait_time = 1.0 - (now - self.calls[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self.calls.pop(0)
            
            self.calls.append(now)

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

# ========== ОПТИМИЗИРОВАННАЯ ОЧЕРЕДЬ СООБЩЕНИЙ ==========

class MessageQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self._tasks = []
        self.application = None
        self.worker_count = 5
        self.sent_count = 0
        self.start_time = time.time()
        self.batch_size = 20
        self.rate_limiter = RateLimiter(max_calls_per_second=30)
    
    async def start(self):
        for i in range(self.worker_count):
            task = asyncio.create_task(self._worker(i))
            self._tasks.append(task)
    
    async def stop(self):
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    async def _worker(self, worker_id: int):
        batch = []
        
        while True:
            try:
                await self.rate_limiter.acquire()
                
                while len(batch) < self.batch_size:
                    try:
                        chat_id, text, parse_mode, photo = self.queue.get_nowait()
                        batch.append((chat_id, text, parse_mode, photo))
                    except asyncio.QueueEmpty:
                        break
                
                if batch:
                    for chat_id, text, parse_mode, photo in batch:
                        try:
                            if photo:
                                await self._send_fast(chat_id, photo, text, parse_mode)
                            else:
                                await self._send_message_fast(chat_id, text, parse_mode)
                            
                            await asyncio.sleep(0.05)
                            
                        except Exception as e:
                            pass
                    
                    self.sent_count += len(batch)
                    batch.clear()
                
                await asyncio.sleep(0.01)
                
            except Exception as e:
                await asyncio.sleep(1)
    
    async def _send_message_fast(self, chat_id: int, text: str, parse_mode: str):
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
        except:
            pass
    
    async def _send_fast(self, chat_id: int, photo: str, caption: str, parse_mode: str):
        try:
            await self.application.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=parse_mode
            )
        except:
            pass

# ========== DISCORD СЛУШАТЕЛЬ ==========

class DiscordListener:
    def __init__(self, telegram_bot_instance):
        self.bot = telegram_bot_instance
        self.headers = {'authorization': DISCORD_TOKEN} if DISCORD_TOKEN else None
        self.last_messages = {}
        self.role_cache = {}
        self.running = True
        self.main_channel_id = int(MAIN_CHANNEL_ID) if MAIN_CHANNEL_ID else None
        self.error_count = 0
        
        try:
            if os.path.exists('last_discord.json'):
                with open('last_discord.json', 'r') as f:
                    self.last_messages = json.load(f)
        except:
            self.last_messages = {}
    
    def save_last(self):
        try:
            with open('last_discord.json', 'w') as f:
                json.dump(self.last_messages, f, indent=2)
        except:
            pass
    
    def get_role_name(self, role_id):
        if not DISCORD_TOKEN or not DISCORD_GUILD_ID:
            return None
            
        if role_id in self.role_cache:
            return self.role_cache[role_id]
        try:
            url = f"https://discord.com/api/v9/guilds/{DISCORD_GUILD_ID}/roles"
            r = requests.get(url, headers=self.headers, timeout=5)
            if r.status_code == 200:
                roles = r.json()
                for role in roles:
                    self.role_cache[role['id']] = role['name']
                    if role['id'] == str(role_id):
                        return role['name']
        except:
            pass
        return None
    
    def extract_quantity(self, msg, role_name):
        full_text = ""
        if msg.get('content'):
            full_text += msg['content']
        if msg.get('embeds'):
            for embed in msg['embeds']:
                if embed.get('description'):
                    full_text += embed['description']
        
        patterns = [
            rf'@?{re.escape(role_name)}\s*\(x(\d+)\)',
            rf'{re.escape(role_name)}\s*x(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        return 1
    
    def parse_message(self, msg, channel_name):
        all_items = []
        rare_items = []
        
        if msg.get('mention_roles'):
            for role_id in msg['mention_roles']:
                role_name = self.get_role_name(role_id)
                if role_name:
                    qty = self.extract_quantity(msg, role_name)
                    all_items.append((role_name, qty))
                    if is_allowed_for_main_channel(role_name):
                        rare_items.append((role_name, qty))
        
        return all_items, rare_items
    
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
    
    def format_pm_message(self, items: List[tuple], weather_info: str = None) -> str:
        message_parts = []
        
        if weather_info:
            message_parts.append(weather_info)
        
        if items:
            msg_items = []
            for name, qty in items:
                translated = translate(name)
                msg_items.append(f"<b>{translated}:</b> {qty} шт.")
            
            if msg_items:
                message_parts.append("🔔 <b>НОВЫЕ ПРЕДМЕТЫ В СТОКЕ</b>\n\n" + "\n".join(msg_items))
        
        return "\n\n".join(message_parts) if message_parts else None
    
    def format_weather_started_message(self, weather_type: str, end_timestamp: int = None) -> str:
        translated = translate(weather_type)
        
        weather_emojis = {
            "fog": "🌫️", "rain": "🌧️", "snow": "❄️", 
            "storm": "⛈️", "sandstorm": "🏜️", "starfall": "⭐"
        }
        emoji = weather_emojis.get(weather_type, "🌤️")
        
        if end_timestamp:
            msk_time = get_msk_time_from_timestamp(end_timestamp)
            return (
                f"{emoji} <b>Актуальная погода:</b>\n"
                f"⛈ <b>{translated}!</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{msk_time} по МСК"
            )
        else:
            return (
                f"{emoji} <b>Актуальная погода:</b>\n"
                f"⛈ <b>{translated}!</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Неизвестное время"
            )
    
    async def send_weather_to_users(self, weather_type: str, end_timestamp: int = None, update_id: str = None):
        weather_msg = self.format_weather_started_message(weather_type, end_timestamp)
        users = get_all_users()
        
        if users and update_id:
            for user_id in users:
                if user_id != ADMIN_ID:
                    settings = self.bot.user_manager.get_user(user_id)
                    if settings.notifications_enabled and settings.weather.get(weather_type, ItemSettings()).enabled:
                        if not was_weather_notification_sent(weather_type, 'started', update_id):
                            await self.bot.message_queue.queue.put((user_id, weather_msg, 'HTML', None))
    
    async def send_to_destinations(self, all_items, rare_items, weather_info=None):
        update_id = str(int(time.time()))
        
        # Множество для отслеживания отправленных в этом апдейте
        sent_in_update = set()
        
        # ===== 1. ОСНОВНОЙ КАНАЛ =====
        if rare_items and self.main_channel_id:
            for item_name, qty in rare_items:
                key = f"{item_name}_{qty}"
                if key not in sent_in_update:
                    if not was_item_sent_in_this_update(item_name, qty, update_id):
                        msg = self.format_channel_message(item_name, qty)
                        await self.bot.message_queue.queue.put((self.main_channel_id, msg, 'HTML', None))
                        mark_item_sent_for_update(item_name, qty, update_id)
                        sent_in_update.add(key)
        
        # ===== 2. АВТОПОСТИНГ =====
        if rare_items and self.bot.posting_channels:
            for channel in self.bot.posting_channels:
                for item_name, qty in rare_items:
                    key = f"{item_name}_{qty}"
                    if key not in sent_in_update:
                        if not was_item_sent_in_this_update(item_name, qty, update_id):
                            msg = self.format_channel_message(item_name, qty)
                            await self.bot.message_queue.queue.put((int(channel['id']), msg, 'HTML', None))
                            sent_in_update.add(key)
        
        # ===== 3. ПОГОДА =====
        if weather_info:
            weather_key = f"weather_{weather_info}"
            if weather_key not in sent_in_update:
                for channel in self.bot.posting_channels:
                    await self.bot.message_queue.queue.put((int(channel['id']), weather_info, 'HTML', None))
                
                weather_type = None
                for w in WEATHER_LIST:
                    if translate(w) in weather_info:
                        weather_type = w
                        break
                
                if weather_type:
                    await self.send_weather_to_users(weather_type, None, update_id)
                
                sent_in_update.add(weather_key)
        
        # ===== 4. ЛИЧКА =====
        if all_items:
            users = get_all_users()
            if users:
                for user_id in users:
                    if user_id == ADMIN_ID:
                        continue
                    
                    settings = self.bot.user_manager.get_user(user_id)
                    if not settings.notifications_enabled:
                        continue
                    
                    user_items = []
                    
                    for name, qty in all_items:
                        key = f"{name}_{qty}"
                        
                        if key in sent_in_update:
                            continue
                        
                        enabled = False
                        if name in SEEDS_LIST:
                            seed_settings = settings.seeds.get(name)
                            enabled = seed_settings and seed_settings.enabled
                        elif name in GEAR_LIST:
                            gear_settings = settings.gear.get(name)
                            enabled = gear_settings and gear_settings.enabled
                        elif name in WEATHER_LIST:
                            weather_settings = settings.weather.get(name)
                            enabled = weather_settings and weather_settings.enabled
                        
                        if enabled and not was_item_sent_to_user(user_id, name, qty, update_id):
                            user_items.append((name, qty))
                    
                    if user_items:
                        pm_message = self.format_pm_message(user_items, weather_info if weather_info and weather_key not in sent_in_update else None)
                        if pm_message:
                            await self.bot.message_queue.queue.put((user_id, pm_message, 'HTML', None))
                            for name, qty in user_items:
                                mark_item_sent_to_user(user_id, name, qty, update_id)
                                sent_in_update.add(f"{name}_{qty}")
    
    async def run(self):
        if not DISCORD_TOKEN or not DISCORD_GUILD_ID:
            return
        
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        ]
        
        while self.running:
            try:
                if is_night_time_msk():
                    night_sleep = random.randint(600, 900)
                    await asyncio.sleep(night_sleep)
                    self.error_count = 0
                    continue
                
                for channel_name, channel_id in DISCORD_CHANNELS.items():
                    headers = {
                        'authorization': DISCORD_TOKEN,
                        'User-Agent': random.choice(user_agents)
                    }
                    
                    try:
                        url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=5"
                        r = requests.get(url, headers=headers, timeout=10)
                        
                        if r.status_code == 200:
                            self.error_count = 0
                            messages = r.json()
                            
                            for msg in messages:
                                msg_id = msg['id']
                                author = msg['author']['username']
                                
                                msg_key = f"{channel_id}_{msg_id}"
                                
                                if msg_key in self.last_messages:
                                    continue
                                
                                if author == 'Dawnbot':
                                    all_items, rare_items = self.parse_message(msg, channel_name)
                                    
                                    weather_info = None
                                    if channel_name == 'weather' and all_items:
                                        for name, qty in all_items:
                                            if name in WEATHER_LIST:
                                                end_timestamp = None
                                                if msg.get('content'):
                                                    time_match = re.search(r'(\d{1,2}):(\d{2})', msg['content'])
                                                    if time_match:
                                                        current_time = int(time.time())
                                                        hours, minutes = map(int, time_match.groups())
                                                        end_timestamp = current_time + (hours * 3600 + minutes * 60)
                                                
                                                weather_info = self.format_weather_started_message(name, end_timestamp)
                                                
                                                if not was_weather_notification_sent(name, 'started', str(msg_id)):
                                                    for channel in self.bot.posting_channels:
                                                        await self.bot.message_queue.queue.put(
                                                            (int(channel['id']), weather_info, 'HTML', None)
                                                        )
                                                    await self.send_weather_to_users(name, end_timestamp, str(msg_id))
                                                    mark_weather_notification_sent(name, 'started', str(msg_id))
                                    
                                    if all_items or rare_items:
                                        await self.send_to_destinations(all_items, rare_items, weather_info)
                                    
                                    self.last_messages[msg_key] = True
                                    self.save_last()
                                
                                await asyncio.sleep(random.uniform(1, 3))
                            
                        elif r.status_code == 429:
                            retry_after = r.json().get('retry_after', 60)
                            await asyncio.sleep(retry_after + random.uniform(5, 15))
                            
                        else:
                            self.error_count += 1
                            error_sleep = min(30 * (2 ** self.error_count), 300)
                            await asyncio.sleep(error_sleep)
                            continue
                            
                    except Exception as e:
                        self.error_count += 1
                        error_sleep = min(30 * (2 ** self.error_count), 300)
                        await asyncio.sleep(error_sleep)
                        continue
                    
                    await asyncio.sleep(random.uniform(5, 10))
                
                await asyncio.sleep(random.uniform(15, 25))
                
            except Exception as e:
                self.error_count += 1
                error_sleep = min(30 * (2 ** self.error_count), 300)
                await asyncio.sleep(error_sleep)
    
    def stop(self):
        self.running = False

# ========== MIDDLEWARE ==========

class SubscriptionMiddleware:
    def __init__(self, bot_instance):
        self.bot = bot_instance
    
    async def __call__(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not user:
            return True
        
        if user.id == ADMIN_ID:
            return True
        
        if update.callback_query and update.callback_query.data == "check_our_sub":
            return True
        
        if update.message and update.message.text and update.message.text.startswith('/start'):
            return True
        
        channels = self.bot.reload_channels()
        
        if not channels:
            return True
        
        is_subscribed = await self.bot.check_our_subscriptions(user.id)
        
        if not is_subscribed:
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
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                elif update.callback_query:
                    try:
                        await update.callback_query.edit_message_media(
                            media=InputMediaPhoto(media=IMAGE_MAIN, caption=f"<b>{text}</b>", parse_mode='HTML'),
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    except:
                        await update.callback_query.message.reply_photo(
                            photo=IMAGE_MAIN,
                            caption=f"<b>{text}</b>",
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
            except Exception as e:
                pass
            
            return False
        
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
        
        # Оптимизации
        self.subscription_cache = {}
        self.blacklist = set()
        self.cache_ttl = SUBSCRIPTION_CACHE_TTL
        self.request_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        self.message_queue = MessageQueue()
        self.message_queue.application = self.application
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        })
        
        self.discord_listener = DiscordListener(self)
        
        self.setup_conversation_handlers()
        self.setup_handlers()
        
        self.subscription_middleware = SubscriptionMiddleware(self)
        self.original_process_update = self.application.process_update
        self.application.process_update = self.process_update_with_middleware
        
        asyncio.create_task(self._cleanup_cache_loop())
    
    async def process_update_with_middleware(self, update: Update):
        try:
            context = ContextTypes.DEFAULT_TYPE(self.application)
            should_continue = await self.subscription_middleware(update, context)
            
            if should_continue:
                await self.original_process_update(update)
                
        except Exception as e:
            pass
    
    def reload_channels(self):
        self.mandatory_channels = get_mandatory_channels()
        self.posting_channels = get_posting_channels()
        return self.mandatory_channels
    
    async def get_chat_id_safe(self, identifier):
        try:
            chat = await self.application.bot.get_chat(identifier)
            return chat.id
        except Exception as e:
            if isinstance(identifier, str) and identifier.lstrip('-').isdigit():
                return int(identifier)
            return identifier
    
    async def check_our_subscriptions(self, user_id: int) -> bool:
        if user_id == ADMIN_ID:
            return True
        
        if user_id in self.blacklist:
            return False
        
        current_time = time.time()
        if user_id in self.subscription_cache:
            is_subscribed, timestamp = self.subscription_cache[user_id]
            if not is_subscribed:
                return False
            if current_time - timestamp < self.cache_ttl:
                return True
        
        channels = self.mandatory_channels
        
        if not channels:
            self.subscription_cache[user_id] = (True, current_time)
            return True
        
        async with self.request_semaphore:
            for channel in channels:
                try:
                    chat_id = await self.get_chat_id_safe(channel['id'])
                    
                    if chat_id is None:
                        self.subscription_cache[user_id] = (False, current_time)
                        self.blacklist.add(user_id)
                        return False
                    
                    member = await self.application.bot.get_chat_member(chat_id, user_id)
                    status = member.status
                    
                    if status not in ["member", "administrator", "creator", "restricted"]:
                        self.subscription_cache[user_id] = (False, current_time)
                        self.blacklist.add(user_id)
                        return False
                        
                except Exception as e:
                    self.subscription_cache[user_id] = (False, current_time)
                    self.blacklist.add(user_id)
                    return False
            
            self.subscription_cache[user_id] = (True, current_time)
            if user_id in self.blacklist:
                self.blacklist.remove(user_id)
            return True
    
    async def verify_subscription_now(self, user_id: int) -> bool:
        channels = self.mandatory_channels
        
        if not channels:
            return True
        
        async with self.request_semaphore:
            for channel in channels:
                try:
                    chat_id = await self.get_chat_id_safe(channel['id'])
                    member = await self.application.bot.get_chat_member(chat_id, user_id)
                    
                    if member.status not in ["member", "administrator", "creator"]:
                        self.subscription_cache[user_id] = (False, time.time())
                        self.blacklist.add(user_id)
                        return False
                        
                except Exception:
                    self.subscription_cache[user_id] = (False, time.time())
                    self.blacklist.add(user_id)
                    return False
            
            self.subscription_cache[user_id] = (True, time.time())
            if user_id in self.blacklist:
                self.blacklist.remove(user_id)
            return True
    
    async def _cleanup_cache_loop(self):
        while True:
            await asyncio.sleep(300)
            
            try:
                current_time = time.time()
                
                to_delete = []
                for user_id, (_, timestamp) in self.subscription_cache.items():
                    if current_time - timestamp > self.cache_ttl * 2:
                        to_delete.append(user_id)
                
                for user_id in to_delete:
                    del self.subscription_cache[user_id]
                
                if int(current_time) % 3600 < 300:
                    self.blacklist.clear()
                    
            except Exception as e:
                pass
    
    def setup_conversation_handlers(self):
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
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("stock", self.cmd_stock))
        self.application.add_handler(CommandHandler("notifications_on", self.cmd_notifications_on))
        self.application.add_handler(CommandHandler("notifications_off", self.cmd_notifications_off))
        self.application.add_handler(CommandHandler("menu", self.cmd_menu))
        self.application.add_handler(CommandHandler("admin", self.cmd_admin))
        
        self.application.add_handler(self.add_op_conv)
        self.application.add_handler(self.add_post_conv)
        self.application.add_handler(self.mailing_conv)
        
        self.application.add_handler(CallbackQueryHandler(self.handle_user_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
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
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
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
    
    async def show_admin_panel(self, update: Update):
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
    
    async def show_op_menu(self, query):
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
        channel_id = update.message.text.strip()
        context.user_data['op_channel_id'] = channel_id
        await update.message.reply_text("✏️ <b>Теперь отправьте название канала</b> (для отображения):", parse_mode='HTML')
        return ADD_OP_CHANNEL_NAME
    
    async def add_op_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        channel_id = query.data.replace('op_del_', '')
        remove_mandatory_channel(channel_id)
        self.reload_channels()
        await query.answer("✅ Канал удален из ОП!")
        await self.show_op_remove(query)
    
    async def show_op_list(self, query):
        self.reload_channels()
        
        if not self.mandatory_channels:
            text = "📭 <b>Нет каналов в обязательной подписке</b>"
        else:
            text = "<b>📋 КАНАЛЫ ОБЯЗАТЕЛЬНОЙ ПОДПИСКИ (ОП)</b>\n\n"
            for ch in self.mandatory_channels:
                text += f"• <b>{ch['name']}</b> (ID: <code>{ch['id']}</code>)\n"
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_op")]]
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_post_menu(self, query):
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
        channel_id = update.message.text.strip()
        context.user_data['post_channel_id'] = channel_id
        await update.message.reply_text("✏️ <b>Теперь отправьте название канала</b> (для отображения):", parse_mode='HTML')
        return ADD_POST_CHANNEL_NAME
    
    async def add_post_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        channel_id = query.data.replace('post_del_', '')
        remove_posting_channel(channel_id)
        self.reload_channels()
        await query.answer("✅ Канал удален из автопостинга!")
        await self.show_post_remove(query)
    
    async def show_post_list(self, query):
        self.reload_channels()
        
        if not self.posting_channels:
            text = "📭 <b>Нет каналов для автопостинга</b>"
        else:
            text = "<b>📢 КАНАЛЫ ДЛЯ АВТОПОСТИНГА</b>\n\n"
            for ch in self.posting_channels:
                text += f"• <b>{ch['name']}</b> (ID: <code>{ch['id']}</code>)\n"
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_post")]]
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def mailing_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        text = update.message.text
        
        context.user_data['mailing_text'] = text
        context.user_data['mailing_text_message_id'] = update.message.message_id
        
        keyboard = [
            [InlineKeyboardButton("✅ ОТПРАВИТЬ", callback_data="mailing_yes"),
             InlineKeyboardButton("❌ ОТМЕНИТЬ", callback_data="mailing_no")]
        ]
        
        await update.message.reply_text(
            f"<b>📧 Подтверждение рассылки</b>\n\n{text}\n\n<b>Отправить это сообщение всем пользователям?</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return ConversationHandler.END
    
    async def mailing_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        
        if user_id != ADMIN_ID:
            await query.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return
        
        if query.data == "mailing_no":
            await query.message.edit_text("❌ <b>Рассылка отменена</b>", parse_mode='HTML')
            await self.show_admin_panel_callback(query)
            return
        
        text = context.user_data.get('mailing_text', '')
        if not text:
            await query.message.edit_text("❌ <b>Ошибка: текст не найден</b>", parse_mode='HTML')
            await self.show_admin_panel_callback(query)
            return
        
        try:
            await query.message.delete()
        except:
            pass
        
        status_msg = await context.bot.send_message(
            chat_id=user_id,
            text="📧 <b>Начинаю рассылку...</b>",
            parse_mode='HTML'
        )
        
        success = 0
        failed = 0
        users = get_all_users()
        
        for uid in users:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"<b>📢 РАССЫЛКА</b>\n\n{text}",
                    parse_mode='HTML'
                )
                success += 1
                await asyncio.sleep(0.01)
            except:
                failed += 1
        
        try:
            await status_msg.delete()
        except:
            pass
        
        report = (
            f"<b>📊 ОТЧЕТ О РАССЫЛКЕ</b>\n\n"
            f"✅ <b>Успешно доставлено:</b> {success}\n"
            f"❌ <b>Ошибок отправки:</b> {failed}\n"
            f"👥 <b>Всего пользователей:</b> {len(users)}"
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text=report,
            parse_mode='HTML'
        )
        
        if 'mailing_text' in context.user_data:
            del context.user_data['mailing_text']
        
        await self.show_admin_panel_callback(query)
    
    async def show_stats(self, query):
        users_count = get_users_count()
        
        text = (
            "<b>📊 СТАТИСТИКА БОТА</b>\n\n"
            f"👥 <b>Всего пользователей:</b> {users_count}\n"
            f"🔐 <b>Каналов ОП:</b> {len(self.mandatory_channels)}\n"
            f"📢 <b>Каналов для автопостинга:</b> {len(self.posting_channels)}"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_panel")]]
        await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_main_menu(self, update: Update):
        user = update.effective_user
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
            await update.message.reply_text("🔄 <b>Обновляю меню...</b>", reply_markup=reply_markup_remove, parse_mode='HTML')
            await update.message.reply_photo(photo=IMAGE_MAIN, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        elif update.callback_query:
            await self.show_main_menu_callback(update.callback_query)
    
    async def show_main_menu_callback(self, query):
        user = query.from_user
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
        parts = query.data.split("_")
        if len(parts) >= 3:
            seed_name = "_".join(parts[2:])
            enabled = not settings.seeds[seed_name].enabled
            settings.seeds[seed_name].enabled = enabled
            update_user_setting(settings.user_id, f"seed_{seed_name}", enabled)
            await self.show_seeds_settings(query, settings)
    
    async def handle_gear_callback(self, query, settings: UserSettings):
        parts = query.data.split("_")
        if len(parts) >= 3:
            gear_name = "_".join(parts[2:])
            enabled = not settings.gear[gear_name].enabled
            settings.gear[gear_name].enabled = enabled
            update_user_setting(settings.user_id, f"gear_{gear_name}", enabled)
            await self.show_gear_settings(query, settings)
    
    async def handle_weather_callback(self, query, settings: UserSettings):
        parts = query.data.split("_")
        if len(parts) >= 3:
            weather_name = "_".join(parts[2:])
            enabled = not settings.weather[weather_name].enabled
            settings.weather[weather_name].enabled = enabled
            update_user_setting(settings.user_id, f"weather_{weather_name}", enabled)
            await self.show_weather_settings(query, settings)
    
    async def handle_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = update.effective_user
        
        await query.answer()
        
        settings = self.user_manager.get_user(user.id)
        
        if query.data == "menu_stock":
            await self.show_stock_callback(query)
            return
        
        if query.data == "menu_main":
            await self.show_main_menu_callback(query)
            return
        
        if query.data == "menu_settings":
            await self.show_main_settings_callback(query, settings)
            return
        
        if query.data == "notifications_on":
            settings.notifications_enabled = True
            update_user_setting(user.id, 'notifications_enabled', True)
            await query.message.reply_html("<b>✅ Уведомления включены!</b>")
            return
        
        if query.data == "notifications_off":
            settings.notifications_enabled = False
            update_user_setting(user.id, 'notifications_enabled', False)
            await query.message.reply_html("<b>❌ Уведомления выключены</b>")
            return
        
        if query.data == "settings_seeds":
            await self.show_seeds_settings(query, settings)
            return
        
        if query.data == "settings_gear":
            await self.show_gear_settings(query, settings)
            return
        
        if query.data == "settings_weather":
            await self.show_weather_settings(query, settings)
            return
        
        if query.data.startswith("seed_toggle_"):
            await self.handle_seed_callback(query, settings)
            return
        
        if query.data.startswith("gear_toggle_"):
            await self.handle_gear_callback(query, settings)
            return
        
        if query.data.startswith("weather_toggle_"):
            await self.handle_weather_callback(query, settings)
            return
        
        if query.data == "check_our_sub":
            is_subscribed = await self.verify_subscription_now(user.id)
            
            if is_subscribed:
                add_user_to_db(user.id, user.username or user.first_name)
                
                try:
                    await query.message.delete()
                except:
                    pass
                
                await query.message.reply_text("✅ <b>Подписка подтверждена!</b>", parse_mode='HTML')
                
                # Сразу показываем главное меню
                await self.show_main_menu_callback(query)
            else:
                await query.answer("❌ Подписка не подтверждена!", show_alert=True)
            return
        
        if not settings.is_admin:
            return
        
        if query.data == "admin_panel":
            await self.show_admin_panel_callback(query)
            return
        
        if query.data == "admin_op":
            await self.show_op_menu(query)
            return
        
        if query.data == "op_remove":
            await self.show_op_remove(query)
            return
        
        if query.data == "op_list":
            await self.show_op_list(query)
            return
        
        if query.data.startswith("op_del_"):
            await self.delete_op_channel(query)
            return
        
        if query.data == "admin_post":
            await self.show_post_menu(query)
            return
        
        if query.data == "post_remove":
            await self.show_post_remove(query)
            return
        
        if query.data == "post_list":
            await self.show_post_list(query)
            return
        
        if query.data.startswith("post_del_"):
            await self.delete_post_channel(query)
            return
        
        if query.data == "admin_stats":
            await self.show_stats(query)
            return
        
        if query.data in ["mailing_yes", "mailing_no"]:
            await self.mailing_confirm(update, context)
            return
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return
        user = update.effective_user
        if not user:
            return
        text = update.message.text
        
        if any(key in context.user_data for key in ['op_channel_id', 'post_channel_id', 'mailing_text']):
            return
        
        if text == "🏠 ГЛАВНОЕ МЕНЮ":
            reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await update.message.reply_text("🔄 <b>Возвращаюсь в главное меню...</b>", reply_markup=reply_markup, parse_mode='HTML')
            await self.show_main_menu(update)
    
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
                    parts.append(
                        f"🌤 <b>Актуальная погода:</b>\n"
                        f"⛈ <b>{translate(wtype)}!</b>\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"{msk_time} по МСК"
                    )
                elif wtype in TRANSLATIONS:
                    parts.append(
                        f"🌤 <b>Актуальная погода:</b>\n"
                        f"⛈ <b>{translate(wtype)}!</b>\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"Неизвестное время"
                    )
        
        return "\n\n".join(parts) if parts else None
    
    async def run(self):
        initial_data = self.fetch_api_data(force=True)
        if initial_data:
            self.last_data = initial_data
        
        await self.message_queue.start()
        asyncio.create_task(self.discord_listener.run())
        
        await self.application.initialize()
        await self.application.start()
        
        await self.application.updater.start_polling()
        
        while True:
            await asyncio.sleep(10)

async def main():
    try:
        if not BOT_TOKEN:
            return
        
        bot = GardenHorizonsBot(BOT_TOKEN)
        await bot.run()
        
    except Exception as e:
        await asyncio.sleep(2)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        pass