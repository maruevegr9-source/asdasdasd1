import os
import json
import logging
import asyncio
import random
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TimedOut

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_CHANNEL_ID = os.getenv("CHANNEL_ID", "-1002808838893")
DEFAULT_REQUIRED_CHANNEL_LINK = "https://t.me/GardenHorizonsStocks"

API_URL = os.getenv("API_URL", "https://garden-horizons-stock.dawidfc.workers.dev/api/stock")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "10"))
ADMIN_ID = 8025951500

# База данных - для Railway используем /data/
if os.environ.get('RAILWAY_ENVIRONMENT'):
    DB_PATH = "/data/bot.db"
    logger.info("✅ Работаем на Railway, БД в /data/bot.db")
else:
    DB_PATH = "bot.db"
    logger.info("✅ Локальная разработка, БД в bot.db")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
MAILING_TEXT, MAILING_CONFIRM = range(4, 6)

# Главное сообщение
MAIN_MENU_TEXT = (
    "🌱 <b>Привет! Я могу отслеживать стоки в игре Garden Horizons, "
    "и отправлять их тебе, круто да? 🔥</b>\n\n"
    "Выберите действие:"
)

# 🌱 ПОЛНЫЙ СЛОВАРЬ ПЕРЕВОДОВ
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

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ==========

def init_database():
    """Создает все необходимые таблицы в базе данных"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Таблица пользователей
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen TEXT,
            notifications_enabled INTEGER DEFAULT 1,
            seeds TEXT DEFAULT '{}',
            gear TEXT DEFAULT '{}',
            weather TEXT DEFAULT '{}'
        )
    """)
    
    # Таблица обязательных каналов (ОП)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS required_channels (
            channel_id TEXT PRIMARY KEY,
            name TEXT,
            link TEXT,
            added_at TEXT
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
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

# Вызываем инициализацию при запуске
init_database()

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ ==========

def get_db():
    """Возвращает соединение с БД"""
    return sqlite3.connect(DB_PATH)

# ----- ПОЛЬЗОВАТЕЛИ -----

def add_user_to_db(user_id: int, username: str = ""):
    """Добавляет или обновляет пользователя в БД"""
    conn = get_db()
    cur = conn.cursor()
    
    # Проверяем, есть ли уже пользователь
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone():
        # Обновляем username если изменился
        cur.execute(
            "UPDATE users SET username = ? WHERE user_id = ?",
            (username, user_id)
        )
    else:
        # Добавляем нового пользователя
        cur.execute(
            "INSERT INTO users (user_id, username, first_seen) VALUES (?, ?, ?)",
            (user_id, username, datetime.now().isoformat())
        )
        # Добавляем все предметы в user_items
        for item in SEEDS_LIST + GEAR_LIST + WEATHER_LIST:
            cur.execute(
                "INSERT INTO user_items (user_id, item_name, enabled) VALUES (?, ?, 1)",
                (user_id, item)
            )
    
    conn.commit()
    conn.close()

def get_user_settings(user_id: int) -> Dict:
    """Получает настройки пользователя из БД"""
    conn = get_db()
    cur = conn.cursor()
    
    # Основные настройки
    cur.execute(
        "SELECT notifications_enabled FROM users WHERE user_id = ?",
        (user_id,)
    )
    result = cur.fetchone()
    notifications_enabled = result[0] if result else True
    
    # Настройки предметов
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

def update_user_setting(user_id: int, setting: str, value: Any):
    """Обновляет настройку пользователя"""
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

def get_all_users() -> List[int]:
    """Возвращает список всех user_id"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return users

def get_users_count() -> int:
    """Возвращает количество пользователей"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    conn.close()
    return count

# ----- ОБЯЗАТЕЛЬНЫЕ КАНАЛЫ (ОП) -----

def get_required_channels() -> List[Dict]:
    """Возвращает список обязательных каналов"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT channel_id, name, link FROM required_channels ORDER BY added_at")
    channels = [
        {'id': row[0], 'name': row[1], 'link': row[2]}
        for row in cur.fetchall()
    ]
    conn.close()
    return channels

def add_required_channel(channel_id: str, name: str, link: str):
    """Добавляет канал в обязательную подписку"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO required_channels (channel_id, name, link, added_at) VALUES (?, ?, ?, ?)",
        (channel_id, name, link, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def remove_required_channel(channel_id: str):
    """Удаляет канал из обязательной подписки"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM required_channels WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()

# ----- КАНАЛЫ ДЛЯ АВТОПОСТИНГА -----

def get_posting_channels() -> List[Dict]:
    """Возвращает список каналов для автопостинга"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT channel_id, name, username FROM posting_channels ORDER BY added_at")
    channels = [
        {'id': row[0], 'name': row[1], 'username': row[2]}
        for row in cur.fetchall()
    ]
    conn.close()
    return channels

