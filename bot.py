import os
import json
import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TimedOut

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_CHANNEL_ID = os.getenv("CHANNEL_ID", "-1002808838893")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "-1002808838893")
REQUIRED_CHANNEL_LINK = os.getenv("REQUIRED_CHANNEL_LINK", "https://t.me/GardenHorizonsStocks")
REQUIRED_CHANNEL_USERNAME = os.getenv("REQUIRED_CHANNEL_USERNAME", "@GardenHorizonsStocks")

API_URL = os.getenv("API_URL", "https://garden-horizons-stock.dawidfc.workers.dev/api/stock")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "5"))  # 5 секунд для МАКСИМАЛЬНОЙ скорости
ADMIN_ID = 8025951500

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
DEFAULT_CHANNEL_LINK = "https://t.me/GardenHorizonsStocks"
BOT_LINK = "https://t.me/GardenHorizons_StocksBot"
CHAT_LINK = "https://t.me/GardenHorizons_Trade"

# Файлы для хранения данных
CHANNELS_FILE = 'channels.json'

# Главное сообщение
MAIN_MENU_TEXT = (
    "🌱 <b>Привет! Я могу отслеживать стоки в игре Garden Horizons, "
    "и отправлять их тебе, круто да? 🔥</b>\n\n"
    f"<b>Наш канал</b> - {REQUIRED_CHANNEL_LINK}\n"
    f"<b>Наш чат</b> - {CHAT_LINK}\n\n"
    "Выберите действие:"
)

# 🌱 ПОЛНЫЙ СЛОВАРЬ ПЕРЕВОДОВ
TRANSLATIONS = {
    # Семена
    "Carrot": "🥕 Морковь",
    "Corn": "🌽 Кукуруза", 
    "Onion": "🧅 Лук",
    "Strawberry": "🍓 Клубника",
    "Mushroom": "🍄 Гриб",
    "Beetroot": "🍠 Свекла",
    "Tomato": "🍅 Помидор",
    "Apple": "🍎 Яблоко",
    "Rose": "🌹 Роза",
    "Wheat": "🌾 Пшеница",
    "Banana": "🍌 Банан",
    "Plum": "🍐 Слива",
    "Potato": "🥔 Картофель",
    "Cabbage": "🥬 Капуста",
    "Cherry": "🍒 Вишня",
    
    # Снаряжение
    "Watering Can": "💧 Лейка",
    "Basic Sprinkler": "💦 Простой разбрызгиватель",
    "Harvest Bell": "🔔 Колокол сбора",
    "Turbo Sprinkler": "⚡ Турбо-разбрызгиватель",
    "Favorite Tool": "⭐ Любимый инструмент",
    "Super Sprinkler": "💎 Супер-разбрызгиватель",
    
    # Погода
    "fog": "🌫️ Туман",
    "rain": "🌧️ Дождь",
    "snow": "❄️ Снег",
    "storm": "⛈️ Шторм",
    "sandstorm": "🏜️ Песчаная буря",
    "starfall": "⭐ Звездопад"
}

# Список РАЗРЕШЕННЫХ растений для основного канала
ALLOWED_CHANNEL_ITEMS = ["Potato", "Cabbage", "Cherry"]

# Списки для удобства
SEEDS_LIST = ["Carrot", "Corn", "Onion", "Strawberry", "Mushroom", "Beetroot", "Tomato", "Apple", "Rose", "Wheat", "Banana", "Plum", "Potato", "Cabbage", "Cherry"]
GEAR_LIST = ["Watering Can", "Basic Sprinkler", "Harvest Bell", "Turbo Sprinkler", "Favorite Tool", "Super Sprinkler"]
WEATHER_LIST = ["fog", "rain", "snow", "storm", "sandstorm", "starfall"]

# Редкие предметы
RARE_ITEMS = ["Super Sprinkler", "Favorite Tool", "starfall"]

# Защита от спама
SPAM_PROTECTION_SECONDS = 10  # Уменьшил для более частых уведомлений
last_notification_time: Dict[int, datetime] = {}

def translate(text: str) -> str:
    return TRANSLATIONS.get(text, text)

def is_rare(item_name: str) -> bool:
    return item_name in RARE_ITEMS

def is_allowed_for_main_channel(item_name: str) -> bool:
    return item_name in ALLOWED_CHANNEL_ITEMS

