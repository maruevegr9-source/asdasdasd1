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
from telegram.error import RetryAfter, TimedOut

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
        logger.debug("🌤️ Нет данных о погоде")
        return False
    
    if not weather_data.get("active"):
        logger.debug("🌤️ Погода не активна по флагу active")
        return False
    
    end_timestamp = weather_data.get("endTimestamp")
    if end_timestamp:
        current_time = int(time.time())
        if current_time >= end_timestamp:
            logger.info(f"🌤️ Погода закончилась по таймеру: current={current_time}, end={end_timestamp}")
            return False
        else:
            time_left = end_timestamp - current_time
            logger.debug(f"🌤️ Погода активна, осталось {time_left} сек")
            return True
    
    logger.debug(f"🌤️ Погода активна (нет timestamp)")
    return True

def get_msk_time_from_timestamp(timestamp: int) -> str:
    """Конвертирует timestamp в московское время"""
    try:
        # Создаем datetime из timestamp (UTC)
        dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        # Конвертируем в московское время (UTC+3)
        dt_msk = dt_utc.astimezone(MSK_TIMEZONE)
        # Возвращаем в формате ЧЧ:ММ:СС
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
        
        # Таблица для истории отправленных уведомлений
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                item_name TEXT,
                quantity INTEGER,
                sent_at TEXT,
                UNIQUE(chat_id, item_name, quantity)
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
        logger.info(f"✅ Пользователь {user_id} добавлен/обновлен в БД")
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
        logger.info(f"📥 Загружено {len(channels)} каналов ОП из БД")
        for ch in channels:
            logger.info(f"  - {ch['name']} ({ch['id']})")
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
        logger.info(f"✅ Канал ОП добавлен в БД: {channel_name} ({channel_id})")
    except Exception as e:
        logger.error(f"❌ Ошибка добавления канала ОП в БД: {e}")

def remove_mandatory_channel(channel_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM mandatory_channels WHERE channel_id = ?", (str(channel_id),))
        conn.commit()
        conn.close()
        logger.info(f"✅ Канал ОП удален из БД: {channel_id}")
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
        logger.info(f"📥 Загружено {len(channels)} каналов автопостинга из БД")
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
        logger.info(f"✅ Канал автопостинга добавлен в БД: {name} ({channel_id})")
    except Exception as e:
        logger.error(f"❌ Ошибка добавления канала автопостинга в БД: {e}")

def remove_posting_channel(channel_id: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM posting_channels WHERE channel_id = ?", (str(channel_id),))
        conn.commit()
        conn.close()
        logger.info(f"✅ Канал автопостинга удален из БД: {channel_id}")
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
            "INSERT INTO user_sent_items (user_id, item_name, quantity, sent_at, update_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, item_name, quantity, datetime.now().isoformat(), update_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка отметки отправленного предмета: {e}")

def was_item_sent(chat_id: int, item_name: str, quantity: int) -> bool:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM sent_items WHERE chat_id = ? AND item_name = ? AND quantity = ?",
            (chat_id, item_name, quantity)
        )
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception as e:
        logger.error(f"❌ Ошибка проверки отправленного: {e}")
        return False