def add_posting_channel(channel_id: str, name: str, username: str = None):
    """Добавляет канал для автопостинга"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO posting_channels (channel_id, name, username, added_at) VALUES (?, ?, ?, ?)",
        (channel_id, name, username, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def remove_posting_channel(channel_id: str):
    """Удаляет канал из автопостинга"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM posting_channels WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()

# ----- ОТПРАВЛЕННЫЕ УВЕДОМЛЕНИЯ -----

def was_item_sent(chat_id: int, item_name: str, quantity: int) -> bool:
    """Проверяет, отправлялось ли уже такое уведомление"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM sent_items WHERE chat_id = ? AND item_name = ? AND quantity = ?",
        (chat_id, item_name, quantity)
    )
    count = cur.fetchone()[0]
    conn.close()
    return count > 0

def mark_item_sent(chat_id: int, item_name: str, quantity: int):
    """Отмечает, что уведомление отправлено"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sent_items (chat_id, item_name, quantity, sent_at) VALUES (?, ?, ?, ?)",
        (chat_id, item_name, quantity, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

# ----- СТАТИСТИКА -----

def get_stats() -> Dict:
    """Возвращает статистику бота"""
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM users")
    users_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM required_channels")
    op_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM posting_channels")
    post_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM sent_items")
    sent_count = cur.fetchone()[0]
    
    conn.close()
    
    return {
        'users': users_count,
        'op_channels': op_count,
        'posting_channels': post_count,
        'sent_notifications': sent_count
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
        # Загружаем реальные настройки из БД
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
        """Загружает пользователей из БД в кэш"""
        user_ids = get_all_users()
        for user_id in user_ids:
            self.users[user_id] = UserSettings(user_id)
        logger.info(f"📥 Загружено {len(self.users)} пользователей")
    
    def get_user(self, user_id: int, username: str = "") -> UserSettings:
        if user_id not in self.users:
            # Добавляем в БД если новый
            add_user_to_db(user_id, username)
            self.users[user_id] = UserSettings(user_id, username)
        elif username and self.users[user_id].username != username:
            self.users[user_id].username = username
            # Обновляем в БД
            add_user_to_db(user_id, username)
        return self.users[user_id]
    
    def get_all_users(self) -> List[int]:
        return list(self.users.keys())

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

class GardenHorizonsBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.user_manager = UserManager()
        self.last_data: Optional[Dict] = None
        self.required_channels = get_required_channels()  # Загружаем из БД
        self.posting_channels = get_posting_channels()    # Загружаем из БД
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
        
        self.setup_handlers()
        self.setup_conversation_handlers()
    
    # ========== НАСТРОЙКА ОБРАБОТЧИКОВ ==========
    
    def setup_conversation_handlers(self):
        """Настройка всех диалогов"""
        
        # 1. Диалог добавления канала в ОП
        add_op_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.add_op_start, pattern="^add_op$")],
            states={
                ADD_OP_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_op_id)],
                ADD_OP_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_op_name)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        
        # 2. Диалог добавления канала для автопостинга
        add_post_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.add_post_start, pattern="^add_post$")],
            states={
                ADD_POST_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_post_id)],
                ADD_POST_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_post_name)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        
        # 3. Диалог рассылки
        mailing_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.mailing_start, pattern="^mailing$")],
            states={
                MAILING_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.mailing_get_text)],
                MAILING_CONFIRM: [CallbackQueryHandler(self.mailing_confirm, pattern="^(mailing_yes|mailing_no)$")],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        
        self.application.add_handler(add_op_conv)
        self.application.add_handler(add_post_conv)
        self.application.add_handler(mailing_conv)
    
    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("stock", self.cmd_stock))
        self.application.add_handler(CommandHandler("notifications_on", self.cmd_notifications_on))
        self.application.add_handler(CommandHandler("notifications_off", self.cmd_notifications_off))
        self.application.add_handler(CommandHandler("menu", self.cmd_menu))
        self.application.add_handler(CommandHandler("admin", self.cmd_admin))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    # ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена действия"""
        await update.message.reply_text("❌ Действие отменено")
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def check_subscription(self, user_id: int) -> bool:
        """Проверяет подписку на ВСЕ обязательные каналы"""
        if not self.required_channels:
            # Если нет обязательных каналов - пропускаем
            return True
        
        for channel in self.required_channels:
            try:
                channel_id = channel['id']
                member = await self.application.bot.get_chat_member(chat_id=int(channel_id), user_id=user_id)
                valid_statuses = [ChatMember.MEMBER, ChatMember.OWNER, ChatMember.ADMINISTRATOR, ChatMember.RESTRICTED]
                if member.status not in valid_statuses:
                    logger.info(f"❌ Пользователь {user_id} не подписан на {channel['name']}")
                    return False
            except Exception as e:
                logger.error(f"❌ Ошибка проверки канала {channel_id}: {e}")
                return False
        
        return True
    
    async def require_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Проверяет подписку и показывает сообщение если не подписан"""
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if settings.is_admin:
            return True
        
        is_subscribed = await self.check_subscription(user.id)
        
        if not is_subscribed:
            # Формируем список каналов
            channels_text = ""
            for ch in self.required_channels:
                channels_text += f"▪️ {ch['name']}\n"
            
            text = (
                "🌱 <b>Привет! Я могу отслеживать стоки в игре, "
                "и отправлять их тебе, круто да? 🔥</b>\n\n"
                "❌ <b>Для использования бота необходимо подписаться на наши каналы:</b>\n\n"
                f"{channels_text}\n"
                "После подписки нажми кнопку ниже 👇"
            )
            
            keyboard = []
            for ch in self.required_channels:
                keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch['link'])])
            
            keyboard.append([InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_subscription")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_photo(photo=IMAGE_MAIN, caption=text, parse_mode='HTML', reply_markup=reply_markup)
            elif update.callback_query:
                await update.callback_query.edit_message_media(
                    media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
                    reply_markup=reply_markup
                )
            return False
        
        add_user_to_db(user.id, user.username or user.first_name)
        return True
    
    # ========== КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ ==========
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.user_manager.get_user(user.id, user.username or user.first_name)
        
        if not await self.require_subscription(update, context):
            return
        
        reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
        await update.message.reply_text("🔄 Загружаю меню...", reply_markup=reply_markup)
        await self.show_main_menu(update)
    
    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.require_subscription(update, context):
            return
        await self.show_main_menu(update)
    
    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.require_subscription(update, context):
            return
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        await self.show_main_settings(update, settings)
    
    async def cmd_stock(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.require_subscription(update, context):
            return
        
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
        if not await self.require_subscription(update, context):
            return
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        settings.notifications_enabled = True
        update_user_setting(user.id, 'notifications_enabled', True)
        await update.message.reply_html("<b>✅ Уведомления успешно включены!</b>")
    
    async def cmd_notifications_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.require_subscription(update, context):
            return
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        settings.notifications_enabled = False
        update_user_setting(user.id, 'notifications_enabled', False)
        await update.message.reply_html("<b>✅ Уведомления успешно выключены</b>")
    
    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для открытия админ-панели"""
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        if not settings.is_admin:
            await update.message.reply_text("❌ У вас нет прав!")
            return
        await self.show_admin_panel(update)
    
    # ========== АДМИН-ПАНЕЛЬ ==========
    
    async def show_admin_panel(self, update: Update):
        """Показывает главное меню админ-панели"""
        stats = get_stats()
        
        keyboard = [
            [InlineKeyboardButton("🔐 Настройка ОП", callback_data="op_menu"),
             InlineKeyboardButton("📧 Рассылка", callback_data="mailing")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats"),
             InlineKeyboardButton("📢 Автопостинг", callback_data="post_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main")]
        ]
        
        text = (
            "<b>👑 АДМИН-ПАНЕЛЬ</b>\n\n"
            f"👥 Пользователей: {stats['users']}\n"
            f"🔐 Каналов ОП: {stats['op_channels']}\n"
            f"📢 Каналов для постинга: {stats['posting_channels']}\n"
            f"📨 Отправлено уведомлений: {stats['sent_notifications']}"
        )
        
        if update.message:
            await update.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_admin_panel_callback(self, query):
        """Показывает админ-панель из callback"""
        stats = get_stats()
        
        keyboard = [
            [InlineKeyboardButton("🔐 Настройка ОП", callback_data="op_menu"),
             InlineKeyboardButton("📧 Рассылка", callback_data="mailing")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats"),
             InlineKeyboardButton("📢 Автопостинг", callback_data="post_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main")]
        ]
        
        text = (
            "<b>👑 АДМИН-ПАНЕЛЬ</b>\n\n"
            f"👥 Пользователей: {stats['users']}\n"
            f"🔐 Каналов ОП: {stats['op_channels']}\n"
            f"📢 Каналов для постинга: {stats['posting_channels']}\n"
            f"📨 Отправлено уведомлений: {stats['sent_notifications']}"
        )
        
        await query.edit_message_caption(
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== МЕНЮ НАСТРОЙКИ ОП ==========
    
    async def show_op_menu(self, query):
        """Показывает меню управления обязательными каналами"""
        keyboard = [
            [InlineKeyboardButton("➕ Добавить канал ОП", callback_data="add_op")],
            [InlineKeyboardButton("🗑 Удалить канал ОП", callback_data="remove_op")],
            [InlineKeyboardButton("📋 Список каналов ОП", callback_data="list_op")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
        ]
        
        text = "<b>🔐 НАСТРОЙКА ОБЯЗАТЕЛЬНОЙ ПОДПИСКИ</b>\n\nВыберите действие:"
        
        await query.edit_message_caption(
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # Добавление канала в ОП
    async def add_op_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало добавления канала в ОП"""
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.edit_message_caption(caption="❌ У вас нет прав!")
            return ConversationHandler.END
        
        await query.edit_message_caption(
            caption="📢 <b>Добавление канала в обязательную подписку</b>\n\n"
                    "Отправьте ID канала (например: -1001234567890) или username (@channel):",
            parse_mode='HTML'
        )
        return ADD_OP_CHANNEL_ID
    
    async def add_op_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получает ID канала и запрашивает название"""
        channel_id = update.message.text.strip()
        context.user_data['op_channel_id'] = channel_id
        await update.message.reply_text("✏️ Теперь отправьте название канала (для отображения):")
        return ADD_OP_CHANNEL_NAME
    
    async def add_op_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получает название и сохраняет канал"""
        channel_name = update.message.text.strip()
        channel_id = context.user_data.get('op_channel_id')
        
        try:
            # Получаем информацию о канале
            if channel_id.startswith('@'):
                chat = await self.application.bot.get_chat(channel_id)
            else:
                chat = await self.application.bot.get_chat(int(channel_id))
            
            # Проверяем, что бот админ
            bot_member = await self.application.bot.get_chat_member(chat.id, self.application.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "❌ Бот не является администратором этого канала!\n"
                    "Сделайте бота админом и попробуйте снова."
                )
                await self.show_admin_panel(update)
                return ConversationHandler.END
            
            # Формируем ссылку
            channel_link = f"https://t.me/{chat.username}" if chat.username else f"https://t.me/c/{str(chat.id).replace('-100', '')}"
            
            # Сохраняем в БД
            add_required_channel(str(chat.id), channel_name, channel_link)
            
            # Обновляем локальный кэш
            self.required_channels = get_required_channels()
            
            await update.message.reply_text(
                f"✅ Канал <b>{channel_name}</b> добавлен в обязательную подписку!",
                parse_mode='HTML'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    # Удаление канала из ОП
    async def remove_op(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает список каналов для удаления"""
        query = update.callback_query
        await query.answer()
        
        if not self.required_channels:
            await query.edit_message_caption(caption="📭 Нет каналов для удаления")
            await self.show_op_menu(query)
            return
        
        keyboard = []
        for ch in self.required_channels:
            keyboard.append([InlineKeyboardButton(f"❌ {ch['name']}", callback_data=f"del_op_{ch['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="op_menu")])
        
        await query.edit_message_caption(
            caption="🗑 <b>Выберите канал для удаления:</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def delete_op_channel(self, query):
        """Удаляет канал из ОП"""
        channel_id = query.data.replace('del_op_', '')
        
        # Удаляем из БД
        remove_required_channel(channel_id)
        
        # Обновляем локальный кэш
        self.required_channels = get_required_channels()
        
        await query.edit_message_caption(caption="✅ Канал удален из обязательной подписки!")
        await self.show_op_menu(query)
    
    # Список каналов ОП
    async def list_op(self, query):
        """Показывает список каналов ОП"""
        if not self.required_channels:
            text = "📭 Нет каналов в обязательной подписке"
        else:
            text = "<b>📋 КАНАЛЫ ОБЯЗАТЕЛЬНОЙ ПОДПИСКИ</b>\n\n"
            for ch in self.required_channels:
                text += f"• {ch['name']} (ID: {ch['id']})\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="op_menu")]]
        await query.edit_message_caption(
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== МЕНЮ АВТОПОСТИНГА ==========
    
    async def show_post_menu(self, query):
        """Показывает меню управления каналами для автопостинга"""
        keyboard = [
            [InlineKeyboardButton("➕ Добавить канал", callback_data="add_post")],
            [InlineKeyboardButton("🗑 Удалить канал", callback_data="remove_post")],
            [InlineKeyboardButton("📋 Список каналов", callback_data="list_post")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
        ]
        
        text = "<b>📢 УПРАВЛЕНИЕ АВТОПОСТИНГОМ</b>\n\nВыберите действие:"
        
        await query.edit_message_caption(
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # Добавление канала для автопостинга
    async def add_post_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало добавления канала для автопостинга"""
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.edit_message_caption(caption="❌ У вас нет прав!")
            return ConversationHandler.END
        
        await query.edit_message_caption(
            caption="📢 <b>Добавление канала для автопостинга</b>\n\n"
                    "Отправьте ID канала (например: -1001234567890) или username (@channel):",
            parse_mode='HTML'
        )
        return ADD_POST_CHANNEL_ID
    
    async def add_post_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получает ID канала и запрашивает название"""
        channel_id = update.message.text.strip()
        context.user_data['post_channel_id'] = channel_id
        await update.message.reply_text("✏️ Теперь отправьте название канала (для отображения):")
        return ADD_POST_CHANNEL_NAME
    
    async def add_post_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получает название и сохраняет канал"""
        channel_name = update.message.text.strip()
        channel_id = context.user_data.get('post_channel_id')
        
        try:
            # Получаем информацию о канале
            if channel_id.startswith('@'):
                chat = await self.application.bot.get_chat(channel_id)
            else:
                chat = await self.application.bot.get_chat(int(channel_id))
            
            # Проверяем, что бот админ
            bot_member = await self.application.bot.get_chat_member(chat.id, self.application.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "❌ Бот не является администратором этого канала!\n"
                    "Сделайте бота админом и попробуйте снова."
                )
                await self.show_admin_panel(update)
                return ConversationHandler.END
            
            # Сохраняем в БД
            add_posting_channel(str(chat.id), channel_name, chat.username)
            
            # Обновляем локальный кэш
            self.posting_channels = get_posting_channels()
            
            await update.message.reply_text(
                f"✅ Канал <b>{channel_name}</b> добавлен для автопостинга!",
                parse_mode='HTML'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    # Удаление канала из автопостинга
    async def remove_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает список каналов для удаления"""
        query = update.callback_query
        await query.answer()
        
        if not self.posting_channels:
            await query.edit_message_caption(caption="📭 Нет каналов для удаления")
            await self.show_post_menu(query)
            return
        
        keyboard = []
        for ch in self.posting_channels:
            keyboard.append([InlineKeyboardButton(f"❌ {ch['name']}", callback_data=f"del_post_{ch['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="post_menu")])
        
        await query.edit_message_caption(
            caption="🗑 <b>Выберите канал для удаления из автопостинга:</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def delete_post_channel(self, query):
        """Удаляет канал из автопостинга"""
        channel_id = query.data.replace('del_post_', '')
        
        # Удаляем из БД
        remove_posting_channel(channel_id)
        
        # Обновляем локальный кэш
        self.posting_channels = get_posting_channels()
        
        await query.edit_message_caption(caption="✅ Канал удален из автопостинга!")
        await self.show_post_menu(query)
    
    # Список каналов автопостинга
    async def list_post(self, query):
        """Показывает список каналов для автопостинга"""
        if not self.posting_channels:
            text = "📭 Нет каналов для автопостинга"
        else:
            text = "<b>📢 КАНАЛЫ ДЛЯ АВТОПОСТИНГА</b>\n\n"
            for ch in self.posting_channels:
                text += f"• {ch['name']} (ID: {ch['id']})\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="post_menu")]]
        await query.edit_message_caption(
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== РАССЫЛКА ==========
    
    async def mailing_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало рассылки"""
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.edit_message_caption(caption="❌ У вас нет прав!")
            return ConversationHandler.END
        
        await query.edit_message_caption(
            caption="📧 <b>Рассылка</b>\n\nВведите текст для рассылки:",
            parse_mode='HTML'
        )
        return MAILING_TEXT
    
    async def mailing_get_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получает текст и запрашивает подтверждение"""
        text = update.message.text
        context.user_data['mailing_text'] = text
        
        keyboard = [
            [InlineKeyboardButton("✅ Отправить", callback_data="mailing_yes"),
             InlineKeyboardButton("❌ Отменить", callback_data="mailing_no")]
        ]
        
        await update.message.reply_text(
            f"<b>📧 Подтверждение рассылки</b>\n\n{text}\n\nОтправить?",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MAILING_CONFIRM
    
    async def mailing_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение или отмена рассылки"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "mailing_no":
            await query.edit_message_text("❌ Рассылка отменена")
            await self.show_admin_panel_callback(query)
            return ConversationHandler.END
        
        text = context.user_data.get('mailing_text', '')
        await query.edit_message_text("📧 Начинаю рассылку...")
        
        success = 0
        failed = 0
        users = get_all_users()
        
        for user_id in users:
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=f"<b>📢 РАССЫЛКА</b>\n\n{text}",
                    parse_mode='HTML'
                )
                success += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                failed += 1
                logger.error(f"Ошибка отправки {user_id}: {e}")
        
        await query.message.reply_text(
            f"<b>📊 ОТЧЕТ О РАССЫЛКЕ</b>\n\n"
            f"✅ Успешно: {success}\n❌ Ошибок: {failed}\n👥 Всего: {len(users)}",
            parse_mode='HTML'
        )
        
        await self.show_admin_panel_callback(query)
        return ConversationHandler.END
    
    # ========== СТАТИСТИКА ==========
    
    async def show_stats(self, query):
        """Показывает статистику бота"""
        if query.from_user.id != ADMIN_ID:
            return
        
        stats = get_stats()
        
        text = (
            "<b>📊 СТАТИСТИКА БОТА</b>\n\n"
            f"👥 Всего пользователей: {stats['users']}\n"
            f"🔐 Каналов ОП: {stats['op_channels']}\n"
            f"📢 Каналов для постинга: {stats['posting_channels']}\n"
            f"📨 Отправлено уведомлений: {stats['sent_notifications']}\n"
            f"⏱️ Интервал проверки: {UPDATE_INTERVAL} сек"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
        await query.edit_message_caption(
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== ОБРАБОТКА СООБЩЕНИЙ ==========
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает текстовые сообщения"""
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if not settings.is_admin:
            return
        
        if update.message.text == "🏠 ГЛАВНОЕ МЕНЮ":
            reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await update.message.reply_text("🔄 Возвращаюсь в главное меню...", reply_markup=reply_markup)
            await self.show_main_menu(update)
    
    # ========== ОБРАБОТКА CALLBACK ==========
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает все callback-запросы"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        # Проверка подписки
        if query.data == "check_subscription":
            is_subscribed = await self.check_subscription(user.id)
            if is_subscribed:
                add_user_to_db(user.id, user.username or user.first_name)
                reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
                await query.message.reply_text("🔄 Подписка подтверждена!", reply_markup=reply_markup)
                await self.show_main_menu_callback(query)
            else:
                # Формируем список каналов
                channels_text = ""
                for ch in self.required_channels:
                    channels_text += f"▪️ {ch['name']}\n"
                
                text = (
                    f"❌ <b>Вы еще не подписались на все каналы!</b>\n\n"
                    f"Необходимо подписаться на:\n\n{channels_text}\n"
                    f"После подписки нажмите кнопку еще раз."
                )
                
                keyboard = []
                for ch in self.required_channels:
                    keyboard.append([InlineKeyboardButton(f"📢 {ch['name']}", url=ch['link'])])
                
                keyboard.append([InlineKeyboardButton("✅ ПРОВЕРИТЬ СНОВА", callback_data="check_subscription")])
                
                await query.edit_message_media(
                    media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return
        
        # Главная админ-панель
        if query.data == "admin_panel":
            if not settings.is_admin:
                await query.edit_message_caption(caption="❌ <b>У вас нет прав доступа!</b>", parse_mode='HTML')
                return
            await self.show_admin_panel_callback(query)
            return
        
        # Меню ОП
        if query.data == "op_menu":
            if not settings.is_admin:
                return
            await self.show_op_menu(query)
            return
        
        # Удаление канала из ОП
        if query.data == "remove_op":
            if not settings.is_admin:
                return
            await self.remove_op(update, context)
            return
        
        # Список каналов ОП
        if query.data == "list_op":
            if not settings.is_admin:
                return
            await self.list_op(query)
            return
        
        # Удаление конкретного канала из ОП
        if query.data.startswith("del_op_"):
            if not settings.is_admin:
                return
            await self.delete_op_channel(query)
            return
        
        # Меню автопостинга
        if query.data == "post_menu":
            if not settings.is_admin:
                return
            await self.show_post_menu(query)
            return
        
        # Удаление канала из автопостинга
        if query.data == "remove_post":
            if not settings.is_admin:
                return
            await self.remove_post(update, context)
            return
        
        # Список каналов автопостинга
        if query.data == "list_post":
            if not settings.is_admin:
                return
            await self.list_post(query)
            return
        
        # Удаление конкретного канала из автопостинга
        if query.data.startswith("del_post_"):
            if not settings.is_admin:
                return
            await self.delete_post_channel(query)
            return
        
        # Статистика
        if query.data == "stats":
            if not settings.is_admin:
                return
            await self.show_stats(query)
            return
        
        # Обработка удаления каналов (передаем в ConversationHandler)
        if query.data in ["add_op", "add_post", "mailing"]:
            # Передаем управление ConversationHandler
            return
        
        # Основное меню (для всех пользователей)
        if not await self.require_subscription(update, context):
            return
        
        if query.data == "menu_main":
            reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await query.message.reply_text("🔄 Возвращаюсь в главное меню...", reply_markup=reply_markup)
            await self.show_main_menu_callback(query)
            return
        
        if query.data == "menu_settings":
            await self.show_main_settings_callback(query, settings)
            return
        
        if query.data == "menu_stock":
            await self.show_stock_callback(query)
            return
        
        if query.data == "notifications_on":
            settings.notifications_enabled = True
            update_user_setting(user.id, 'notifications_enabled', True)
            await query.edit_message_caption(caption="<b>✅ Уведомления включены!</b>", parse_mode='HTML')
            await asyncio.sleep(1)
            await self.show_main_menu_callback(query)
            return
        
        if query.data == "notifications_off":
            settings.notifications_enabled = False
            update_user_setting(user.id, 'notifications_enabled', False)
            await query.edit_message_caption(caption="<b>✅ Уведомления выключены</b>", parse_mode='HTML')
            await asyncio.sleep(1)
            await self.show_main_menu_callback(query)
            return
        
        if query.data == "settings_seeds":
            await self.show_seeds_settings(query, settings)
            return
        
        if query.data.startswith("seed_"):
            await self.handle_seed_callback(query, settings)
            return
        
        if query.data == "settings_gear":
            await self.show_gear_settings(query, settings)
            return
        
        if query.data.startswith("gear_"):
            await self.handle_gear_callback(query, settings)
            return
        
        if query.data == "settings_weather":
            await self.show_weather_settings(query, settings)
            return
        
        if query.data.startswith("weather_"):
            await self.handle_weather_callback(query, settings)
            return
    
    # ========== ОТОБРАЖЕНИЕ МЕНЮ ==========
    
    async def show_main_menu(self, update: Update):
        """Показывает главное меню"""
        # Формируем текст с каналами
        channels_text = ""
        if self.required_channels:
            channels_text = "\n\n<b>Обязательные каналы:</b>\n"
            for ch in self.required_channels:
                channels_text += f"▪️ {ch['name']}\n"
        
        text = MAIN_MENU_TEXT + channels_text
        
        keyboard = [
            [InlineKeyboardButton("⚙️ АВТО-СТОК", callback_data="menu_settings"),
             InlineKeyboardButton("📦 СТОК", callback_data="menu_stock")],
            [InlineKeyboardButton("🔔 УВЕДОМЛЕНИЯ", callback_data="notifications_on"),
             InlineKeyboardButton("🔕 УВЕДОМЛЕНИЯ", callback_data="notifications_off")]
        ]
        
        settings = self.user_manager.get_user(update.effective_user.id)
        if settings.is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        reply_markup_remove = ReplyKeyboardMarkup([[]], resize_keyboard=True)
        await update.message.reply_text("🔄 Обновляю меню...", reply_markup=reply_markup_remove)
        await update.message.reply_photo(photo=IMAGE_MAIN, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_main_menu_callback(self, query):
        user = query.from_user
        settings = self.user_manager.get_user(user.id)
        
        # Формируем текст с каналами
        channels_text = ""
        if self.required_channels:
            channels_text = "\n\n<b>Обязательные каналы:</b>\n"
            for ch in self.required_channels:
                channels_text += f"▪️ {ch['name']}\n"
        
        text = MAIN_MENU_TEXT + channels_text
        
        keyboard = [
            [InlineKeyboardButton("⚙️ АВТО-СТОК", callback_data="menu_settings"),
             InlineKeyboardButton("📦 СТОК", callback_data="menu_stock")],
            [InlineKeyboardButton("🔔 УВЕДОМЛЕНИЯ", callback_data="notifications_on"),
             InlineKeyboardButton("🔕 УВЕДОМЛЕНИЯ", callback_data="notifications_off")]
        ]
        
        if settings.is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        await query.edit_message_media(
            media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_main_settings(self, update: Update, settings: UserSettings):
        status = "🔔 ВКЛ" if settings.notifications_enabled else "🔕 ВЫКЛ"
        text = f"<b>⚙️ АВТО-СТОК</b>\n\n<b>Уведомления: {status}</b>\n\nВыберите категорию:"
        keyboard = [
            [InlineKeyboardButton("🌱 СЕМЕНА", callback_data="settings_seeds"),
             InlineKeyboardButton("⚙️ СНАРЯЖЕНИЕ", callback_data="settings_gear")],
            [InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather"),
             InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
        ]
        await update.message.reply_photo(photo=IMAGE_MAIN, caption=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_main_settings_callback(self, query, settings: UserSettings):
        status = "🔔 ВКЛ" if settings.notifications_enabled else "🔕 ВЫКЛ"
        text = f"<b>⚙️ АВТО-СТОК</b>\n\n<b>Уведомления: {status}</b>\n\nВыберите категорию:"
        keyboard = [
            [InlineKeyboardButton("🌱 СЕМЕНА", callback_data="settings_seeds"),
             InlineKeyboardButton("⚙️ СНАРЯЖЕНИЕ", callback_data="settings_gear")],
            [InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather"),
             InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]
        ]
        await query.edit_message_media(
            media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
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
        await query.edit_message_media(
            media=InputMediaPhoto(media=IMAGE_SEEDS, caption=text, parse_mode='HTML'),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
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
        await query.edit_message_media(
            media=InputMediaPhoto(media=IMAGE_GEAR, caption=text, parse_mode='HTML'),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
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
        await query.edit_message_media(
            media=InputMediaPhoto(media=IMAGE_WEATHER, caption=text, parse_mode='HTML'),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_stock_callback(self, query):
        await query.edit_message_media(media=InputMediaPhoto(media=IMAGE_MAIN, caption="<b>🔍 Получаю данные...</b>", parse_mode='HTML'))
        data = self.fetch_api_data(force=True)
        if not data:
            await query.edit_message_media(media=InputMediaPhoto(media=IMAGE_MAIN, caption="<b>❌ Ошибка</b>", parse_mode='HTML'))
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
            self.user_manager.save_users()
            await self.show_seeds_settings(query, settings)
    
    async def handle_gear_callback(self, query, settings: UserSettings):
        parts = query.data.split("_")
        if len(parts) >= 3:
            gear_name = "_".join(parts[2:])
            enabled = not settings.gear[gear_name].enabled
            settings.gear[gear_name].enabled = enabled
            update_user_setting(settings.user_id, f"gear_{gear_name}", enabled)
            self.user_manager.save_users()
            await self.show_gear_settings(query, settings)
    
    async def handle_weather_callback(self, query, settings: UserSettings):
        parts = query.data.split("_")
        if len(parts) >= 3:
            weather_name = "_".join(parts[2:])
            enabled = not settings.weather[weather_name].enabled
            settings.weather[weather_name].enabled = enabled
            update_user_setting(settings.user_id, f"weather_{weather_name}", enabled)
            self.user_manager.save_users()
            await self.show_weather_settings(query, settings)
    
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
        if "weather" in data and data["weather"].get("active"):
            wtype = data["weather"]["type"]
            if wtype in TRANSLATIONS:
                parts.append(f"<b>{translate(wtype)} АКТИВНА</b>")
        return "\n\n".join(parts) if parts else None
    
    def format_channel_message(self, item_name: str, quantity: int) -> str:
        translated = translate(item_name)
        return (
            f"✨ <b>{translated}</b>\n"
            f"<b>Количество:</b> {quantity} шт.\n"
            f"━━━━━━━━━━━━━━\n"
            f"<a href='{DEFAULT_REQUIRED_CHANNEL_LINK}'>Наш канал</a> | <a href='{BOT_LINK}'>Авто-сток</a> | <a href='{CHAT_LINK}'>Наш чат</a>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👀 Включи уведомления в канале!"
        )
    
    def format_pm_message(self, items: List[tuple]) -> str:
        """Форматирует сообщение со ВСЕМИ изменениями для пользователя"""
        if not items:
            return None
        
        message = "<b>🔔 НОВЫЕ ПРЕДМЕТЫ В СТОКЕ</b>\n\n"
        
        for item_name, quantity in items:
            translated = translate(item_name)
            message += f"<b>{translated}:</b> {quantity} шт.\n"
        
        return message
    
    def get_changed_items(self, old_data: Dict, new_data: Dict) -> Dict[str, int]:
        """Получает только предметы которые появились или увеличились"""
        changes = {}
        
        if "seeds" in new_data:
            old_seeds = {s["name"]: s["quantity"] for s in old_data.get("seeds", [])}
            new_seeds = {s["name"]: s["quantity"] for s in new_data["seeds"]}
            
            for name, new_q in new_seeds.items():
                if name not in TRANSLATIONS:
                    continue
                old_q = old_seeds.get(name, 0)
                if new_q > old_q:
                    changes[name] = new_q
                    logger.info(f"✅ {name} изменилось: {old_q} → {new_q}")
        
        if "gear" in new_data:
            old_gear = {g["name"]: g["quantity"] for g in old_data.get("gear", [])}
            new_gear = {g["name"]: g["quantity"] for g in new_data["gear"]}
            
            for name, new_q in new_gear.items():
                if name not in TRANSLATIONS:
                    continue
                old_q = old_gear.get(name, 0)
                if new_q > old_q:
                    changes[name] = new_q
                    logger.info(f"✅ {name} изменилось: {old_q} → {new_q}")
        
        if "weather" in new_data:
            old_weather = old_data.get("weather", {})
            new_weather = new_data["weather"]
            wtype = new_weather.get("type")
            if wtype and wtype in TRANSLATIONS:
                if new_weather.get("active") and not old_weather.get("active"):
                    changes[wtype] = 1
                    logger.info(f"✅ {wtype} началась")
        
        return changes
    
    def get_user_items(self, changes: Dict[str, int], settings: UserSettings) -> List[tuple]:
        """Фильтрует изменения по настройкам пользователя"""
        user_items = []
        
        for name, quantity in changes.items():
            if name in SEEDS_LIST:
                if settings.seeds.get(name, ItemSettings()).enabled:
                    user_items.append((name, quantity))
            elif name in GEAR_LIST:
                if settings.gear.get(name, ItemSettings()).enabled:
                    user_items.append((name, quantity))
            elif name in WEATHER_LIST:
                if settings.weather.get(name, ItemSettings()).enabled:
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
                    if new_data.get("lastGlobalUpdate") != self.last_data.get("lastGlobalUpdate"):
                        logger.info(f"✅ Обнаружены изменения в API!")
                        changes = self.get_changed_items(self.last_data, new_data)
                        
                        if changes:
                            logger.info(f"✅ Изменились предметы: {changes}")
                            
                            # 1. Отправляем в ОСНОВНОЙ канал (твой личный)
                            main_channel_items = {}
                            for name, new_q in changes.items():
                                if is_allowed_for_main_channel(name):
                                    main_channel_items[name] = new_q
                            
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
                                        logger.info(f"📢 В канал {channel['name']}: {name} = {qty}")
                            
                            # 3. Отправляем пользователям
                            users = get_all_users()
                            for user_id in users:
                                settings = self.user_manager.get_user(user_id)
                                if await self.check_subscription(user_id) and settings.notifications_enabled:
                                    user_items = self.get_user_items(changes, settings)
                                    if user_items:
                                        # Проверяем, не отправляли ли уже это обновление
                                        update_key = f"user_{user_id}_{new_data.get('lastGlobalUpdate')}"
                                        if not was_item_sent(user_id, update_key, 1):
                                            msg = self.format_pm_message(user_items)
                                            await self.message_queue.queue.put((user_id, msg, 'HTML', None))
                                            mark_item_sent(user_id, update_key, 1)
                                            logger.info(f"👤 Пользователю {user_id} отправлено {len(user_items)} предметов")
                            
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