def can_send_notification(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    last_time = last_notification_time.get(user_id)
    if not last_time:
        return True
    elapsed = (datetime.now() - last_time).total_seconds()
    return elapsed >= SPAM_PROTECTION_SECONDS

def update_last_notification(user_id: int):
    last_notification_time[user_id] = datetime.now()

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
        for seed in SEEDS_LIST:
            if seed not in self.seeds:
                self.seeds[seed] = ItemSettings(enabled=True)
        for gear in GEAR_LIST:
            if gear not in self.gear:
                self.gear[gear] = ItemSettings(enabled=True)
        for weather in WEATHER_LIST:
            if weather not in self.weather:
                self.weather[weather] = ItemSettings(enabled=True)
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
    def __init__(self, filename='users.json'):
        self.filename = filename
        self.users: Dict[int, UserSettings] = {}
        self.load_users()
    
    def load_users(self):
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for user_id, user_data in data.items():
                        self.users[int(user_id)] = UserSettings.from_dict(user_data)
                logger.info(f"📥 Загружено {len(self.users)} пользователей")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки пользователей: {e}")
    
    def save_users(self):
        try:
            data = {str(uid): settings.to_dict() for uid, settings in self.users.items()}
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 Сохранено {len(self.users)} пользователей")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения пользователей: {e}")
    
    def get_user(self, user_id: int, username: str = "") -> UserSettings:
        if user_id not in self.users:
            self.users[user_id] = UserSettings(user_id, username)
            self.save_users()
        elif username and self.users[user_id].username != username:
            self.users[user_id].username = username
            self.save_users()
        return self.users[user_id]
    
    def get_all_users(self) -> List[int]:
        return list(self.users.keys())

