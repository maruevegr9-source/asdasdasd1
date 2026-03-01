import os
import logging
import asyncio
import random
import sqlite3
import time
import json
import re
import hashlib
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
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

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
MAX_WORKERS = 10
BATCH_SIZE = 20
RATE_LIMIT = 30  # сообщений в секунду

# Часовой пояс Москвы (UTC+3)
MSK_TIMEZONE = timezone(timedelta(hours=3))

# База данных
if os.environ.get('RAILWAY_ENVIRONMENT'):
    DB_PATH = "/data/bot.db"
    logger.info(f"✅ Работаем на Railway, БД в /data/bot.db")
    try:
        os.makedirs('/data', exist_ok=True)
    except Exception as e:
        logger.error(f"❌ Ошибка создания папки /data: {e}")
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

# Состояния для ConversationHandler (исправляем warning)
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
    return True

def get_msk_time_from_timestamp(timestamp: int) -> str:
    try:
        dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        dt_msk = dt_utc.astimezone(MSK_TIMEZONE)
        return dt_msk.strftime("%H:%M:%S")
    except Exception as e:
        logger.error(f"❌ Ошибка конвертации времени: {e}")
        return "??:??:??"

def generate_event_id(item_name: str, quantity: int, source: str, timestamp: int = None) -> str:
    """Генерирует уникальный ID события для дедупликации"""
    if timestamp is None:
        timestamp = int(time.time())
    unique_str = f"{item_name}_{quantity}_{source}_{timestamp}"
    return hashlib.md5(unique_str.encode()).hexdigest()[:16]