def mark_item_sent(chat_id: int, item_name: str, quantity: int):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sent_items (chat_id, item_name, quantity, sent_at) VALUES (?, ?, ?, ?)",
            (chat_id, item_name, quantity, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
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
        
        # Пропускаем, если нет пользователя
        if not user:
            return True
        
        # ВАЖНО: Всегда пропускаем админа
        if user.id == ADMIN_ID:
            logger.info(f"👑 Middleware: админ {user.id} пропущен")
            return True
        
        # ВАЖНО: Всегда пропускаем команду /start
        if update.message and update.message.text and update.message.text.startswith('/start'):
            logger.info(f"🚀 Middleware: команда /start от {user.id} пропущена")
            return True
        
        # ВАЖНО: Всегда пропускаем callback проверки подписки
        if update.callback_query and update.callback_query.data == "check_our_sub":
            logger.info(f"✅ Middleware: callback check_our_sub от {user.id} пропущен")
            return True
        
        # Для всех остальных запросов проверяем подписку
        logger.info(f"🔍 Middleware: проверка подписки для {user.id}")
        
        # Получаем актуальные каналы
        channels = self.bot.reload_channels()
        
        # Если каналов нет - пропускаем
        if not channels:
            logger.info(f"📭 Middleware: нет каналов ОП, пропускаем {user.id}")
            return True
        
        # Проверяем подписку
        is_subscribed = await self.bot.check_our_subscriptions(user.id)
        
        if not is_subscribed:
            logger.info(f"❌ Middleware: пользователь {user.id} не подписан, показываем сообщение")
            
            # Формируем сообщение о необходимости подписки
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
            
            # Отправляем сообщение
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
            
            return False  # Блокируем дальнейшую обработку
        
        logger.info(f"✅ Middleware: пользователь {user.id} подписан, пропускаем")
        return True  # Продолжаем обработку

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
        
        # Переопределяем метод process_update
        self.application.process_update = self.process_update_with_middleware
        
        logger.info(f"🤖 Бот инициализирован. Админ ID: {ADMIN_ID}")
        logger.info(f"📢 Каналов ОП: {len(self.mandatory_channels)}")
        logger.info(f"📢 Каналов автопостинга: {len(self.posting_channels)}")
    
    async def process_update_with_middleware(self, update: Update):
        """Обертка для process_update с middleware"""
        context = ContextTypes.DEFAULT_TYPE(self.application)
        
        # Применяем middleware
        should_continue = await self.subscription_middleware(update, context)
        
        if should_continue:
            # Если middleware пропустил, вызываем оригинальный process_update
            await self.application._process_update(update)
    
    def reload_channels(self):
        """Перезагружает каналы из БД"""
        old_op_count = len(self.mandatory_channels)
        old_post_count = len(self.posting_channels)
        
        self.mandatory_channels = get_mandatory_channels()
        self.posting_channels = get_posting_channels()
        
        logger.info(f"🔄 Каналы перезагружены. ОП: {old_op_count} -> {len(self.mandatory_channels)}, Автопостинг: {old_post_count} -> {len(self.posting_channels)}")
        
        # Выводим список каналов для отладки
        if self.mandatory_channels:
            logger.info(f"📋 Список каналов ОП:")
            for ch in self.mandatory_channels:
                logger.info(f"  - {ch['name']} ({ch['id']})")
        
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
        channels = self.mandatory_channels  # Используем уже загруженные
        
        if not channels:
            logger.info(f"Нет обязательных каналов для пользователя {user_id}")
            return True
        
        logger.info(f"🔍 Проверка ОП для пользователя {user_id} на {len(channels)} каналов")
        
        for channel in channels:
            channel_id_str = channel['id']
            channel_name = channel['name']
            
            logger.info(f"  Канал: {channel_name} ({channel_id_str})")
            
            try:
                chat_id = await self.get_chat_id_safe(channel_id_str)
                
                if chat_id is None:
                    logger.error(f"    ❌ Не удалось получить chat_id для {channel_id_str}")
                    return False
                
                member = await self.application.bot.get_chat_member(chat_id, user_id)
                status = member.status
                logger.info(f"    Статус: {status}")
                
                if status not in ["member", "administrator", "creator", "restricted"]:
                    logger.info(f"    ❌ Не подписан на {channel_name}")
                    return False
                else:
                    logger.info(f"    ✅ Подписан на {channel_name}")
                    
            except Exception as e:
                logger.error(f"    ❌ Ошибка проверки подписки: {e}")
                return False
        
        logger.info(f"✅ Все проверки пройдены для {user_id}")
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
        """Настройка обработчиков"""
        
        # 1. СНАЧАЛА ConversationHandler
        self.application.add_handler(self.add_op_conv)
        self.application.add_handler(self.add_post_conv)
        self.application.add_handler(self.mailing_conv)
        
        # 2. ПОТОМ команды
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("stock", self.cmd_stock))
        self.application.add_handler(CommandHandler("notifications_on", self.cmd_notifications_on))
        self.application.add_handler(CommandHandler("notifications_off", self.cmd_notifications_off))
        self.application.add_handler(CommandHandler("menu", self.cmd_menu))
        self.application.add_handler(CommandHandler("admin", self.cmd_admin))
        
        # 3. ПОТОМ обработчик callback
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # 4. ПОТОМ обработчик сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    # ========== ФУНКЦИИ ОТМЕНЫ ==========
    
    async def cancel_op(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"❌ Отмена добавления канала ОП пользователем {update.effective_user.id}")
        await update.message.reply_text("❌ <b>Добавление канала отменено</b>", parse_mode='HTML')
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def cancel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"❌ Отмена добавления канала автопостинга пользователем {update.effective_user.id}")
        await update.message.reply_text("❌ <b>Добавление канала отменено</b>", parse_mode='HTML')
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def cancel_mailing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"❌ Отмена рассылки пользователем {update.effective_user.id}")
        await update.message.reply_text("❌ <b>Рассылка отменена</b>", parse_mode='HTML')
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    # ========== КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ ==========
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"🚀 Команда /start от пользователя {user.id} (@{user.username})")
        
        # Добавляем пользователя в БД
        self.user_manager.get_user(user.id, user.username or user.first_name)
        
        # Показываем главное меню
        await self.show_main_menu(update)
    
    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"🚀 Команда /menu от пользователя {user.id}")
        
        await self.show_main_menu(update)
    
    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"⚙️ Команда /settings от пользователя {user.id}")
        
        settings = self.user_manager.get_user(user.id)
        await self.show_main_settings(update, settings)
    
    async def cmd_stock(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"📦 Команда /stock от пользователя {user.id}")
        
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
        logger.info(f"🔔 Команда /notifications_on от пользователя {user.id}")
        
        settings = self.user_manager.get_user(user.id)
        settings.notifications_enabled = True
        update_user_setting(user.id, 'notifications_enabled', True)
        await update.message.reply_html("<b>✅ Уведомления успешно включены!</b>")
    
    async def cmd_notifications_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"🔕 Команда /notifications_off от пользователя {user.id}")
        
        settings = self.user_manager.get_user(user.id)
        settings.notifications_enabled = False
        update_user_setting(user.id, 'notifications_enabled', False)
        await update.message.reply_html("<b>❌ Уведомления успешно выключены</b>")
    
    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"👑 Команда /admin от пользователя {user.id}")
        
        settings = self.user_manager.get_user(user.id)
        if not settings.is_admin:
            await update.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return
        
        # ВАЖНО: Перезагружаем каналы перед показом админ-панели
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
        # Перезагружаем каналы перед показом меню
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
        logger.info(f"➕ Начало добавления канала ОП пользователем {user_id}")
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
        logger.info(f"➕ Ввод ID канала ОП пользователем {user_id}: {channel_id}")
        
        context.user_data['op_channel_id'] = channel_id
        await update.message.reply_text("✏️ <b>Теперь отправьте название канала</b> (для отображения):", parse_mode='HTML')
        return ADD_OP_CHANNEL_NAME
    
    async def add_op_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        channel_name = update.message.text.strip()
        channel_id = context.user_data.get('op_channel_id')
        
        logger.info(f"➕ Ввод названия канала ОП пользователем {user_id}: {channel_name} ({channel_id})")
        
        try:
            if channel_id.startswith('@'):
                chat = await self.application.bot.get_chat(channel_id)
            else:
                chat = await self.application.bot.get_chat(int(channel_id))
            
            # Проверяем, является ли бот администратором канала
            bot_member = await self.application.bot.get_chat_member(chat.id, self.application.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                logger.error(f"❌ Бот не является администратором канала {channel_id}")
                await update.message.reply_text(
                    "❌ <b>Бот не является администратором этого канала!</b>\n"
                    "Сделайте бота админом и попробуйте снова.",
                    parse_mode='HTML'
                )
                await self.show_admin_panel(update)
                return ConversationHandler.END
            
            final_id = f"@{chat.username}" if chat.username else str(chat.id)
            add_mandatory_channel(final_id, channel_name)
            
            # ВАЖНО: Перезагружаем каналы сразу после добавления
            self.reload_channels()
            
            logger.info(f"✅ Канал ОП успешно добавлен и загружен: {channel_name} ({channel_id})")
            await update.message.reply_text(
                f"✅ <b>Канал {channel_name} добавлен в обязательную подписку!</b>\n"
                f"📊 Теперь в ОП {len(self.mandatory_channels)} каналов",
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка добавления канала ОП: {e}")
            await update.message.reply_text(f"❌ <b>Ошибка:</b> {e}", parse_mode='HTML')
        
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def show_op_remove(self, query):
        """Показ списка каналов для удаления из ОП"""
        # Перезагружаем каналы перед показом
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
        
        # ВАЖНО: Перезагружаем каналы сразу после удаления
        self.reload_channels()
        
        await query.answer("✅ Канал удален из ОП!")
        await self.show_op_remove(query)
    
    async def show_op_list(self, query):
        """Показ списка каналов ОП"""
        # Перезагружаем каналы перед показом
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
        # Перезагружаем каналы перед показом
        self.reload_channels()
        
        text = (
            "📢 <b>УПРАВЛЕНИЕ АВТОПОСТИНГОМ</b>\n\n"
            "<b>Каналы, в которые бот будет отправлять уведомления</b>\n"
            "(помимо основного канала @GardenHorizonsStocks)\n\n"
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
        logger.info(f"➕ Начало добавления канала автопостинга пользователем {user_id}")
        await query.answer()
        
        if user_id != ADMIN_ID:
            await query.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return ConversationHandler.END
        
        await query.message.reply_text(
            "📢 <b>Добавление канала для автопостинга</b>\n\n"
            "Отправьте <b>ID канала</b> (например: -1001234567890) или <b>username</b> (@channel):",
            parse_mode='HTML'
        )
        return ADD_POST_CHANNEL_ID
    
    async def add_post_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        channel_id = update.message.text.strip()
        logger.info(f"➕ Ввод ID канала автопостинга пользователем {user_id}: {channel_id}")
        
        context.user_data['post_channel_id'] = channel_id
        await update.message.reply_text("✏️ <b>Теперь отправьте название канала</b> (для отображения):", parse_mode='HTML')
        return ADD_POST_CHANNEL_NAME
    
    async def add_post_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        channel_name = update.message.text.strip()
        channel_id = context.user_data.get('post_channel_id')
        
        logger.info(f"➕ Ввод названия канала автопостинга пользователем {user_id}: {channel_name} ({channel_id})")
        
        try:
            if channel_id.startswith('@'):
                chat = await self.application.bot.get_chat(channel_id)
            else:
                chat = await self.application.bot.get_chat(int(channel_id))
            
            # Проверяем, является ли бот администратором канала
            bot_member = await self.application.bot.get_chat_member(chat.id, self.application.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                logger.error(f"❌ Бот не является администратором канала {channel_id}")
                await update.message.reply_text(
                    "❌ <b>Бот не является администратором этого канала!</b>\n"
                    "Сделайте бота админом и попробуйте снова.",
                    parse_mode='HTML'
                )
                await self.show_admin_panel(update)
                return ConversationHandler.END
            
            logger.info(f"✅ Канал найден: {chat.title} (ID: {chat.id})")
            
            add_posting_channel(str(chat.id), channel_name, chat.username)
            
            # ВАЖНО: Перезагружаем каналы сразу после добавления
            self.reload_channels()
            
            logger.info(f"✅ Канал автопостинга успешно добавлен и загружен: {channel_name} ({channel_id})")
            await update.message.reply_text(
                f"✅ <b>Канал {channel_name} добавлен для автопостинга!</b>\n"
                f"📊 Теперь в автопостинге {len(self.posting_channels)} каналов",
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка добавления канала автопостинга: {e}")
            await update.message.reply_text(f"❌ <b>Ошибка:</b> {e}", parse_mode='HTML')
        
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def show_post_remove(self, query):
        """Показ списка каналов для удаления из автопостинга"""
        # Перезагружаем каналы перед показом
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
        
        # ВАЖНО: Перезагружаем каналы сразу после удаления
        self.reload_channels()
        
        await query.answer("✅ Канал удален из автопостинга!")
        await self.show_post_remove(query)
    
    async def show_post_list(self, query):
        """Показ списка каналов автопостинга"""
        # Перезагружаем каналы перед показом
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
        logger.info(f"📧 Начало рассылки пользователем {user_id}")
        await query.answer()
        
        if user_id != ADMIN_ID:
            await query.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return ConversationHandler.END
        
        # Очищаем старые данные
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
        logger.info(f"📧 Ввод текста рассылки пользователем {user_id}, длина: {len(text)}")
        
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
            logger.info(f"❌ Отмена рассылки пользователем {user_id}")
            await query.message.reply_text("❌ <b>Рассылка отменена</b>", parse_mode='HTML')
            await self.show_admin_panel_callback(query)
            return
        
        text = context.user_data.get('mailing_text', '')
        if not text:
            logger.error(f"❌ Текст рассылки не найден для пользователя {user_id}")
            await query.message.reply_text("❌ <b>Ошибка: текст не найден</b>", parse_mode='HTML')
            await self.show_admin_panel_callback(query)
            return
        
        logger.info(f"📧 Подтверждение рассылки пользователем {user_id}")
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
            except Exception as e:
                failed += 1
                logger.error(f"❌ Ошибка отправки пользователю {uid}: {e}")
        
        logger.info(f"📧 Рассылка завершена. Успешно: {success}, Ошибок: {failed}")
        await query.message.reply_text(
            f"<b>📊 ОТЧЕТ О РАССЫЛКЕ</b>\n\n"
            f"✅ <b>Успешно:</b> {success}\n"
            f"❌ <b>Ошибок:</b> {failed}\n"
            f"👥 <b>Всего:</b> {len(users)}",
            parse_mode='HTML'
        )
        
        # Очищаем данные после рассылки
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
        user_id = user.id
        logger.info(f"🌱 Показ главного меню пользователю {user_id}")
        
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
        """Показ главного меню из callback"""
        user = query.from_user
        user_id = user.id
        logger.info(f"🌱 Показ главного меню (callback) пользователю {user_id}")
        
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
        user_id = query.from_user.id
        logger.info(f"📦 Показ текущего стока пользователю {user_id}")
        
        await query.edit_message_media(media=InputMediaPhoto(media=IMAGE_MAIN, caption="<b>🔍 Получаю данные...</b>", parse_mode='HTML'))
        data = self.fetch_api_data(force=True)
        if not data:
            await query.edit_message_media(media=InputMediaPhoto(media=IMAGE_MAIN, caption="<b>❌ Ошибка получения данных</b>", parse_mode='HTML'))
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
        user_id = query.from_user.id
        parts = query.data.split("_")
        if len(parts) >= 3:
            seed_name = "_".join(parts[2:])
            enabled = not settings.seeds[seed_name].enabled
            settings.seeds[seed_name].enabled = enabled
            update_user_setting(settings.user_id, f"seed_{seed_name}", enabled)
            logger.info(f"🌱 Переключение семени {seed_name} для пользователя {user_id}: {'✅' if enabled else '❌'}")
            await self.show_seeds_settings(query, settings)
    
    async def handle_gear_callback(self, query, settings: UserSettings):
        """Обработка настроек снаряжения"""
        user_id = query.from_user.id
        parts = query.data.split("_")
        if len(parts) >= 3:
            gear_name = "_".join(parts[2:])
            enabled = not settings.gear[gear_name].enabled
            settings.gear[gear_name].enabled = enabled
            update_user_setting(settings.user_id, f"gear_{gear_name}", enabled)
            logger.info(f"⚙️ Переключение снаряжения {gear_name} для пользователя {user_id}: {'✅' if enabled else '❌'}")
            await self.show_gear_settings(query, settings)
    
    async def handle_weather_callback(self, query, settings: UserSettings):
        """Обработка настроек погоды"""
        user_id = query.from_user.id
        parts = query.data.split("_")
        if len(parts) >= 3:
            weather_name = "_".join(parts[2:])
            enabled = not settings.weather[weather_name].enabled
            settings.weather[weather_name].enabled = enabled
            update_user_setting(settings.user_id, f"weather_{weather_name}", enabled)
            logger.info(f"🌤️ Переключение погоды {weather_name} для пользователя {user_id}: {'✅' if enabled else '❌'}")
            await self.show_weather_settings(query, settings)
    
    # ========== ОБРАБОТКА СООБЩЕНИЙ ==========
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        text = update.message.text
        
        # Проверяем, не находимся ли мы в диалоге
        if context.user_data.get(ADD_OP_CHANNEL_ID) or context.user_data.get(ADD_POST_CHANNEL_ID) or context.user_data.get(MAILING_TEXT):
            return
        
        if text == "🏠 ГЛАВНОЕ МЕНЮ":
            logger.info(f"🏠 Возврат в главное меню пользователем {user.id}")
            reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await update.message.reply_text("🔄 <b>Возвращаюсь в главное меню...</b>", reply_markup=reply_markup, parse_mode='HTML')
            await self.show_main_menu(update)
    
    # ========== ГЛАВНЫЙ ОБРАБОТЧИК CALLBACK ==========
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главный обработчик callback запросов"""
        query = update.callback_query
        user = update.effective_user
        await query.answer()
        
        logger.info(f"📨 Callback от пользователя {user.id}: {query.data}")
        
        settings = self.user_manager.get_user(user.id)
        
        # Пропускаем callback для ConversationHandler
        if query.data in ["add_op", "add_post", "mailing"]:
            logger.info(f"⏩ Callback {query.data} передан ConversationHandler")
            return
        
        # Обработка проверки подписки
        if query.data == "check_our_sub":
            logger.info(f"✅ Нажата кнопка 'Я подписался' пользователем {user.id}")
            
            is_subscribed = await self.check_our_subscriptions(user.id)
            
            if is_subscribed:
                logger.info(f"✅ Пользователь {user.id} подписался на все каналы")
                add_user_to_db(user.id, user.username or user.first_name)
                
                # Удаляем сообщение с кнопками
                try:
                    await query.message.delete()
                except:
                    pass
                
                # Показываем подтверждение
                await query.message.answer("✅ <b>Подписка подтверждена!</b>", parse_mode='HTML')
                
                # Показываем главное меню
                await self.show_main_menu_callback(query)
            else:
                logger.info(f"❌ Пользователь {user.id} не подписался на все каналы")
                await query.answer("❌ Подписка не подтверждена!", show_alert=True)
            return
        
        # Админ-панель
        if query.data == "admin_panel":
            if not settings.is_admin:
                await query.answer("❌ У вас нет прав!", show_alert=True)
                return
            await self.show_admin_panel_callback(query)
            return
        
        # Меню ОП
        if query.data == "admin_op":
            if not settings.is_admin:
                return
            await self.show_op_menu(query)
            return
        
        # Удаление из ОП
        if query.data == "op_remove":
            if not settings.is_admin:
                return
            await self.show_op_remove(query)
            return
        
        # Список ОП
        if query.data == "op_list":
            if not settings.is_admin:
                return
            await self.show_op_list(query)
            return
        
        # Удаление конкретного канала из ОП
        if query.data.startswith("op_del_"):
            if not settings.is_admin:
                return
            await self.delete_op_channel(query)
            return
        
        # Меню автопостинга
        if query.data == "admin_post":
            if not settings.is_admin:
                return
            await self.show_post_menu(query)
            return
        
        # Удаление из автопостинга
        if query.data == "post_remove":
            if not settings.is_admin:
                return
            await self.show_post_remove(query)
            return
        
        # Список автопостинга
        if query.data == "post_list":
            if not settings.is_admin:
                return
            await self.show_post_list(query)
            return
        
        # Удаление конкретного канала из автопостинга
        if query.data.startswith("post_del_"):
            if not settings.is_admin:
                return
            await self.delete_post_channel(query)
            return
        
        # Статистика
        if query.data == "admin_stats":
            if not settings.is_admin:
                return
            await self.show_stats(query)
            return
        
        # Подтверждение рассылки
        if query.data in ["mailing_yes", "mailing_no"]:
            if not settings.is_admin:
                return
            await self.mailing_confirm(update, context)
            return
        
        # Главное меню
        if query.data == "menu_main":
            await self.show_main_menu_callback(query)
            return
        
        # Меню настроек
        if query.data == "menu_settings":
            await self.show_main_settings_callback(query, settings)
            return
        
        # Сток
        if query.data == "menu_stock":
            await self.show_stock_callback(query)
            return
        
        # Уведомления
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
        
        # Настройки категорий
        if query.data == "settings_seeds":
            await self.show_seeds_settings(query, settings)
            return
        
        if query.data.startswith("seed_toggle_"):
            await self.handle_seed_callback(query, settings)
            return
        
        if query.data == "settings_gear":
            await self.show_gear_settings(query, settings)
            return
        
        if query.data.startswith("gear_toggle_"):
            await self.handle_gear_callback(query, settings)
            return
        
        if query.data == "settings_weather":
            await self.show_weather_settings(query, settings)
            return
        
        if query.data.startswith("weather_toggle_"):
            await self.handle_weather_callback(query, settings)
            return
    
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
            
            logger.info(f"🔍 Запрос к API: {url}")
            response = self.session.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"⚠️ API вернул статус {response.status_code}")
                return None
            
            data = response.json()
            logger.info(f"✅ Ответ API получен")
            
            if data.get("ok") and "data" in data:
                last_update = data["data"].get("lastGlobalUpdate", "no date")
                logger.info(f"📅 Последнее обновление: {last_update}")
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
        
        # Проверяем, активна ли погода с учетом времени окончания
        if "weather" in data:
            weather_data = data["weather"]
            if is_weather_active(weather_data):
                wtype = weather_data["type"]
                end_timestamp = weather_data.get("endTimestamp")
                
                if end_timestamp and wtype in TRANSLATIONS:
                    # Конвертируем в московское время
                    msk_time = get_msk_time_from_timestamp(end_timestamp)
                    parts.append(f"<b>{translate(wtype)} АКТИВНА</b> до {msk_time} (МСК)")
                elif wtype in TRANSLATIONS:
                    parts.append(f"<b>{translate(wtype)} АКТИВНА</b>")
            else:
                logger.debug(f"🌤️ Погода не активна, не добавляем в сообщение")
        
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
        
        if "gear" in data:
            for item in data["gear"]:
                name = item["name"]
                if name in TRANSLATIONS and item["quantity"] > 0:
                    all_items[name] = item["quantity"]
        
        # Добавляем погоду ТОЛЬКО если она активна
        if "weather" in data:
            weather_data = data["weather"]
            if is_weather_active(weather_data):
                wtype = weather_data.get("type")
                if wtype and wtype in TRANSLATIONS:
                    all_items[wtype] = 1
                    logger.info(f"🌤️ Добавляем активную погоду: {wtype}")
        
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
            logger.info(f"🌤️ Погода началась: {new_type}")
            return 'started', new_type, new_end
        
        # Погода закончилась
        if old_active and not new_active:
            logger.info(f"🌤️ Погода закончилась: {old_type}")
            return 'ended', old_type, None
        
        # Погода изменилась на другой тип
        if old_active and new_active and old_type != new_type:
            logger.info(f"🌤️ Погода изменилась: {old_type} -> {new_type}")
            # Сначала отправляем что старая закончилась
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
                            
                            logger.info(f"🌤️ Изменение погоды: {weather_status} {wtype}")
                            mark_weather_notification_sent(wtype, weather_status, update_id)
                    
                    # Проверяем изменения в стоке
                    if new_data.get("lastGlobalUpdate") != self.last_data.get("lastGlobalUpdate") or weather_changed:
                        if new_data.get("lastGlobalUpdate") != self.last_data.get("lastGlobalUpdate"):
                            logger.info(f"✅ Обнаружены изменения в API!")
                        
                        all_items = self.get_all_current_items(new_data)
                        
                        if all_items or weather_info:
                            logger.info(f"✅ Отправка обновлений: сток={bool(all_items)}, погода={weather_info is not None}")
                            
                            update_id = new_data.get('lastGlobalUpdate', datetime.now().isoformat())
                            
                            # Формируем сообщение для каналов (только сток)
                            main_channel_items = {}
                            for name, qty in all_items.items():
                                if is_allowed_for_main_channel(name):
                                    main_channel_items[name] = qty
                            
                            # 1. Отправляем в ОСНОВНОЙ канал
                            if MAIN_CHANNEL_ID and main_channel_items:
                                for name, qty in main_channel_items.items():
                                    if not was_item_sent(int(MAIN_CHANNEL_ID), name, qty):
                                        msg = self.format_channel_message(name, qty)
                                        await self.message_queue.queue.put((int(MAIN_CHANNEL_ID), msg, 'HTML', None))
                                        mark_item_sent(int(MAIN_CHANNEL_ID), name, qty)
                                        logger.info(f"📢 В основной канал: {name} = {qty}")
                            
                            # 2. Отправляем в ДОПОЛНИТЕЛЬНЫЕ каналы (автопостинг)
                            for channel in self.posting_channels:
                                for name, qty in main_channel_items.items():
                                    if not was_item_sent(int(channel['id']), name, qty):
                                        msg = self.format_channel_message(name, qty)
                                        await self.message_queue.queue.put((int(channel['id']), msg, 'HTML', None))
                                        mark_item_sent(int(channel['id']), name, qty)
                                        logger.info(f"📢 В канал автопостинга {channel['name']}: {name} = {qty}")
                            
                            # 3. Отправляем пользователям (личные сообщения)
                            users = get_all_users()
                            
                            for user_id in users:
                                settings = self.user_manager.get_user(user_id)
                                if await self.check_our_subscriptions(user_id) and settings.notifications_enabled:
                                    # Собираем предметы для пользователя
                                    user_items = self.get_user_items_to_send(all_items, settings, user_id, update_id)
                                    
                                    # Формируем единое сообщение
                                    message_parts = []
                                    
                                    # Добавляем информацию о погоде если есть
                                    if weather_info and weather_type and settings.weather.get(weather_type, ItemSettings()).enabled:
                                        message_parts.append(weather_info)
                                    
                                    # Добавляем предметы если есть
                                    if user_items:
                                        items_msg = self.format_pm_message(user_items)
                                        if items_msg:
                                            message_parts.append(items_msg)
                                    
                                    # Отправляем одним сообщением
                                    if message_parts:
                                        full_message = "\n\n".join(message_parts)
                                        await self.message_queue.queue.put((user_id, full_message, 'HTML', None))
                                        
                                        # Отмечаем отправленные предметы
                                        for name, qty in user_items:
                                            mark_item_sent_to_user(user_id, name, qty, update_id)
                                        
                                        logger.info(f"👤 Пользователю {user_id} отправлено: {len(user_items)} предметов, погода={bool(weather_info)}")
                            
                            self.last_data = new_data
                    
                elif new_data and not self.last_data:
                    self.last_data = new_data
                    logger.info(f"✅ Первые данные получены: {new_data.get('lastGlobalUpdate')}")
                
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(5, UPDATE_INTERVAL - elapsed)
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле: {e}")
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
            await asyncio.sleep(3600)

async def main():
    if not BOT_TOKEN:
        logger.error("❌ Нет BOT_TOKEN")
        return
    
    bot = GardenHorizonsBot(BOT_TOKEN)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())