class MessageQueue:
    def __init__(self, delay: float = 0.02):  # 20ms между сообщениями
        self.queue = asyncio.Queue()
        self.delay = delay
        self._task = None
    
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
                bot_app = Application.bot()
                await bot_app.send_message(
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
                bot_app = Application.bot()
                await bot_app.send_photo(
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
        self.last_seen_items: Dict[str, int] = {}
        self.mailing_text: Optional[str] = None
        self.mailing_target: Optional[str] = None
        self.message_queue = MessageQueue(delay=0.02)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        })
        
        self.setup_handlers()
    
    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("stock", self.cmd_stock))
        self.application.add_handler(CommandHandler("notifications_on", self.cmd_notifications_on))
        self.application.add_handler(CommandHandler("notifications_off", self.cmd_notifications_off))
        self.application.add_handler(CommandHandler("mailing", self.cmd_mailing))
        self.application.add_handler(CommandHandler("setchannel", self.cmd_set_channel))
        self.application.add_handler(CommandHandler("addchannel", self.cmd_add_channel))
        self.application.add_handler(CommandHandler("channels", self.cmd_list_channels))
        self.application.add_handler(CommandHandler("testapi", self.cmd_test_api))
        self.application.add_handler(CommandHandler("menu", self.cmd_menu))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    async def check_subscription(self, user_id: int) -> bool:
        """Проверка подписки пользователя на обязательный канал"""
        try:
            if not REQUIRED_CHANNEL_ID:
                logger.error("REQUIRED_CHANNEL_ID не задан!")
                return True  # Пропускаем если не задан
            
            logger.info(f"🔍 Проверка подписки {user_id} на канал {REQUIRED_CHANNEL_ID}")
            
            member = await self.application.bot.get_chat_member(
                chat_id=int(REQUIRED_CHANNEL_ID),
                user_id=user_id
            )
            
            valid_statuses = [
                ChatMember.MEMBER,
                ChatMember.OWNER,
                ChatMember.ADMINISTRATOR,
                ChatMember.RESTRICTED
            ]
            
            is_subscribed = member.status in valid_statuses
            logger.info(f"✅ Результат проверки {user_id}: {member.status} -> {is_subscribed}")
            
            return is_subscribed
            
        except Exception as e:
            logger.error(f"❌ Ошибка проверки подписки {user_id}: {e}")
            # В случае ошибки пропускаем, чтобы не блокировать пользователей
            return True
    
    async def require_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Проверка подписки с обработкой исключений"""
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        # Админа пропускаем без проверки
        if settings.is_admin:
            return True
        
        try:
            is_subscribed = await self.check_subscription(user.id)
        except Exception as e:
            logger.error(f"❌ Критическая ошибка проверки подписки: {e}")
            return True
        
        if not is_subscribed:
            text = (
                "🌱 <b>Привет! Я могу отслеживать стоки в игре, "
                "и отправлять их тебе, круто да? 🔥</b>\n\n"
                "❌ <b>Для использования бота необходимо подписаться на наш канал:</b>\n"
                f"{REQUIRED_CHANNEL_LINK}\n\n"
                "После подписки нажми кнопку ниже 👇"
            )
            
            keyboard = [
                [InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=REQUIRED_CHANNEL_LINK)],
                [InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_subscription")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_photo(
                    photo=IMAGE_MAIN,
                    caption=text,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            elif update.callback_query:
                await update.callback_query.edit_message_media(
                    media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
                    reply_markup=reply_markup
                )
            
            return False
        
        return True
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id, user.username or user.first_name)
        
        if not await self.require_subscription(update, context):
            return
        
        # Убираем реплай клавиатуру при старте
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
        self.user_manager.save_users()
        await update.message.reply_html("<b>✅ Уведомления успешно включены!</b>")
    
    async def cmd_notifications_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.require_subscription(update, context):
            return
        
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        settings.notifications_enabled = False
        self.user_manager.save_users()
        await update.message.reply_html("<b>✅ Уведомления успешно выключены</b>")
    
    async def cmd_mailing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if not settings.is_admin:
            await update.message.reply_html("<b>❌ У вас нет прав!</b>")
            return
        
        if context.args:
            self.mailing_text = " ".join(context.args)
            self.mailing_target = 'users'
            
            text = (
                f"<b>📧 ПОДТВЕРЖДЕНИЕ РАССЫЛКИ ПОЛЬЗОВАТЕЛЯМ</b>\n\n"
                f"<b>Текст:</b>\n{self.mailing_text}\n\n"
                f"<b>Получателей:</b> {len(self.user_manager.users)}\n\n"
                f"Подтвердите:"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ ПОДТВЕРДИТЬ", callback_data="mailing_confirm"),
                    InlineKeyboardButton("❌ ОТМЕНИТЬ", callback_data="mailing_cancel"),
                    InlineKeyboardButton("🏠 МЕНЮ", callback_data="menu_main")
                ]
            ]
            await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_html(
                "<b>📧 РАССЫЛКА</b>\n\n"
                "Отправьте текст для рассылки пользователям\n"
                "Или используйте /mailing текст"
            )
    
    async def cmd_set_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if not settings.is_admin:
            await update.message.reply_html("<b>❌ У вас нет прав!</b>")
            return
        
        # Здесь можно добавить логику смены канала
        await update.message.reply_html("<b>⚙️ Функция в разработке</b>")
    
    async def cmd_add_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if not settings.is_admin:
            await update.message.reply_html("<b>❌ У вас нет прав!</b>")
            return
        
        if not context.args:
            await update.message.reply_html(
                "<b>📢 ДОБАВЛЕНИЕ КАНАЛА</b>\n\n"
                "Использование: /addchannel CHANNEL_ID\n\n"
                "Пример: /addchannel -1001234567890"
            )
            return
        
        try:
            channel_id = context.args[0]
            chat = await self.application.bot.get_chat(chat_id=int(channel_id))
            
            channels = []
            if os.path.exists(CHANNELS_FILE):
                with open(CHANNELS_FILE, 'r') as f:
                    channels = json.load(f)
            
            if channel_id not in channels:
                channels.append(channel_id)
                with open(CHANNELS_FILE, 'w') as f:
                    json.dump(channels, f)
                
                await update.message.reply_html(
                    f"<b>✅ Канал добавлен!</b>\n\n"
                    f"ID: {channel_id}\n"
                    f"Название: {chat.title}\n"
                    f"Теперь бот будет отправлять стоки и туда."
                )
            else:
                await update.message.reply_html("<b>❌ Канал уже добавлен!</b>")
                
        except Exception as e:
            await update.message.reply_html(f"<b>❌ Ошибка: {e}</b>")
    
    async def cmd_list_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if not settings.is_admin:
            await update.message.reply_html("<b>❌ У вас нет прав!</b>")
            return
        
        text = f"<b>📋 КАНАЛЫ</b>\n\n"
        text += f"<b>Обязательный канал:</b>\n"
        text += f"ID: {REQUIRED_CHANNEL_ID}\n"
        text += f"Ссылка: {REQUIRED_CHANNEL_LINK}\n\n"
        
        text += f"<b>Дополнительные каналы для стоков:</b>\n"
        if os.path.exists(CHANNELS_FILE):
            with open(CHANNELS_FILE, 'r') as f:
                channels = json.load(f)
                if channels:
                    for ch in channels:
                        try:
                            chat = await self.application.bot.get_chat(chat_id=int(ch))
                            text += f"• {ch} - {chat.title}\n"
                        except:
                            text += f"• {ch} - (недоступен)\n"
                else:
                    text += "• Нет дополнительных каналов\n"
        else:
            text += "• Нет дополнительных каналов\n"
        
        keyboard = [[InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]]
        await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def cmd_test_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if not settings.is_admin:
            await update.message.reply_html("<b>❌ Только для админа!</b>")
            return
        
        await update.message.reply_html("<b>🔍 Тестирую API...</b>")
        
        data = self.fetch_api_data(force=True)
        current_time = datetime.now().isoformat()
        
        if data:
            seeds = data.get("seeds", [])
            seeds_text = "\n".join([f"  • {s['name']}: {s['quantity']}" for s in seeds if s['quantity'] > 0])
            
            msg = (
                f"<b>📊 ТЕСТ API</b>\n\n"
                f"<b>Последнее обновление:</b>\n{data.get('lastGlobalUpdate')}\n\n"
                f"<b>Текущее время:</b>\n{current_time}\n\n"
                f"<b>Семена в стоке:</b>\n{seeds_text}"
            )
        else:
            msg = "<b>❌ API не отвечает</b>"
        
        keyboard = [[InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]]
        await update.message.reply_html(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        text = update.message.text
        
        # Если админ и есть активная рассылка
        if settings.is_admin and self.mailing_target:
            if text == "🏠 ГЛАВНОЕ МЕНЮ":
                self.mailing_target = None
                self.mailing_text = None
                await self.show_main_menu(update)
                return
            
            self.mailing_text = text
            
            if self.mailing_target == 'users':
                target_text = f"<b>📧 РАССЫЛКА ПОЛЬЗОВАТЕЛЯМ</b>\n\n"
                target_count = len(self.user_manager.users)
            else:
                target_text = f"<b>📧 РАССЫЛКА В КАНАЛ</b>\n\n"
                target_count = 1
            
            confirm_text = (
                f"{target_text}"
                f"<b>Текст:</b>\n{self.mailing_text}\n\n"
                f"<b>Получателей:</b> {target_count}\n\n"
                f"Подтвердите:"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ ПОДТВЕРДИТЬ", callback_data="mailing_confirm"),
                    InlineKeyboardButton("❌ ОТМЕНИТЬ", callback_data="mailing_cancel"),
                    InlineKeyboardButton("🏠 МЕНЮ", callback_data="menu_main")
                ]
            ]
            
            await update.message.reply_html(confirm_text, reply_markup=InlineKeyboardMarkup(keyboard))
            return
        
        # Для всех остальных сообщений
        if text == "🏠 ГЛАВНОЕ МЕНЮ":
            await self.show_main_menu(update)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        # Проверка подписки
        if query.data == "check_subscription":
            is_subscribed = await self.check_subscription(user.id)
            
            if is_subscribed:
                await self.show_main_menu_callback(query)
            else:
                text = (
                    "❌ <b>Вы еще не подписались!</b>\n\n"
                    f"Подпишитесь на канал {REQUIRED_CHANNEL_LINK} и нажмите кнопку еще раз."
                )
                keyboard = [
                    [InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=REQUIRED_CHANNEL_LINK)],
                    [InlineKeyboardButton("✅ ПРОВЕРИТЬ СНОВА", callback_data="check_subscription")]
                ]
                await query.edit_message_media(
                    media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return
        
        # Админ-панель
        if query.data == "admin_panel":
            if not settings.is_admin:
                await query.edit_message_caption(
                    caption="❌ <b>У вас нет прав доступа!</b>",
                    parse_mode='HTML'
                )
                return
            
            # Показываем реплай клавиатуру админа
            reply_keyboard = [
                [KeyboardButton("📢 Рассылка пользователям")],
                [KeyboardButton("📢 Рассылка в канал")],
                [KeyboardButton("➕ Добавить канал")],
                [KeyboardButton("📋 Список каналов")],
                [KeyboardButton("🔍 Тест API")],
                [KeyboardButton("🏠 ГЛАВНОЕ МЕНЮ")]
            ]
            reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
            
            await query.message.reply_text(
                "<b>👑 АДМИН-ПАНЕЛЬ</b>\n\nВыберите действие на клавиатуре ниже:",
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            
            # Редактируем исходное сообщение с главным меню
            await query.edit_message_caption(
                caption="✅ <b>Админ-панель активирована</b>\n\nИспользуйте клавиатуру внизу экрана.",
                parse_mode='HTML'
            )
            return
        
        if not await self.require_subscription(update, context):
            return
        
        if query.data == "mailing_confirm":
            if not settings.is_admin:
                return
            
            await query.edit_message_caption(caption="<b>📧 Начинаю рассылку...</b>", parse_mode='HTML')
            
            success = 0
            failed = 0
            
            if self.mailing_target == 'users':
                for uid in self.user_manager.get_all_users():
                    try:
                        await self.message_queue.queue.put((
                            uid,
                            f"<b>📢 РАССЫЛКА</b>\n\n{self.mailing_text}",
                            'HTML',
                            None
                        ))
                        success += 1
                    except Exception as e:
                        failed += 1
                        logger.error(f"Ошибка {uid}: {e}")
                
                report = f"<b>📊 ОТЧЕТ</b>\n\n✅ Успешно: {success}\n❌ Ошибок: {failed}"
            
            else:
                try:
                    await self.message_queue.queue.put((
                        int(MAIN_CHANNEL_ID),
                        f"<b>📢 ОБЪЯВЛЕНИЕ</b>\n\n{self.mailing_text}",
                        'HTML',
                        None
                    ))
                    report = "<b>✅ Сообщение отправлено в канал</b>"
                except Exception as e:
                    report = f"<b>❌ Ошибка: {e}</b>"
            
            await self.application.bot.send_message(
                chat_id=ADMIN_ID,
                text=report,
                parse_mode='HTML'
            )
            
            self.mailing_text = None
            self.mailing_target = None
        
        elif query.data == "mailing_cancel":
            self.mailing_text = None
            self.mailing_target = None
            await query.edit_message_caption(caption="❌ Отменено", parse_mode='HTML')
        
        elif query.data == "menu_main":
            await self.show_main_menu_callback(query)
        
        elif query.data == "menu_settings":
            await self.show_main_settings_callback(query, settings)
        
        elif query.data == "menu_stock":
            await self.show_stock_callback(query)
        
        elif query.data == "notifications_on":
            settings.notifications_enabled = True
            self.user_manager.save_users()
            await query.edit_message_caption(caption="<b>✅ Уведомления включены!</b>", parse_mode='HTML')
            await asyncio.sleep(1)
            await self.show_main_menu_callback(query)
        
        elif query.data == "notifications_off":
            settings.notifications_enabled = False
            self.user_manager.save_users()
            await query.edit_message_caption(caption="<b>✅ Уведомления выключены</b>", parse_mode='HTML')
            await asyncio.sleep(1)
            await self.show_main_menu_callback(query)
        
        elif query.data == "settings_seeds":
            await self.show_seeds_settings(query, settings)
        elif query.data.startswith("seed_"):
            await self.handle_seed_callback(query, settings)
        elif query.data == "settings_gear":
            await self.show_gear_settings(query, settings)
        elif query.data.startswith("gear_"):
            await self.handle_gear_callback(query, settings)
        elif query.data == "settings_weather":
            await self.show_weather_settings(query, settings)
        elif query.data.startswith("weather_"):
            await self.handle_weather_callback(query, settings)
    
    async def show_main_menu(self, update: Update):
        keyboard = [
            [
                InlineKeyboardButton("⚙️ АВТО-СТОК", callback_data="menu_settings"),
                InlineKeyboardButton("📦 СТОК", callback_data="menu_stock")
            ],
            [
                InlineKeyboardButton("🔔 УВЕДОМЛЕНИЯ", callback_data="notifications_on"),
                InlineKeyboardButton("🔕 УВЕДОМЛЕНИЯ", callback_data="notifications_off")
            ]
        ]
        
        # Добавляем кнопку админ-панели для админа
        settings = self.user_manager.get_user(update.effective_user.id)
        if settings.is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        # Убираем реплай клавиатуру
        reply_markup_remove = ReplyKeyboardMarkup([[]], resize_keyboard=True)
        await update.message.reply_text("🔄 Обновляю меню...", reply_markup=reply_markup_remove)
        
        await update.message.reply_photo(
            photo=IMAGE_MAIN,
            caption=MAIN_MENU_TEXT,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_main_menu_callback(self, query):
        user = query.from_user
        settings = self.user_manager.get_user(user.id)
        
        keyboard = [
            [
                InlineKeyboardButton("⚙️ АВТО-СТОК", callback_data="menu_settings"),
                InlineKeyboardButton("📦 СТОК", callback_data="menu_stock")
            ],
            [
                InlineKeyboardButton("🔔 УВЕДОМЛЕНИЯ", callback_data="notifications_on"),
                InlineKeyboardButton("🔕 УВЕДОМЛЕНИЯ", callback_data="notifications_off")
            ]
        ]
        
        # Добавляем кнопку админ-панели для админа
        if settings.is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        # Убираем реплай клавиатуру
        reply_markup_remove = ReplyKeyboardMarkup([[]], resize_keyboard=True)
        await query.message.reply_text("🔄 Возвращаю главное меню...", reply_markup=reply_markup_remove)
        
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=IMAGE_MAIN,
                caption=MAIN_MENU_TEXT,
                parse_mode='HTML'
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_main_settings(self, update: Update, settings: UserSettings):
        status = "🔔 ВКЛ" if settings.notifications_enabled else "🔕 ВЫКЛ"
        text = f"<b>⚙️ АВТО-СТОК</b>\n\n<b>Уведомления: {status}</b>\n\nВыберите категорию:"
        
        keyboard = [
            [
                InlineKeyboardButton("🌱 СЕМЕНА", callback_data="settings_seeds"),
                InlineKeyboardButton("⚙️ СНАРЯЖЕНИЕ", callback_data="settings_gear")
            ],
            [
                InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather"),
                InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")
            ]
        ]
        
        await update.message.reply_photo(
            photo=IMAGE_MAIN,
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_main_settings_callback(self, query, settings: UserSettings):
        status = "🔔 ВКЛ" if settings.notifications_enabled else "🔕 ВЫКЛ"
        text = f"<b>⚙️ АВТО-СТОК</b>\n\n<b>Уведомления: {status}</b>\n\nВыберите категорию:"
        
        keyboard = [
            [
                InlineKeyboardButton("🌱 СЕМЕНА", callback_data="settings_seeds"),
                InlineKeyboardButton("⚙️ СНАРЯЖЕНИЕ", callback_data="settings_gear")
            ],
            [
                InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather"),
                InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")
            ]
        ]
        
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=IMAGE_MAIN,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_seeds_settings(self, query, settings: UserSettings):
        text = "<b>🌱 НАСТРОЙКИ СЕМЯН</b>\n\nНажмите на семя:"
        
        keyboard = []
        row = []
        
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
            media=InputMediaPhoto(
                media=IMAGE_SEEDS,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_gear_settings(self, query, settings: UserSettings):
        text = "<b>⚙️ НАСТРОЙКИ СНАРЯЖЕНИЯ</b>\n\nНажмите на предмет:"
        
        keyboard = []
        row = []
        
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
            media=InputMediaPhoto(
                media=IMAGE_GEAR,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_weather_settings(self, query, settings: UserSettings):
        text = "<b>🌤️ НАСТРОЙКИ ПОГОДЫ</b>\n\nНажмите на погоду:"
        
        keyboard = []
        row = []
        
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
            media=InputMediaPhoto(
                media=IMAGE_WEATHER,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_seed_callback(self, query, settings: UserSettings):
        parts = query.data.split("_")
        if len(parts) >= 3:
            seed_name = "_".join(parts[2:])
            settings.seeds[seed_name].enabled = not settings.seeds[seed_name].enabled
            self.user_manager.save_users()
            await self.show_seeds_settings(query, settings)
    
    async def handle_gear_callback(self, query, settings: UserSettings):
        parts = query.data.split("_")
        if len(parts) >= 3:
            gear_name = "_".join(parts[2:])
            settings.gear[gear_name].enabled = not settings.gear[gear_name].enabled
            self.user_manager.save_users()
            await self.show_gear_settings(query, settings)
    
    async def handle_weather_callback(self, query, settings: UserSettings):
        parts = query.data.split("_")
        if len(parts) >= 3:
            weather_name = "_".join(parts[2:])
            settings.weather[weather_name].enabled = not settings.weather[weather_name].enabled
            self.user_manager.save_users()
            await self.show_weather_settings(query, settings)
    
    async def show_stock_callback(self, query):
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=IMAGE_MAIN,
                caption="<b>🔍 Получаю данные...</b>",
                parse_mode='HTML'
            )
        )
        
        data = self.fetch_api_data(force=True)
        if not data:
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=IMAGE_MAIN,
                    caption="<b>❌ Ошибка</b>",
                    parse_mode='HTML'
                )
            )
            return
        
        message = self.format_stock_message(data)
        if message:
            keyboard = [[InlineKeyboardButton("🏠 ГЛАВНОЕ МЕНЮ", callback_data="menu_main")]]
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=IMAGE_MAIN,
                    caption=message,
                    parse_mode='HTML'
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
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
                
                seeds = data["data"].get("seeds", [])
                if seeds:
                    seeds_in_stock = [(s['name'], s['quantity']) for s in seeds if s['quantity'] > 0]
                    logger.info(f"🌱 Семена в стоке: {seeds_in_stock}")
                
                gear = data["data"].get("gear", [])
                if gear:
                    gear_in_stock = [(g['name'], g['quantity']) for g in gear if g['quantity'] > 0]
                    logger.info(f"⚙️ Снаряжение в стоке: {gear_in_stock}")
                
                return data["data"]
            
            logger.warning("⚠️ Неожиданная структура ответа API")
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
    
    def format_channel_message(self, item_name: str, quantity: int, channel_link: str = None) -> str:
        translated = translate(item_name)
        link = channel_link or REQUIRED_CHANNEL_LINK
        
        return (
            f"✨ <b>{translated}</b>\n"
            f"<b>Количество:</b> {quantity} шт.\n"
            f"━━━━━━━━━━━━━━\n"
            f"<a href='{link}'>Наш канал</a> | <a href='{BOT_LINK}'>Авто-сток</a> | <a href='{CHAT_LINK}'>Наш чат</a>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👀 Включи уведомления в канале!"
        )
    
    def format_pm_message(self, new_items: List[tuple]) -> str:
        if not new_items:
            return None
        
        message = "<b>🔔 ОБНОВЛЕНИЕ СТОКА</b>\n\n"
        
        for item_name, diff in new_items:
            translated = translate(item_name)
            if diff > 0:
                message += f"<b>Появился:</b> {translated} +{diff}\n"
            else:
                message += f"<b>Уменьшился:</b> {translated} {diff}\n"
        
        return message
    
    def get_all_changes(self, old_data: Dict, new_data: Dict) -> Dict[str, int]:
        changes = defaultdict(int)
        processed = set()
        
        if "seeds" in new_data:
            old_seeds = {s["name"]: s["quantity"] for s in old_data.get("seeds", [])}
            new_seeds = {s["name"]: s["quantity"] for s in new_data["seeds"]}
            
            all_names = set(old_seeds.keys()) | set(new_seeds.keys())
            
            for name in all_names:
                if name in processed:
                    continue
                    
                if name not in TRANSLATIONS:
                    continue
                
                old_q = old_seeds.get(name, 0)
                new_q = new_seeds.get(name, 0)
                
                if old_q != new_q:
                    diff = new_q - old_q
                    changes[name] = diff
                    processed.add(name)
                    self.last_seen_items[name] = new_q
        
        if "gear" in new_data:
            old_gear = {g["name"]: g["quantity"] for g in old_data.get("gear", [])}
            new_gear = {g["name"]: g["quantity"] for g in new_data["gear"]}
            
            all_names = set(old_gear.keys()) | set(new_gear.keys())
            
            for name in all_names:
                if name in processed:
                    continue
                    
                if name not in TRANSLATIONS:
                    continue
                
                old_q = old_gear.get(name, 0)
                new_q = new_gear.get(name, 0)
                
                if old_q != new_q:
                    diff = new_q - old_q
                    changes[name] = diff
                    processed.add(name)
                    self.last_seen_items[name] = new_q
        
        if "weather" in new_data:
            old_weather = old_data.get("weather", {})
            new_weather = new_data["weather"]
            
            wtype = new_weather.get("type")
            if wtype and wtype not in processed and wtype in TRANSLATIONS:
                if new_weather.get("active") and not old_weather.get("active"):
                    changes[wtype] = 1
                    processed.add(wtype)
        
        return dict(changes)
    
    def get_user_changes(self, all_changes: Dict[str, int], settings: UserSettings) -> List[tuple]:
        user_items = []
        
        for name, diff in all_changes.items():
            if name in SEEDS_LIST:
                if name in settings.seeds and settings.seeds[name].enabled:
                    user_items.append((name, diff))
            elif name in GEAR_LIST:
                if name in settings.gear and settings.gear[name].enabled:
                    user_items.append((name, diff))
            elif name in WEATHER_LIST:
                if name in settings.weather and settings.weather[name].enabled:
                    user_items.append((name, diff))
        
        return user_items
    
    async def monitor_loop(self):
        logger.info("🚀 Запущен цикл мониторинга API (интервал 5 секунд)")
        
        additional_channels = []
        if os.path.exists(CHANNELS_FILE):
            with open(CHANNELS_FILE, 'r') as f:
                additional_channels = json.load(f)
        
        while True:
            try:
                start_time = datetime.now()
                logger.info("🔄 Быстрая проверка API...")
                new_data = self.fetch_api_data(force=True)
                
                if new_data:
                    logger.info(f"📊 Текущие данные: {new_data.get('lastGlobalUpdate')}")
                
                if new_data and self.last_data:
                    all_changes = self.get_all_changes(self.last_data, new_data)
                    
                    if all_changes:
                        logger.info(f"✅ Обнаружены изменения: {all_changes}")
                        
                        # Для основного канала
                        main_channel_changes = {}
                        for name, diff in all_changes.items():
                            if is_allowed_for_main_channel(name):
                                current_qty = 0
                                for item in new_data.get("seeds", []):
                                    if item["name"] == name:
                                        current_qty = item["quantity"]
                                        break
                                main_channel_changes[name] = current_qty
                        
                        # Отправляем в ОСНОВНОЙ канал
                        if MAIN_CHANNEL_ID and main_channel_changes:
                            logger.info(f"📢 Отправка {len(main_channel_changes)} в основной канал")
                            
                            for name, qty in main_channel_changes.items():
                                channel_message = self.format_channel_message(name, qty)
                                try:
                                    await self.message_queue.queue.put((
                                        int(MAIN_CHANNEL_ID),
                                        channel_message,
                                        'HTML',
                                        None
                                    ))
                                    logger.info(f"✅ В основной канал: {name} x{qty}")
                                except Exception as e:
                                    logger.error(f"❌ Ошибка основного канала: {e}")
                        
                        # Отправляем в дополнительные каналы
                        if additional_channels:
                            for channel_id in additional_channels:
                                try:
                                    for name, qty in main_channel_changes.items():
                                        channel_message = self.format_channel_message(name, qty)
                                        await self.message_queue.queue.put((
                                            int(channel_id),
                                            channel_message,
                                            'HTML',
                                            None
                                        ))
                                    logger.info(f"✅ В доп. канал {channel_id}")
                                except Exception as e:
                                    logger.error(f"❌ Ошибка доп. канала {channel_id}: {e}")
                        
                        # Отправляем пользователям
                        notifications_sent = 0
                        for user_id, settings in self.user_manager.users.items():
                            if settings.notifications_enabled:
                                is_subscribed = await self.check_subscription(user_id)
                                
                                if is_subscribed and can_send_notification(user_id):
                                    user_changes = self.get_user_changes(all_changes, settings)
                                    
                                    if user_changes:
                                        pm_message = self.format_pm_message(user_changes)
                                        if pm_message:
                                            try:
                                                await self.message_queue.queue.put((
                                                    user_id,
                                                    pm_message,
                                                    'HTML',
                                                    None
                                                ))
                                                notifications_sent += 1
                                                update_last_notification(user_id)
                                                logger.info(f"✅ Уведомление {user_id}: {user_changes}")
                                            except Exception as e:
                                                logger.error(f"❌ Ошибка {user_id}: {e}")
                        
                        if notifications_sent > 0:
                            logger.info(f"📨 Отправлено уведомлений: {notifications_sent}")
                        
                        self.last_data = new_data
                    
                elif new_data and not self.last_data:
                    self.last_data = new_data
                    logger.info(f"✅ Первые данные: {new_data.get('lastGlobalUpdate')}")
                
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(1, UPDATE_INTERVAL - elapsed)  # Минимум 1 секунда
                logger.info(f"⏱️ Следующая проверка через {sleep_time} сек")
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
        logger.info(f"⏱️ Интервал: {UPDATE_INTERVAL} сек")
        
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