# ========== БАЗА ДАННЫХ (ИСПРАВЛЕННАЯ) ==========

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-20000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Инициализация БД с правильной структурой"""
    try:
        conn = get_db()
        cur = conn.cursor()
        logger.info(f"✅ Подключение к БД успешно: {DB_PATH}")
        
        # Пользователи
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen TEXT,
                last_activity TEXT,
                notifications_enabled INTEGER DEFAULT 1,
                is_blocked INTEGER DEFAULT 0,
                block_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Подписки (нормализованная таблица)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER,
                category TEXT CHECK(category IN ('seeds', 'gear', 'weather')),
                item_name TEXT,
                enabled INTEGER DEFAULT 1,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, category, item_name),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # Отправленные события (дедупликация)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_events (
                event_id TEXT PRIMARY KEY,
                item_name TEXT,
                quantity INTEGER,
                source TEXT,
                channel_type TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Логи отправки пользователям
        cur.execute("""
            CREATE TABLE IF NOT EXISTS delivery_log (
                user_id INTEGER,
                event_id TEXT,
                status TEXT CHECK(status IN ('sent', 'blocked', 'failed', 'skipped', 'unsubscribed')),
                reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, event_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (event_id) REFERENCES sent_events(event_id) ON DELETE CASCADE
            )
        """)
        
        # Каналы обязательной подписки
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mandatory_channels (
                channel_id TEXT PRIMARY KEY,
                channel_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Каналы автопостинга
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posting_channels (
                channel_id TEXT PRIMARY KEY,
                name TEXT,
                username TEXT,
                added_at TEXT
            )
        """)
        
        # Индексы для скорости
        cur.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_lookup ON subscriptions(user_id, category, enabled)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_delivery_log_user ON delivery_log(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_delivery_log_event ON delivery_log(event_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sent_events_created ON sent_events(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_blocked ON users(is_blocked)")
        
        conn.commit()
        
        # Миграция старых данных, если есть
        migrate_old_data(conn)
        
        conn.close()
        logger.info("✅ База данных инициализирована успешно")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

def migrate_old_data(conn):
    """Миграция данных из старой схемы"""
    try:
        cur = conn.cursor()
        
        # Проверяем, есть ли старая таблица user_items
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_items'")
        if cur.fetchone():
            logger.info("🔄 Обнаружена старая таблица user_items, начинаем миграцию...")
            
            # Переносим подписки
            cur.execute("""
                INSERT OR IGNORE INTO subscriptions (user_id, category, item_name, enabled)
                SELECT 
                    user_id,
                    CASE 
                        WHEN item_name IN ('fog','rain','snow','storm','sandstorm','starfall') THEN 'weather'
                        WHEN item_name IN ('Watering Can','Basic Sprinkler','Harvest Bell','Turbo Sprinkler','Favorite Tool','Super Sprinkler','Trowel') THEN 'gear'
                        ELSE 'seeds'
                    END as category,
                    item_name,
                    enabled
                FROM user_items
            """)
            
            logger.info("✅ Миграция подписок завершена")
            
    except Exception as e:
        logger.error(f"❌ Ошибка миграции: {e}")

init_database()

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С БД (ИСПРАВЛЕННЫЕ) ==========

def add_user_to_db(user_id: int, username: str = ""):
    """Добавление пользователя с инициализацией всех подписок"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        now = datetime.now().isoformat()
        
        # Добавляем/обновляем пользователя
        cur.execute("""
            INSERT INTO users (user_id, username, first_seen, last_activity, notifications_enabled)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                last_activity = excluded.last_activity
        """, (user_id, username, now, now))
        
        # Проверяем, есть ли уже подписки
        cur.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ?", (user_id,))
        if cur.fetchone()[0] == 0:
            # Добавляем все подписки по умолчанию
            subscriptions = []
            for item in SEEDS_LIST:
                subscriptions.append((user_id, 'seeds', item, 1))
            for item in GEAR_LIST:
                subscriptions.append((user_id, 'gear', item, 1))
            for item in WEATHER_LIST:
                subscriptions.append((user_id, 'weather', item, 1))
            
            cur.executemany("""
                INSERT INTO subscriptions (user_id, category, item_name, enabled)
                VALUES (?, ?, ?, ?)
            """, subscriptions)
        
        conn.commit()
        conn.close()
        logger.debug(f"✅ Пользователь {user_id} добавлен/обновлен в БД")
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления пользователя {user_id}: {e}")

def get_user_subscriptions(user_id: int) -> Dict[str, Set[str]]:
    """Получает активные подписки пользователя"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT category, item_name 
            FROM subscriptions 
            WHERE user_id = ? AND enabled = 1
        """, (user_id,))
        
        result = {'seeds': set(), 'gear': set(), 'weather': set()}
        for row in cur.fetchall():
            result[row['category']].add(row['item_name'])
        
        conn.close()
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения подписок {user_id}: {e}")
        return {'seeds': set(SEEDS_LIST), 'gear': set(GEAR_LIST), 'weather': set(WEATHER_LIST)}

def check_user_notifications_enabled(user_id: int) -> bool:
    """Проверяет, включены ли уведомления у пользователя"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT notifications_enabled, is_blocked FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return True
        return bool(row['notifications_enabled']) and not bool(row['is_blocked'])
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки уведомлений {user_id}: {e}")
        return True

def mark_user_blocked(user_id: int, reason: str = "blocked_bot"):
    """Отмечает пользователя как заблокировавшего бота"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE users 
            SET is_blocked = 1, block_reason = ?, last_activity = ?
            WHERE user_id = ?
        """, (reason, datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()
        logger.info(f"🚫 Пользователь {user_id} отмечен как заблокировавший бота")
    except Exception as e:
        logger.error(f"❌ Ошибка отметки блокировки {user_id}: {e}")

def update_user_setting(user_id: int, setting: str, value: Any):
    """Обновление настроек пользователя"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        if setting == 'notifications_enabled':
            cur.execute("""
                UPDATE users 
                SET notifications_enabled = ?, last_activity = ?
                WHERE user_id = ?
            """, (1 if value else 0, datetime.now().isoformat(), user_id))
            
        elif setting.startswith(('seed_', 'gear_', 'weather_')):
            parts = setting.split('_', 1)
            category = parts[0]  # seed, gear, weather
            item_name = parts[1]
            
            # Определяем правильную категорию для БД
            if category == 'seed':
                db_category = 'seeds'
            elif category == 'gear':
                db_category = 'gear'
            else:  # weather
                db_category = 'weather'
            
            cur.execute("""
                UPDATE subscriptions 
                SET enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND category = ? AND item_name = ?
            """, (1 if value else 0, user_id, db_category, item_name))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления настройки {setting} для {user_id}: {e}")

def get_all_active_users() -> List[int]:
    """Получает список всех активных пользователей (не заблокировавших бота)"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id FROM users 
            WHERE is_blocked = 0
        """)
        users = [row['user_id'] for row in cur.fetchall()]
        conn.close()
        logger.debug(f"📊 Активных пользователей: {len(users)}")
        return users
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка пользователей: {e}")
        return []

def get_users_count() -> int:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 0")
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logger.error(f"❌ Ошибка получения количества пользователей: {e}")
        return 0

def is_event_sent(event_id: str) -> bool:
    """Проверяет, было ли событие уже отправлено"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sent_events WHERE event_id = ?", (event_id,))
        exists = cur.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        logger.error(f"❌ Ошибка проверки события {event_id}: {e}")
        return False

def mark_event_sent(event_id: str, item_name: str, quantity: int, source: str, channel_type: str = None):
    """Отмечает событие как отправленное"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO sent_events (event_id, item_name, quantity, source, channel_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_id, item_name, quantity, source, channel_type, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка отметки события {event_id}: {e}")

def log_delivery(user_id: int, event_id: str, status: str, reason: str = None):
    """Логирует доставку сообщения пользователю"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO delivery_log (user_id, event_id, status, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, event_id, status, reason, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка логирования доставки: {e}")

def get_mandatory_channels() -> List[Dict]:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_name FROM mandatory_channels ORDER BY created_at")
        channels = [{'id': row['channel_id'], 'name': row['channel_name']} for row in cur.fetchall()]
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
            "INSERT OR REPLACE INTO mandatory_channels (channel_id, channel_name, created_at) VALUES (?, ?, ?)",
            (str(channel_id), channel_name, datetime.now().isoformat())
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

def get_posting_channels() -> List[Dict]:
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, name, username FROM posting_channels ORDER BY added_at")
        channels = [
            {'id': row['channel_id'], 'name': row['name'], 'username': row['username']}
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

def get_stats() -> Dict:
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 0")
        users_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
        blocked_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM mandatory_channels")
        op_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM posting_channels")
        post_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM sent_events")
        events_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM delivery_log WHERE status = 'sent'")
        sent_count = cur.fetchone()[0]
        
        conn.close()
        
        return {
            'users': users_count,
            'blocked': blocked_count,
            'op_channels': op_count,
            'posting_channels': post_count,
            'events': events_count,
            'deliveries': sent_count
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        return {
            'users': 0, 'blocked': 0, 'op_channels': 0,
            'posting_channels': 0, 'events': 0, 'deliveries': 0
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

# ========== ОПТИМИЗИРОВАННАЯ РАССЫЛКА ==========

class DeliveryManager:
    def __init__(self, bot):
        self.bot = bot
        self.queue = asyncio.Queue()
        self.workers = []
        self.rate_limiter = RateLimiter(RATE_LIMIT)
        self.stats = {
            'sent': 0,
            'blocked': 0,
            'failed': 0,
            'unsubscribed': 0,
            'skipped': 0
        }
        self.start_time = time.time()
    
    async def start(self):
        """Запуск воркеров"""
        for i in range(MAX_WORKERS):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
        logger.info(f"🚀 Запущено {MAX_WORKERS} воркеров доставки")
    
    async def stop(self):
        """Остановка воркеров"""
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
    
    async def _worker(self, worker_id: int):
        """Воркер для отправки сообщений"""
        batch = []
        
        while True:
            try:
                # Ждем rate limit
                await self.rate_limiter.acquire()
                
                # Собираем батч
                while len(batch) < BATCH_SIZE:
                    try:
                        task = self.queue.get_nowait()
                        batch.append(task)
                    except asyncio.QueueEmpty:
                        break
                
                if batch:
                    # Отправляем батч
                    tasks = [self._send_single(task) for task in batch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Обрабатываем результаты
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            logger.error(f"❌ Ошибка в батче: {result}")
                    
                    batch.clear()
                
                await asyncio.sleep(0.01)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Ошибка в воркере {worker_id}: {e}")
                await asyncio.sleep(1)
    
    async def _send_single(self, task):
        """Отправка одного сообщения"""
        user_id, message_data, event_id = task
        
        try:
            # Проверяем подписки и настройки
            if not check_user_notifications_enabled(user_id):
                log_delivery(user_id, event_id, 'skipped', 'notifications_disabled')
                self.stats['skipped'] += 1
                return
            
            # Отправляем
            if message_data.get('photo'):
                await self.bot.application.bot.send_photo(
                    chat_id=user_id,
                    photo=message_data['photo'],
                    caption=message_data['text'],
                    parse_mode='HTML'
                )
            else:
                await self.bot.application.bot.send_message(
                    chat_id=user_id,
                    text=message_data['text'],
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
            
            log_delivery(user_id, event_id, 'sent')
            self.stats['sent'] += 1
            
            # Логируем прогресс
            if self.stats['sent'] % 100 == 0:
                elapsed = time.time() - self.start_time
                speed = self.stats['sent'] / elapsed if elapsed > 0 else 0
                logger.info(f"📨 Доставлено: {self.stats['sent']}, скорость: {speed:.1f}/сек")
            
        except Forbidden:
            # Пользователь заблокировал бота
            mark_user_blocked(user_id)
            log_delivery(user_id, event_id, 'blocked', 'user_blocked_bot')
            self.stats['blocked'] += 1
            
        except RetryAfter as e:
            # Flood wait
            logger.warning(f"⏳ Flood wait {e.retry_after}с для {user_id}")
            await asyncio.sleep(e.retry_after)
            # Возвращаем в очередь
            await self.queue.put(task)
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки {user_id}: {e}")
            log_delivery(user_id, event_id, 'failed', str(e)[:100])
            self.stats['failed'] += 1
    
    async def broadcast(self, user_ids: List[int], message_data: Dict, event_id: str):
        """Массовая рассылка сообщения"""
        for user_id in user_ids:
            await self.queue.put((user_id, message_data, event_id))
        
        logger.info(f"📦 Поставлено в очередь: {len(user_ids)} сообщений (event: {event_id})")
    
    def get_stats(self):
        """Получение статистики доставки"""
        elapsed = time.time() - self.start_time
        return {
            **self.stats,
            'elapsed': elapsed,
            'queue_size': self.queue.qsize(),
            'speed': self.stats['sent'] / elapsed if elapsed > 0 else 0
        }

# ========== DISCORD СЛУШАТЕЛЬ (ИСПРАВЛЕННЫЙ) ==========

class DiscordListener:
    def __init__(self, telegram_bot_instance):
        self.bot = telegram_bot_instance
        self.headers = {'authorization': DISCORD_TOKEN} if DISCORD_TOKEN else None
        self.last_messages = set()
        self.role_cache = {}
        self.running = True
        self.main_channel_id = int(MAIN_CHANNEL_ID) if MAIN_CHANNEL_ID else None
        self.first_run = True
        self.processed_count = 0
        self.last_weather_state = None  # Для отслеживания изменений погоды
        
        self.load_last_messages()
    
    def load_last_messages(self):
        try:
            if os.path.exists('last_discord.json'):
                with open('last_discord.json', 'r') as f:
                    data = json.load(f)
                    self.last_messages = set(data.get('processed', []))
                logger.info(f"📂 Загружено {len(self.last_messages)} записей из last_discord.json")
            else:
                self.last_messages = set()
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки last_discord.json: {e}")
            self.last_messages = set()
    
    def save_last(self):
        try:
            to_save = list(self.last_messages)[-1000:] if len(self.last_messages) > 1000 else list(self.last_messages)
            with open('last_discord.json', 'w') as f:
                json.dump({'processed': to_save}, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения last_discord.json: {e}")
    
    def parse_message(self, msg, channel_name):
        """Парсит сообщение и возвращает предметы с количеством"""
        all_items = []
        rare_items = []
        weather_info = None
        
        full_text = ""
        
        if msg.get('content'):
            full_text += msg['content'] + "\n"
        
        if msg.get('embeds'):
            for embed in msg['embeds']:
                if embed.get('title'):
                    full_text += embed['title'] + "\n"
                if embed.get('description'):
                    full_text += embed['description'] + "\n"
                if embed.get('fields'):
                    for field in embed['fields']:
                        if field.get('name'):
                            full_text += field['name'] + "\n"
                        if field.get('value'):
                            full_text += field['value'] + "\n"
        
        # Ищем предметы в формате @Item (xN) или Item (xN)
        pattern = r'@?(\w+(?:\s+\w+)?)\s*\(x(\d+)\)'
        matches = re.findall(pattern, full_text)
        
        for match in matches:
            item_name = match[0].strip()
            quantity = int(match[1])
            
            if item_name in SEEDS_LIST:
                all_items.append(('seeds', item_name, quantity))
                if is_allowed_for_main_channel(item_name):
                    rare_items.append(('seeds', item_name, quantity))
            elif item_name in GEAR_LIST:
                all_items.append(('gear', item_name, quantity))
                if is_allowed_for_main_channel(item_name):
                    rare_items.append(('gear', item_name, quantity))
            elif item_name in WEATHER_LIST:
                all_items.append(('weather', item_name, quantity))
                if is_allowed_for_main_channel(item_name):
                    rare_items.append(('weather', item_name, quantity))
        
        # Парсим погоду отдельно
        if channel_name == 'weather':
            for weather in WEATHER_LIST:
                if weather in full_text.lower():
                    end_timestamp = None
                    time_match = re.search(r'until (\d{1,2}:\d{2})', full_text, re.IGNORECASE)
                    if time_match:
                        # Парсим время окончания
                        pass
                    
                    weather_info = self.format_weather_message(weather, end_timestamp)
                    break
        
        return all_items, rare_items, weather_info
    
    def format_channel_message(self, item_name: str, quantity: int) -> str:
        """Форматирование сообщения для канала"""
        translated = translate(item_name)
        return (
            f"✨ <b>{translated}</b>\n"
            f"📦 <b>Количество:</b> {quantity} шт.\n"
            f"━━━━━━━━━━━━━━\n"
            f"<a href='{DEFAULT_REQUIRED_CHANNEL_LINK}'>📢 Наш канал</a> | <a href='{BOT_LINK}'>🤖 Авто-сток</a> | <a href='{CHAT_LINK}'>💬 Наш чат</a>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👀 Включи уведомления в канале!"
        )
    
    def format_user_message(self, items: List[tuple], weather_info: str = None, channel_name: str = None) -> Optional[str]:
        """Форматирование сообщения для пользователя"""
        message_parts = []
        
        if weather_info:
            message_parts.append(weather_info)
        
        if items:
            category_name = {
                'seeds': '🌱 СЕМЕНА',
                'gear': '⚙️ СНАРЯЖЕНИЕ',
                'weather': '🌤️ ПОГОДА'
            }.get(channel_name, channel_name.upper() if channel_name else 'ПРЕДМЕТЫ')
            
            items_text = []
            for _, name, qty in items:
                translated = translate(name)
                items_text.append(f"  • {translated}: {qty} шт.")
            
            if items_text:
                message_parts.append(
                    f"🔔 <b>НОВЫЕ ПРЕДМЕТЫ В СТОКЕ</b>\n"
                    f"<b>{category_name}:</b>\n" + "\n".join(items_text)
                )
        
        return "\n\n".join(message_parts) if message_parts else None
    
    def format_weather_message(self, weather_type: str, end_timestamp: int = None) -> str:
        """Форматирование сообщения о погоде (исправленный формат)"""
        translated = translate(weather_type)
        if end_timestamp:
            try:
                msk_time = get_msk_time_from_timestamp(end_timestamp)
                return (
                    f"<b>🌤 Активна погода:</b>\n"
                    f"{translated}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"⏰ До {msk_time} (МСК)"
                )
            except:
                pass
        
        return (
            f"<b>🌤 Активна погода:</b>\n"
            f"{translated}"
        )
    
    async def send_to_destinations(self, all_items, rare_items, weather_info=None, channel_name=None):
        """Отправка уведомлений с проверкой подписок и дедупликацией"""
        
        if not all_items and not rare_items and not weather_info:
            return
        
        # Генерируем event_id на основе данных
        timestamp = int(time.time())
        events = []
        
        # Создаем события для каждого уникального предмета
        for category, name, qty in all_items:
            event_id = generate_event_id(name, qty, f"discord_{channel_name}", timestamp)
            events.append((event_id, category, name, qty))
        
        # Проверяем дубликаты
        new_events = []
        for event_id, category, name, qty in events:
            if not is_event_sent(event_id):
                new_events.append((event_id, category, name, qty))
                mark_event_sent(event_id, name, qty, f"discord_{channel_name}", channel_name)
        
        if not new_events and not weather_info:
            logger.info(f"⏭️ Нет новых событий для рассылки (все уже отправлены)")
            return
        
        logger.info(f"📦 Новые события: {len(new_events)} предметов")
        
        # Отправка в основной канал (редкие предметы)
        if rare_items and self.main_channel_id:
            for _, name, qty in rare_items:
                event_id = generate_event_id(name, qty, "main_channel", timestamp)
                if not is_event_sent(event_id):
                    msg = self.format_channel_message(name, qty)
                    await self.bot.application.bot.send_message(
                        chat_id=self.main_channel_id,
                        text=msg,
                        parse_mode='HTML'
                    )
                    mark_event_sent(event_id, name, qty, "main_channel")
                    logger.info(f"📤 Редкий предмет в основной канал: {name} x{qty}")
        
        # Отправка в каналы автопостинга (редкие предметы)
        if rare_items:
            for channel in self.bot.posting_channels:
                try:
                    for _, name, qty in rare_items:
                        event_id = generate_event_id(name, qty, f"posting_{channel['id']}", timestamp)
                        if not is_event_sent(event_id):
                            msg = self.format_channel_message(name, qty)
                            await self.bot.application.bot.send_message(
                                chat_id=int(channel['id']),
                                text=msg,
                                parse_mode='HTML'
                            )
                            mark_event_sent(event_id, name, qty, f"posting_{channel['id']}")
                            logger.info(f"📤 Редкий предмет в канал {channel['name']}: {name} x{qty}")
                except Exception as e:
                    logger.error(f"Ошибка отправки в канал {channel['name']}: {e}")
        
        # Получаем всех активных пользователей
        all_users = get_all_active_users()
        if not all_users:
            logger.warning("⚠️ Нет активных пользователей для рассылки")
            return
        
        # Для каждого пользователя проверяем подписки
        users_to_notify = []
        stats = {'checked': 0, 'subscribed': 0, 'unsubscribed': 0, 'notifications_off': 0}
        
        for user_id in all_users:
            stats['checked'] += 1
            
            # Проверяем, включены ли уведомления
            if not check_user_notifications_enabled(user_id):
                stats['notifications_off'] += 1
                continue
            
            # Получаем подписки пользователя
            subscriptions = get_user_subscriptions(user_id)
            
            # Проверяем, есть ли у пользователя подписки на эти предметы
            has_subscription = False
            user_items = []
            
            for event_id, category, name, qty in new_events:
                if name in subscriptions.get(category, set()):
                    has_subscription = True
                    user_items.append((category, name, qty, event_id))
            
            if has_subscription or weather_info:
                users_to_notify.append((user_id, user_items))
                stats['subscribed'] += 1
            else:
                stats['unsubscribed'] += 1
        
        logger.info(f"📊 Фильтрация пользователей: всего={stats['checked']}, "
                   f"подписаны={stats['subscribed']}, "
                   f"уведомления выкл={stats['notifications_off']}, "
                   f"не подписаны={stats['unsubscribed']}")
        
        # Формируем и отправляем сообщения
        if users_to_notify:
            message_tasks = []
            
            for user_id, user_items in users_to_notify:
                # Формируем персонализированное сообщение
                items_for_user = [(c, n, q) for c, n, q, _ in user_items]
                user_message = self.format_user_message(items_for_user, weather_info, channel_name)
                
                if user_message:
                    # Используем первый event_id для логирования
                    event_id = user_items[0][3] if user_items else generate_event_id("weather", 0, channel_name, timestamp)
                    
                    message_data = {
                        'text': user_message,
                        'photo': None
                    }
                    
                    message_tasks.append((user_id, message_data, event_id))
            
            if message_tasks:
                # Отправляем через DeliveryManager
                for task in message_tasks:
                    await self.bot.delivery_manager.queue.put(task)
                
                logger.info(f"📦 Поставлено в очередь: {len(message_tasks)} персонализированных сообщений")
    
    async def run(self):
        """Основной цикл слушателя Discord"""
        if not DISCORD_TOKEN or not DISCORD_GUILD_ID:
            logger.warning("⚠️ Discord слушатель отключён")
            return
        
        logger.info("🔌 Discord слушатель запущен")
        
        while self.running:
            try:
                for channel_name, channel_id in DISCORD_CHANNELS.items():
                    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=5"
                    
                    r = requests.get(url, headers=self.headers, timeout=5)
                    
                    if r.status_code == 200:
                        messages = r.json()
                        
                        for msg in messages:
                            msg_id = msg['id']
                            author = msg['author']['username']
                            
                            msg_key = f"{channel_id}_{msg_id}"
                            
                            if self.first_run:
                                self.last_messages.add(msg_key)
                                continue
                            
                            if msg_key in self.last_messages:
                                continue
                            
                            if author == 'Dawnbot':
                                all_items, rare_items, weather_info = self.parse_message(msg, channel_name)
                                
                                if all_items or rare_items or weather_info:
                                    await self.send_to_destinations(all_items, rare_items, weather_info, channel_name)
                                
                                self.last_messages.add(msg_key)
                                self.processed_count += 1
                                
                                if self.processed_count % 10 == 0:
                                    self.save_last()
                        
                        if self.first_run:
                            self.first_run = False
                            self.save_last()
                    
                    await asyncio.sleep(1)
                
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"❌ Discord ошибка: {e}", exc_info=True)
                await asyncio.sleep(30)
    
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
        
        # Пропускаем проверку для определенных callback
        if update.callback_query:
            if update.callback_query.data in ["check_our_sub", "menu_main", "menu_settings"]:
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
                logger.error(f"❌ Middleware: ошибка отправки сообщения: {e}")
            
            return False
        
        return True

# ========== ОСНОВНОЙ КЛАСС БОТА ==========

class GardenHorizonsBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.last_data: Optional[Dict] = None
        self.mandatory_channels = get_mandatory_channels()
        self.posting_channels = get_posting_channels()
        self.mailing_text = None
        
        # Кэш подписок
        self.subscription_cache = {}
        self.cache_ttl = SUBSCRIPTION_CACHE_TTL
        
        # Менеджер доставки
        self.delivery_manager = DeliveryManager(self)
        
        # Discord слушатель
        self.discord_listener = DiscordListener(self)
        
        # Настройка обработчиков
        self.setup_handlers()
        
        # Middleware
        self.subscription_middleware = SubscriptionMiddleware(self)
        self.original_process_update = self.application.process_update
        self.application.process_update = self.process_update_with_middleware
        
        # Сессия для API
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Cache-Control': 'no-cache'
        })
        
        logger.info(f"🤖 Бот инициализирован. Админ ID: {ADMIN_ID}")
    
    async def process_update_with_middleware(self, update: Update):
        try:
            context = ContextTypes.DEFAULT_TYPE(self.application)
            should_continue = await self.subscription_middleware(update, context)
            
            if should_continue:
                await self.original_process_update(update)
                
        except Exception as e:
            logger.error(f"⚡ Ошибка: {e}", exc_info=True)
    
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
        
        current_time = time.time()
        
        # Проверяем кэш
        if user_id in self.subscription_cache:
            is_subscribed, timestamp = self.subscription_cache[user_id]
            if current_time - timestamp < self.cache_ttl:
                return is_subscribed
        
        channels = self.mandatory_channels
        
        if not channels:
            self.subscription_cache[user_id] = (True, current_time)
            return True
        
        # Проверяем подписки
        for channel in channels:
            try:
                chat_id = await self.get_chat_id_safe(channel['id'])
                
                if chat_id is None:
                    self.subscription_cache[user_id] = (False, current_time)
                    return False
                
                member = await self.application.bot.get_chat_member(chat_id, user_id)
                status = member.status
                
                if status not in ["member", "administrator", "creator", "restricted"]:
                    self.subscription_cache[user_id] = (False, current_time)
                    return False
                    
            except Exception as e:
                self.subscription_cache[user_id] = (False, current_time)
                return False
        
        self.subscription_cache[user_id] = (True, current_time)
        return True
    
    async def verify_subscription_now(self, user_id: int) -> bool:
        """Мгновенная проверка подписки (без кэша)"""
        channels = self.mandatory_channels
        
        if not channels:
            return True
        
        for channel in channels:
            try:
                chat_id = await self.get_chat_id_safe(channel['id'])
                member = await self.application.bot.get_chat_member(chat_id, user_id)
                
                if member.status not in ["member", "administrator", "creator"]:
                    return False
                    
            except Exception:
                return False
        
        return True
    
    def setup_handlers(self):
        """Настройка обработчиков команд"""
        
        # Простые команды
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("stock", self.cmd_stock))
        self.application.add_handler(CommandHandler("menu", self.cmd_menu))
        self.application.add_handler(CommandHandler("admin", self.cmd_admin))
        
        # ConversationHandler для добавления каналов (с per_message=False для устранения warning)
        self.application.add_handler(
            ConversationHandler(
                entry_points=[CallbackQueryHandler(self.add_op_start, pattern="^add_op$")],
                states={
                    ADD_OP_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_op_id)],
                    ADD_OP_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_op_name)],
                },
                fallbacks=[CommandHandler("cancel", self.cancel_op)],
                per_message=False,  # Исправляем warning
                name="add_op_conversation"
            )
        )
        
        self.application.add_handler(
            ConversationHandler(
                entry_points=[CallbackQueryHandler(self.add_post_start, pattern="^add_post$")],
                states={
                    ADD_POST_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_post_id)],
                    ADD_POST_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_post_name)],
                },
                fallbacks=[CommandHandler("cancel", self.cancel_post)],
                per_message=False,  # Исправляем warning
                name="add_post_conversation"
            )
        )
        
        self.application.add_handler(
            ConversationHandler(
                entry_points=[CallbackQueryHandler(self.mailing_start, pattern="^mailing$")],
                states={
                    MAILING_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.mailing_get_text)],
                },
                fallbacks=[CommandHandler("cancel", self.cancel_mailing)],
                per_message=False,  # Исправляем warning
                name="mailing_conversation"
            )
        )
        
        # Callback обработчики
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Текстовые сообщения
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    # ========== ОБРАБОТЧИКИ КОМАНД ==========
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        add_user_to_db(user.id, user.username or user.first_name)
        await self.show_main_menu(update)
    
    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.show_main_menu(update)
    
    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await self.show_main_settings(update, user.id)
    
    async def cmd_stock(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html("<b>🔍 Получаю актуальные данные...</b>")
        data = self.fetch_api_data(force=True)
        if not data:
            await update.message.reply_html("<b>❌ Ошибка получения данных</b>")
            return
        
        message = self.format_stock_message(data)
        if message:
            keyboard = [[InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]]
            await update.message.reply_html(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user.id != ADMIN_ID:
            await update.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return
        
        self.reload_channels()
        await self.show_admin_panel(update)
    
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
    
    # ========== АДМИН ФУНКЦИИ ==========
    
    async def show_admin_panel(self, update: Update):
        stats = get_stats()
        
        text = (
            "👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
            f"👥 <b>Активных пользователей:</b> {stats['users']}\n"
            f"🚫 <b>Заблокировали бота:</b> {stats['blocked']}\n"
            f"🔐 <b>Каналов ОП:</b> {stats['op_channels']}\n"
            f"📢 <b>Каналов автопостинга:</b> {stats['posting_channels']}\n"
            f"📊 <b>Событий обработано:</b> {stats['events']}\n"
            f"📨 <b>Доставлено уведомлений:</b> {stats['deliveries']}\n\n"
            "<b>Выберите действие:</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔐 УПРАВЛЕНИЕ ОП", callback_data="admin_op")],
            [InlineKeyboardButton("📢 УПРАВЛЕНИЕ АВТОПОСТИНГОМ", callback_data="admin_post")],
            [InlineKeyboardButton("📧 РАССЫЛКА", callback_data="mailing")],
            [InlineKeyboardButton("📊 СТАТИСТИКА", callback_data="admin_stats")],
            [InlineKeyboardButton("📈 ДОСТАВКА", callback_data="admin_delivery_stats")],
            [InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
        ]
        
        if update.message:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def add_op_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return ConversationHandler.END
        
        await query.message.reply_text(
            "📢 <b>Добавление канала в обязательную подписку</b>\n\n"
            "Отправьте <b>@username</b> канала или ID:",
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
            
            # Проверяем, что бот админ
            bot_member = await self.application.bot.get_chat_member(chat.id, self.application.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "❌ <b>Бот не является администратором этого канала!</b>",
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
    
    async def add_post_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
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
            
            # Проверяем, что бот админ
            bot_member = await self.application.bot.get_chat_member(chat.id, self.application.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "❌ <b>Бот не является администратором этого канала!</b>",
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
    
    async def mailing_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.message.reply_text("❌ <b>У вас нет прав!</b>", parse_mode='HTML')
            return ConversationHandler.END
        
        await query.message.reply_text(
            "📧 <b>Рассылка</b>\n\nВведите текст для рассылки:",
            parse_mode='HTML'
        )
        return MAILING_TEXT
    
    async def mailing_get_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        context.user_data['mailing_text'] = text
        
        keyboard = [
            [InlineKeyboardButton("✅ ОТПРАВИТЬ", callback_data="mailing_confirm"),
             InlineKeyboardButton("❌ ОТМЕНИТЬ", callback_data="mailing_cancel")]
        ]
        
        await update.message.reply_text(
            f"<b>📧 Подтверждение рассылки</b>\n\n{text}\n\n<b>Отправить всем пользователям?</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return ConversationHandler.END
    
    # ========== ПОЛЬЗОВАТЕЛЬСКИЕ ФУНКЦИИ ==========
    
    async def show_main_menu(self, update: Update):
        user = update.effective_user
        is_admin = (user.id == ADMIN_ID)
        
        keyboard = [
            [InlineKeyboardButton("⚙️ АВТО-СТОК", callback_data="menu_settings"),
             InlineKeyboardButton("📦 СТОК", callback_data="menu_stock")],
            [InlineKeyboardButton("🔔 УВЕДОМЛЕНИЯ ВКЛ", callback_data="notifications_on"),
             InlineKeyboardButton("🔕 УВЕДОМЛЕНИЯ ВЫКЛ", callback_data="notifications_off")]
        ]
        
        if is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        if update.message:
            await update.message.reply_photo(
                photo=IMAGE_MAIN,
                caption=MAIN_MENU_TEXT,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif update.callback_query:
            try:
                await update.callback_query.edit_message_media(
                    media=InputMediaPhoto(media=IMAGE_MAIN, caption=MAIN_MENU_TEXT, parse_mode='HTML'),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                await update.callback_query.message.reply_photo(
                    photo=IMAGE_MAIN,
                    caption=MAIN_MENU_TEXT,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
    
    async def show_main_settings(self, update: Update, user_id: int):
        """Показывает главное меню настроек"""
        # Проверяем статус уведомлений
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT notifications_enabled FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        notifications_enabled = bool(row['notifications_enabled']) if row else True
        conn.close()
        
        status = "🔔 ВКЛ" if notifications_enabled else "🔕 ВЫКЛ"
        text = f"<b>⚙️ АВТО-СТОК</b>\n\n<b>Уведомления: {status}</b>\n\nВыберите категорию:"
        
        keyboard = [
            [InlineKeyboardButton("🌱 СЕМЕНА", callback_data="settings_seeds"),
             InlineKeyboardButton("⚙️ СНАРЯЖЕНИЕ", callback_data="settings_gear")],
            [InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather"),
             InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
        ]
        
        if isinstance(update, Update) and update.message:
            await update.message.reply_photo(
                photo=IMAGE_MAIN,
                caption=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif hasattr(update, 'callback_query'):
            try:
                await update.callback_query.edit_message_media(
                    media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                await update.callback_query.message.reply_photo(
                    photo=IMAGE_MAIN,
                    caption=text,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
    
    async def show_seeds_settings(self, query, user_id: int):
        """Показывает настройки семян"""
        subscriptions = get_user_subscriptions(user_id)
        
        text = "<b>🌱 НАСТРОЙКИ СЕМЯН</b>\n\nНажмите на семя для включения/отключения:"
        keyboard, row = [], []
        
        for seed_name in SEEDS_LIST:
            enabled = seed_name in subscriptions['seeds']
            status = "✅" if enabled else "❌"
            button_text = f"{status} {translate(seed_name)}"
            row.append(InlineKeyboardButton(button_text, callback_data=f"toggle_seed_{seed_name}"))
            
            if len(row) == 2:
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")])
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_settings")])
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_SEEDS, caption=text, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            await query.message.reply_photo(
                photo=IMAGE_SEEDS,
                caption=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def show_gear_settings(self, query, user_id: int):
        """Показывает настройки снаряжения"""
        subscriptions = get_user_subscriptions(user_id)
        
        text = "<b>⚙️ НАСТРОЙКИ СНАРЯЖЕНИЯ</b>\n\nНажмите на предмет для включения/отключения:"
        keyboard, row = [], []
        
        for gear_name in GEAR_LIST:
            enabled = gear_name in subscriptions['gear']
            status = "✅" if enabled else "❌"
            button_text = f"{status} {translate(gear_name)}"
            row.append(InlineKeyboardButton(button_text, callback_data=f"toggle_gear_{gear_name}"))
            
            if len(row) == 2:
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")])
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_settings")])
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_GEAR, caption=text, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            await query.message.reply_photo(
                photo=IMAGE_GEAR,
                caption=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def show_weather_settings(self, query, user_id: int):
        """Показывает настройки погоды"""
        subscriptions = get_user_subscriptions(user_id)
        
        text = "<b>🌤️ НАСТРОЙКИ ПОГОДЫ</b>\n\nНажмите на погоду для включения/отключения:"
        keyboard, row = [], []
        
        for weather_name in WEATHER_LIST:
            enabled = weather_name in subscriptions['weather']
            status = "✅" if enabled else "❌"
            button_text = f"{status} {translate(weather_name)}"
            row.append(InlineKeyboardButton(button_text, callback_data=f"toggle_weather_{weather_name}"))
            
            if len(row) == 2:
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")])
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_settings")])
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(media=IMAGE_WEATHER, caption=text, parse_mode='HTML'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            await query.message.reply_photo(
                photo=IMAGE_WEATHER,
                caption=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    # ========== ОБРАБОТЧИК CALLBACK ==========
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user = update.effective_user
        await query.answer()
        
        # ===== ОСНОВНЫЕ МЕНЮ =====
        if query.data == "menu_main":
            await self.show_main_menu(update)
            return
        
        if query.data == "menu_settings":
            await self.show_main_settings(update, user.id)
            return
        
        if query.data == "menu_stock":
            await self.show_stock_callback(query)
            return
        
        # ===== НАСТРОЙКИ УВЕДОМЛЕНИЙ =====
        if query.data == "notifications_on":
            update_user_setting(user.id, 'notifications_enabled', True)
            await query.message.reply_html("<b>✅ Уведомления включены!</b>")
            return
        
        if query.data == "notifications_off":
            update_user_setting(user.id, 'notifications_enabled', False)
            await query.message.reply_html("<b>❌ Уведомления выключены</b>")
            return
        
        # ===== КАТЕГОРИИ НАСТРОЕК =====
        if query.data == "settings_seeds":
            await self.show_seeds_settings(query, user.id)
            return
        
        if query.data == "settings_gear":
            await self.show_gear_settings(query, user.id)
            return
        
        if query.data == "settings_weather":
            await self.show_weather_settings(query, user.id)
            return
        
        # ===== ПЕРЕКЛЮЧЕНИЕ ПОДПИСОК =====
        if query.data.startswith("toggle_"):
            parts = query.data.split("_", 2)
            if len(parts) == 3:
                category = parts[1]  # seed, gear, weather
                item_name = parts[2]
                
                # Получаем текущие подписки
                subscriptions = get_user_subscriptions(user.id)
                
                # Определяем, включен ли сейчас
                if category == 'seed':
                    is_enabled = item_name in subscriptions['seeds']
                    new_value = not is_enabled
                    update_user_setting(user.id, f"seed_{item_name}", new_value)
                elif category == 'gear':
                    is_enabled = item_name in subscriptions['gear']
                    new_value = not is_enabled
                    update_user_setting(user.id, f"gear_{item_name}", new_value)
                elif category == 'weather':
                    is_enabled = item_name in subscriptions['weather']
                    new_value = not is_enabled
                    update_user_setting(user.id, f"weather_{item_name}", new_value)
                
                # Обновляем отображение
                if category == 'seed':
                    await self.show_seeds_settings(query, user.id)
                elif category == 'gear':
                    await self.show_gear_settings(query, user.id)
                elif category == 'weather':
                    await self.show_weather_settings(query, user.id)
            
            return
        
        # ===== ПРОВЕРКА ПОДПИСКИ =====
        if query.data == "check_our_sub":
            is_subscribed = await self.verify_subscription_now(user.id)
            
            if is_subscribed:
                add_user_to_db(user.id, user.username or user.first_name)
                
                try:
                    await query.message.delete()
                except:
                    pass
                
                await query.message.reply_text("✅ <b>Подписка подтверждена!</b>", parse_mode='HTML')
                await self.show_main_menu(update)
            else:
                await query.answer("❌ Подписка не подтверждена!", show_alert=True)
            return
        
        # ===== АДМИН ФУНКЦИИ =====
        if user.id != ADMIN_ID:
            return
        
        if query.data == "admin_panel":
            await self.show_admin_panel(update)
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
            channel_id = query.data.replace('op_del_', '')
            remove_mandatory_channel(channel_id)
            self.reload_channels()
            await query.answer("✅ Канал удален из ОП!")
            await self.show_op_remove(query)
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
            channel_id = query.data.replace('post_del_', '')
            remove_posting_channel(channel_id)
            self.reload_channels()
            await query.answer("✅ Канал удален из автопостинга!")
            await self.show_post_remove(query)
            return
        
        if query.data == "admin_stats":
            await self.show_stats(query)
            return
        
        if query.data == "admin_delivery_stats":
            await self.show_delivery_stats(query)
            return
        
        if query.data == "mailing_confirm":
            await self.mailing_confirm(update, context)
            return
        
        if query.data == "mailing_cancel":
            await query.message.edit_text("❌ <b>Рассылка отменена</b>", parse_mode='HTML')
            await self.show_admin_panel(update)
            return
    
    async def show_stock_callback(self, query):
        """Показывает текущий сток"""
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
    
    # ========== АДМИН МЕНЮ ==========
    
    async def show_op_menu(self, query):
        self.reload_channels()
        
        text = (
            "🔐 <b>УПРАВЛЕНИЕ ОБЯЗАТЕЛЬНОЙ ПОДПИСКОЙ (ОП)</b>\n\n"
            "Каналы, на которые нужно подписаться для доступа к боту\n\n"
            "<b>Выберите действие:</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("➕ ДОБАВИТЬ КАНАЛ", callback_data="add_op")],
            [InlineKeyboardButton("🗑 УДАЛИТЬ КАНАЛ", callback_data="op_remove")],
            [InlineKeyboardButton("📋 СПИСОК КАНАЛОВ", callback_data="op_list")],
            [InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_panel")]
        ]
        
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
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
        
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_op_list(self, query):
        self.reload_channels()
        
        if not self.mandatory_channels:
            text = "📭 <b>Нет каналов в обязательной подписке</b>"
        else:
            text = "<b>📋 КАНАЛЫ ОБЯЗАТЕЛЬНОЙ ПОДПИСКИ</b>\n\n"
            for ch in self.mandatory_channels:
                text += f"• <b>{ch['name']}</b> (ID: <code>{ch['id']}</code>)\n"
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_op")]]
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_post_menu(self, query):
        self.reload_channels()
        
        text = (
            "📢 <b>УПРАВЛЕНИЕ АВТОПОСТИНГОМ</b>\n\n"
            "Каналы, в которые бот будет отправлять уведомления\n\n"
            "<b>Выберите действие:</b>"
        )
        
        keyboard = [
            [InlineKeyboardButton("➕ ДОБАВИТЬ КАНАЛ", callback_data="add_post")],
            [InlineKeyboardButton("🗑 УДАЛИТЬ КАНАЛ", callback_data="post_remove")],
            [InlineKeyboardButton("📋 СПИСОК КАНАЛОВ", callback_data="post_list")],
            [InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_panel")]
        ]
        
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_post_remove(self, query):
        self.reload_channels()
        
        if not self.posting_channels:
            await query.message.reply_text("📭 <b>Нет каналов для удаления</b>", parse_mode='HTML')
            return
        
        text = "🗑 <b>Выберите канал для удаления из автопостинга:</b>"
        keyboard = []
        for ch in self.posting_channels:
            keyboard.append([InlineKeyboardButton(f"❌ {ch['name']}", callback_data=f"post_del_{ch['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_post")])
        
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_post_list(self, query):
        self.reload_channels()
        
        if not self.posting_channels:
            text = "📭 <b>Нет каналов для автопостинга</b>"
        else:
            text = "<b>📢 КАНАЛЫ ДЛЯ АВТОПОСТИНГА</b>\n\n"
            for ch in self.posting_channels:
                text += f"• <b>{ch['name']}</b> (ID: <code>{ch['id']}</code>)\n"
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_post")]]
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_stats(self, query):
        stats = get_stats()
        
        text = (
            "<b>📊 СТАТИСТИКА БОТА</b>\n\n"
            f"👥 <b>Активных пользователей:</b> {stats['users']}\n"
            f"🚫 <b>Заблокировали бота:</b> {stats['blocked']}\n"
            f"🔐 <b>Каналов ОП:</b> {stats['op_channels']}\n"
            f"📢 <b>Каналов автопостинга:</b> {stats['posting_channels']}\n"
            f"📊 <b>Всего событий:</b> {stats['events']}\n"
            f"📨 <b>Доставлено уведомлений:</b> {stats['deliveries']}"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_panel")]]
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_delivery_stats(self, query):
        """Показывает статистику доставки"""
        stats = self.delivery_manager.get_stats()
        
        text = (
            "<b>📈 СТАТИСТИКА ДОСТАВКИ</b>\n\n"
            f"✅ <b>Отправлено:</b> {stats['sent']}\n"
            f"🚫 <b>Заблокировали:</b> {stats['blocked']}\n"
            f"❌ <b>Ошибок:</b> {stats['failed']}\n"
            f"⏭️ <b>Пропущено:</b> {stats['skipped']}\n"
            f"📊 <b>В очереди:</b> {stats['queue_size']}\n"
            f"⚡ <b>Скорость:</b> {stats['speed']:.1f}/сек"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="admin_panel")]]
        await query.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def mailing_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение и отправка рассылки"""
        query = update.callback_query
        text = context.user_data.get('mailing_text', '')
        
        if not text:
            await query.message.edit_text("❌ <b>Ошибка: текст не найден</b>", parse_mode='HTML')
            return
        
        await query.message.delete()
        
        status_msg = await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="📧 <b>Начинаю рассылку...</b>",
            parse_mode='HTML'
        )
        
        # Получаем всех активных пользователей
        users = get_all_active_users()
        success = 0
        failed = 0
        
        # Создаем событие для рассылки
        event_id = generate_event_id("mailing", len(users), "admin", int(time.time()))
        
        for uid in users:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"<b>📢 РАССЫЛКА</b>\n\n{text}",
                    parse_mode='HTML'
                )
                success += 1
                log_delivery(uid, event_id, 'sent')
                await asyncio.sleep(0.05)  # Небольшая задержка
            except Forbidden:
                mark_user_blocked(uid, "blocked_during_mailing")
                failed += 1
                log_delivery(uid, event_id, 'blocked', 'user_blocked_bot')
            except Exception as e:
                failed += 1
                log_delivery(uid, event_id, 'failed', str(e)[:100])
        
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
            chat_id=ADMIN_ID,
            text=report,
            parse_mode='HTML'
        )
        
        context.user_data.pop('mailing_text', None)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        if not update.message:
            return
        
        # Проверяем, не в диалоге ли мы
        if any(key in context.user_data for key in ['op_channel_id', 'post_channel_id', 'mailing_text']):
            return
    
    # ========== API И ФОРМАТИРОВАНИЕ ==========
    
    def fetch_api_data(self, force=False) -> Optional[Dict]:
        """Получение данных из API"""
        try:
            rand = random.randint(1000, 9999)
            url = f"{API_URL}?r={rand}"
            if force:
                url = f"{API_URL}?t={int(datetime.now().timestamp())}&r={rand}"
            
            response = self.session.get(url, timeout=10)
            
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
        """Форматирование сообщения о стоке"""
        parts = []
        
        if "seeds" in data:
            seeds = []
            for s in data["seeds"]:
                if s["quantity"] > 0 and s["name"] in TRANSLATIONS:
                    seeds.append(f"  • <b>{translate(s['name'])}</b>: {s['quantity']} шт.")
            if seeds:
                parts.append("<b>🌱 СЕМЕНА:</b>\n" + "\n".join(seeds))
        
        if "gear" in data:
            gear = []
            for g in data["gear"]:
                if g["quantity"] > 0 and g["name"] in TRANSLATIONS:
                    gear.append(f"  • <b>{translate(g['name'])}</b>: {g['quantity']} шт.")
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
                        f"<b>🌤 Активна погода:</b>\n"
                        f"{translate(wtype)}\n"
                        f"━━━━━━━━━━━━━━━━\n"
                        f"⏰ До {msk_time} (МСК)"
                    )
                elif wtype in TRANSLATIONS:
                    parts.append(f"<b>🌤 Активна погода:</b>\n{translate(wtype)}")
        
        return "\n\n".join(parts) if parts else None
    
    # ========== ЗАПУСК ==========
    
    async def run(self):
        """Запуск бота"""
        logger.info("🚀 Запуск бота...")
        
        # Запускаем менеджер доставки
        await self.delivery_manager.start()
        
        # Запускаем Discord слушатель
        asyncio.create_task(self.discord_listener.run())
        
        # Запускаем Telegram бота
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("🤖 Бот успешно запущен")
        logger.info(f"👑 Админ: {ADMIN_ID}")
        logger.info(f"🔌 Discord: {'активен' if DISCORD_TOKEN else 'отключён'}")
        
        # Держим бота запущенным
        while True:
            await asyncio.sleep(3600)
            
            # Логируем статистику каждый час
            stats = self.delivery_manager.get_stats()
            logger.info(f"📊 Статистика доставки: отправлено={stats['sent']}, "
                       f"заблокировали={stats['blocked']}, "
                       f"очередь={stats['queue_size']}")

# ========== ТОЧКА ВХОДА ==========

async def main():
    try:
        if not BOT_TOKEN:
            logger.error("❌ Нет BOT_TOKEN в переменных окружения")
            return
        
        bot = GardenHorizonsBot(BOT_TOKEN)
        await bot.run()
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")