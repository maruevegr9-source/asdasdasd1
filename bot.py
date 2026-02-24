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
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TimedOut

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
MAIN_CHANNEL_ID = os.getenv("CHANNEL_ID", "-1002808838893")
DEFAULT_REQUIRED_CHANNEL_ID = "-1002808838893"
DEFAULT_REQUIRED_CHANNEL_LINK = "https://t.me/GardenHorizonsStocks"

API_URL = os.getenv("API_URL", "https://garden-horizons-stock.dawidfc.workers.dev/api/stock")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "10"))  # Увеличил до 10 секунд чтобы не спамить
ADMIN_ID = 8025951500

# Файл для хранения обязательного канала
REQUIRED_CHANNEL_FILE = 'required_channel.json'

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

# Файлы для хранения данных
CHANNELS_FILE = 'channels.json'
USERS_FILE = 'users.json'

# Состояния для ConversationHandler
(
    ADD_CHANNEL_ID, ADD_CHANNEL_NAME,
    ADD_POST_CHANNEL_ID, ADD_POST_CHANNEL_NAME,
    REMOVE_CHANNEL, REMOVE_POST_CHANNEL,
    MAILING_TEXT
) = range(7)

# Главное сообщение
MAIN_MENU_TEXT = (
    "🌱 <b>Привет! Я могу отслеживать стоки в игре Garden Horizons, "
    "и отправлять их тебе, круто да? 🔥</b>\n\n"
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
last_notification_time: Dict[str, datetime] = {}  # Ключ: user_id_item_name
last_sent_items: Dict[str, int] = {}  # Для отслеживания последних отправленных количеств

def translate(text: str) -> str:
    return TRANSLATIONS.get(text, text)

def is_rare(item_name: str) -> bool:
    return item_name in RARE_ITEMS

def is_allowed_for_main_channel(item_name: str) -> bool:
    return item_name in ALLOWED_CHANNEL_ITEMS

def can_send_notification(user_id: int, item_name: str, new_quantity: int) -> bool:
    """Проверка защиты от спама для конкретного предмета"""
    if user_id == ADMIN_ID:
        return True
    
    # Проверяем по времени
    key = f"{user_id}_{item_name}"
    last_time = last_notification_time.get(key)
    if last_time:
        elapsed = (datetime.now() - last_time).total_seconds()
        if elapsed < 60:  # Минимум 60 секунд между уведомлениями
            logger.info(f"⏱️ Спам-защита для {user_id}_{item_name}: {elapsed:.1f} сек")
            return False
    
    # Проверяем, что количество увеличилось
    last_qty = last_sent_items.get(key, 0)
    if new_quantity <= last_qty:
        logger.info(f"📊 Количество не увеличилось: {last_qty} -> {new_quantity}")
        return False
    
    return True

def update_last_notification(user_id: int, item_name: str, quantity: int):
    """Обновление времени и количества последнего уведомления"""
    key = f"{user_id}_{item_name}"
    last_notification_time[key] = datetime.now()
    last_sent_items[key] = quantity
    logger.info(f"✅ Обновлено уведомление для {key}: {quantity}")

def load_required_channel():
    """Загрузка настроек обязательного канала"""
    try:
        if os.path.exists(REQUIRED_CHANNEL_FILE):
            with open(REQUIRED_CHANNEL_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки канала: {e}")
    
    return {
        'id': DEFAULT_REQUIRED_CHANNEL_ID,
        'link': DEFAULT_REQUIRED_CHANNEL_LINK
    }

def save_required_channel(channel_id: str, channel_link: str):
    """Сохранение настроек обязательного канала"""
    data = {
        'id': channel_id,
        'link': channel_link
    }
    with open(REQUIRED_CHANNEL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Обязательный канал сохранен: {channel_id}")

def load_channels():
    """Загрузка списка каналов для постинга"""
    try:
        if os.path.exists(CHANNELS_FILE):
            with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки каналов: {e}")
    return []

def save_channels(channels: list):
    """Сохранение списка каналов для постинга"""
    with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Каналы сохранены: {len(channels)}")

def load_users():
    """Загрузка списка пользователей"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки пользователей: {e}")
    return []

def save_users(users: list):
    """Сохранение списка пользователей"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Пользователи сохранены: {len(users)}")

def add_user(user_id: int, username: str = ""):
    """Добавление пользователя в базу"""
    users = load_users()
    user_data = {
        'user_id': user_id,
        'username': username,
        'first_seen': datetime.now().isoformat(),
        'notifications_enabled': True,
        'seeds': {seed: True for seed in SEEDS_LIST},
        'gear': {gear: True for gear in GEAR_LIST},
        'weather': {weather: True for weather in WEATHER_LIST}
    }
    
    for i, u in enumerate(users):
        if u['user_id'] == user_id:
            users[i] = user_data
            save_users(users)
            return
    
    users.append(user_data)
    save_users(users)

def get_user_settings(user_id: int) -> Optional[Dict]:
    """Получение настроек пользователя"""
    users = load_users()
    for u in users:
        if u['user_id'] == user_id:
            return u
    return None

def update_user_settings(user_id: int, updates: Dict):
    """Обновление настроек пользователя"""
    users = load_users()
    for i, u in enumerate(users):
        if u['user_id'] == user_id:
            users[i].update(updates)
            save_users(users)
            return True
    return False

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
        self.last_seen_items: Dict[str, int] = {}
        self.mailing_text: Optional[str] = None
        self.mailing_target: Optional[str] = None
        self.required_channel = load_required_channel()
        self.posting_channels = load_channels()
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
    
    def setup_conversation_handlers(self):
        """Настройка обработчиков диалогов"""
        # Добавление канала для постинга
        add_post_channel_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.add_post_channel_start, pattern="^add_post_channel$")],
            states={
                ADD_POST_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_post_channel_id)],
                ADD_POST_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_post_channel_name)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        
        # Удаление канала из постинга
        remove_post_channel_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.remove_post_channel_start, pattern="^remove_post_channel$")],
            states={
                REMOVE_POST_CHANNEL: [CallbackQueryHandler(self.remove_post_channel_confirm, pattern="^del_post_channel_")],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        
        # Рассылка
        mailing_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.mailing_start, pattern="^mailing$")],
            states={
                MAILING_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.mailing_text)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        
        self.application.add_handler(add_post_channel_conv)
        self.application.add_handler(remove_post_channel_conv)
        self.application.add_handler(mailing_conv)
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена действия"""
        await update.message.reply_text("❌ Действие отменено")
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def add_post_channel_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало добавления канала для постинга"""
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.edit_message_text("❌ У вас нет прав!")
            return ConversationHandler.END
        
        await query.edit_message_text(
            "📢 <b>Добавление канала для постинга стоков</b>\n\n"
            "Отправьте ID канала (например: -1001234567890) или username (@channel):",
            parse_mode='HTML'
        )
        return ADD_POST_CHANNEL_ID
    
    async def add_post_channel_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение ID канала для постинга"""
        channel_id = update.message.text.strip()
        context.user_data['post_channel_id'] = channel_id
        
        await update.message.reply_text(
            "✏️ Теперь отправьте название канала (для отображения):"
        )
        return ADD_POST_CHANNEL_NAME
    
    async def add_post_channel_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение названия канала для постинга и сохранение"""
        channel_name = update.message.text.strip()
        channel_id = context.user_data.get('post_channel_id')
        
        try:
            # Проверяем существование канала
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
            
            # Добавляем в список каналов для постинга
            self.posting_channels.append({
                'id': str(chat.id),
                'name': channel_name,
                'username': chat.username
            })
            save_channels(self.posting_channels)
            
            await update.message.reply_text(
                f"✅ Канал <b>{channel_name}</b> добавлен для постинга стоков!",
                parse_mode='HTML'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    async def remove_post_channel_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало удаления канала из постинга"""
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.edit_message_text("❌ У вас нет прав!")
            return ConversationHandler.END
        
        if not self.posting_channels:
            await query.edit_message_text("📭 Нет каналов для удаления")
            await self.show_admin_panel_callback(query)
            return ConversationHandler.END
        
        keyboard = []
        for ch in self.posting_channels:
            keyboard.append([InlineKeyboardButton(
                f"❌ {ch['name']}",
                callback_data=f"del_post_channel_{ch['id']}"
            )])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")])
        
        await query.edit_message_text(
            "🗑 <b>Выберите канал для удаления из постинга:</b>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REMOVE_POST_CHANNEL
    
    async def remove_post_channel_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение удаления канала из постинга"""
        query = update.callback_query
        await query.answer()
        
        channel_id = query.data.replace('del_post_channel_', '')
        
        # Удаляем из списка
        self.posting_channels = [ch for ch in self.posting_channels if ch['id'] != channel_id]
        save_channels(self.posting_channels)
        
        await query.edit_message_text("✅ Канал удален из списка постинга!")
        await self.show_admin_panel_callback(query)
        return ConversationHandler.END
    
    async def mailing_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало рассылки"""
        query = update.callback_query
        await query.answer()
        
        if query.from_user.id != ADMIN_ID:
            await query.edit_message_text("❌ У вас нет прав!")
            return ConversationHandler.END
        
        await query.edit_message_text(
            "📧 <b>Рассылка</b>\n\n"
            "Отправьте текст для рассылки всем пользователям:",
            parse_mode='HTML'
        )
        return MAILING_TEXT
    
    async def mailing_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение текста рассылки и отправка"""
        text = update.message.text
        
        await update.message.reply_text("📧 Начинаю рассылку...")
        
        success = 0
        failed = 0
        failed_users = []
        
        for user_id in self.user_manager.get_all_users():
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
                failed_users.append(user_id)
                logger.error(f"Ошибка отправки {user_id}: {e}")
        
        report = (
            f"<b>📊 ОТЧЕТ О РАССЫЛКЕ</b>\n\n"
            f"✅ Успешно: {success}\n"
            f"❌ Ошибок: {failed}\n"
            f"👥 Всего: {len(self.user_manager.users)}"
        )
        
        if failed_users and len(failed_users) <= 10:
            report += f"\n\n❌ Не удалось отправить:\n"
            for uid in failed_users:
                report += f"• {uid}\n"
        
        await update.message.reply_text(report, parse_mode='HTML')
        
        await self.show_admin_panel(update)
        return ConversationHandler.END
    
    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("stock", self.cmd_stock))
        self.application.add_handler(CommandHandler("notifications_on", self.cmd_notifications_on))
        self.application.add_handler(CommandHandler("notifications_off", self.cmd_notifications_off))
        self.application.add_handler(CommandHandler("menu", self.cmd_menu))
        self.application.add_handler(CommandHandler("admin", self.cmd_admin))  # Быстрый доступ к админке
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Быстрый доступ к админ-панели"""
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if not settings.is_admin:
            await update.message.reply_text("❌ У вас нет прав!")
            return
        
        await self.show_admin_panel(update)
    
    async def check_subscription(self, user_id: int) -> bool:
        """Проверка подписки пользователя на обязательный канал"""
        try:
            channel_id = self.required_channel['id']
            if not channel_id:
                logger.error("Channel ID не задан!")
                return True
            
            member = await self.application.bot.get_chat_member(
                chat_id=int(channel_id),
                user_id=user_id
            )
            
            valid_statuses = [
                ChatMember.MEMBER,
                ChatMember.OWNER,
                ChatMember.ADMINISTRATOR,
                ChatMember.RESTRICTED
            ]
            
            is_subscribed = member.status in valid_statuses
            
            return is_subscribed
            
        except Exception as e:
            logger.error(f"❌ Ошибка проверки подписки {user_id}: {e}")
            return True
    
    async def require_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Проверка подписки с обработкой"""
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if settings.is_admin:
            return True
        
        is_subscribed = await self.check_subscription(user.id)
        
        if not is_subscribed:
            text = (
                "🌱 <b>Привет! Я могу отслеживать стоки в игре, "
                "и отправлять их тебе, круто да? 🔥</b>\n\n"
                "❌ <b>Для использования бота необходимо подписаться на наш канал:</b>\n"
                f"{self.required_channel['link']}\n\n"
                "После подписки нажми кнопку ниже 👇"
            )
            
            keyboard = [
                [InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=self.required_channel['link'])],
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
        
        add_user(user.id, user.username or user.first_name)
        return True
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        settings = self.user_manager.get_user(user.id, user.username or user.first_name)
        
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
    
    async def show_admin_panel(self, update: Update):
        """Показ админ-панели"""
        keyboard = [
            [
                InlineKeyboardButton("📧 Рассылка", callback_data="mailing"),
                InlineKeyboardButton("📊 Статистика", callback_data="bot_stats")
            ],
            [
                InlineKeyboardButton("➕ Добавить канал", callback_data="add_post_channel"),
                InlineKeyboardButton("🗑 Удалить канал", callback_data="remove_post_channel")
            ],
            [
                InlineKeyboardButton("📢 Список каналов", callback_data="post_channels_list"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main")
            ]
        ]
        
        text = (
            "<b>👑 АДМИН-ПАНЕЛЬ</b>\n\n"
            f"👥 Пользователей: {len(self.user_manager.users)}\n"
            f"📢 Каналов для постинга: {len(self.posting_channels)}"
        )
        
        if update.message:
            await update.message.reply_text(
                text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.edit_message_text(
                text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def show_admin_panel_callback(self, query):
        """Показ админ-панели из callback"""
        keyboard = [
            [
                InlineKeyboardButton("📧 Рассылка", callback_data="mailing"),
                InlineKeyboardButton("📊 Статистика", callback_data="bot_stats")
            ],
            [
                InlineKeyboardButton("➕ Добавить канал", callback_data="add_post_channel"),
                InlineKeyboardButton("🗑 Удалить канал", callback_data="remove_post_channel")
            ],
            [
                InlineKeyboardButton("📢 Список каналов", callback_data="post_channels_list"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main")
            ]
        ]
        
        text = (
            "<b>👑 АДМИН-ПАНЕЛЬ</b>\n\n"
            f"👥 Пользователей: {len(self.user_manager.users)}\n"
            f"📢 Каналов для постинга: {len(self.posting_channels)}"
        )
        
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        text = update.message.text
        
        if not settings.is_admin:
            return
        
        if text == "🏠 ГЛАВНОЕ МЕНЮ":
            reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await update.message.reply_text("🔄 Возвращаюсь в главное меню...", reply_markup=reply_markup)
            await self.show_main_menu(update)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        if query.data == "check_subscription":
            is_subscribed = await self.check_subscription(user.id)
            
            if is_subscribed:
                add_user(user.id, user.username or user.first_name)
                
                reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
                await query.message.reply_text("🔄 Подписка подтверждена!", reply_markup=reply_markup)
                await self.show_main_menu_callback(query)
            else:
                text = (
                    "❌ <b>Вы еще не подписались!</b>\n\n"
                    f"Подпишитесь на канал {self.required_channel['link']} и нажмите кнопку еще раз."
                )
                keyboard = [
                    [InlineKeyboardButton("📢 ПОДПИСАТЬСЯ", url=self.required_channel['link'])],
                    [InlineKeyboardButton("✅ ПРОВЕРИТЬ СНОВА", callback_data="check_subscription")]
                ]
                await query.edit_message_media(
                    media=InputMediaPhoto(media=IMAGE_MAIN, caption=text, parse_mode='HTML'),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return
        
        if query.data == "admin_panel":
            if not settings.is_admin:
                await query.edit_message_caption(
                    caption="❌ <b>У вас нет прав доступа!</b>",
                    parse_mode='HTML'
                )
                return
            
            await self.show_admin_panel_callback(query)
            return
        
        if query.data == "bot_stats":
            if not settings.is_admin:
                return
            
            stats_text = (
                "<b>📊 СТАТИСТИКА БОТА</b>\n\n"
                f"👥 Всего пользователей: {len(self.user_manager.users)}\n"
                f"📢 Каналов для постинга: {len(self.posting_channels)}\n"
                f"🔐 Обязательный канал: {self.required_channel['link']}\n"
                f"⏱️ Интервал проверки: {UPDATE_INTERVAL} сек"
            )
            
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await query.edit_message_text(
                stats_text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        if query.data == "post_channels_list":
            if not settings.is_admin:
                return
            
            if not self.posting_channels:
                text = "📭 Нет добавленных каналов для постинга"
            else:
                text = "<b>📢 КАНАЛЫ ДЛЯ ПОСТИНГА</b>\n\n"
                for ch in self.posting_channels:
                    text += f"• {ch['name']} (ID: {ch['id']})\n"
            
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]
            await query.edit_message_text(
                text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        if not await self.require_subscription(update, context):
            return
        
        if query.data == "menu_main":
            reply_markup = ReplyKeyboardMarkup([[]], resize_keyboard=True)
            await query.message.reply_text("🔄 Возвращаюсь в главное меню...", reply_markup=reply_markup)
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
        text = MAIN_MENU_TEXT + f"\n\n<b>Обязательный канал:</b> {self.required_channel['link']}"
        
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
        
        settings = self.user_manager.get_user(update.effective_user.id)
        if settings.is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        reply_markup_remove = ReplyKeyboardMarkup([[]], resize_keyboard=True)
        await update.message.reply_text("🔄 Обновляю меню...", reply_markup=reply_markup_remove)
        
        await update.message.reply_photo(
            photo=IMAGE_MAIN,
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_main_menu_callback(self, query):
        user = query.from_user
        settings = self.user_manager.get_user(user.id)
        
        text = MAIN_MENU_TEXT + f"\n\n<b>Обязательный канал:</b> {self.required_channel['link']}"
        
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
        
        if settings.is_admin:
            keyboard.append([InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin_panel")])
        
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=IMAGE_MAIN,
                caption=text,
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
        link = channel_link or self.required_channel['link']
        
        return (
            f"✨ <b>{translated}</b>\n"
            f"<b>Количество:</b> {quantity} шт.\n"
            f"━━━━━━━━━━━━━━\n"
            f"<a href='{link}'>Наш канал</a> | <a href='{BOT_LINK}'>Авто-сток</a> | <a href='{CHAT_LINK}'>Наш чат</a>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👀 Включи уведомления в канале!"
        )
    
    def format_pm_message(self, new_items: List[tuple]) -> str:
        """Форматирование сообщения для лички - ТОЛЬКО УВЕЛИЧЕНИЕ"""
        if not new_items:
            return None
        
        message = "<b>🔔 НОВЫЕ ПРЕДМЕТЫ В СТОКЕ</b>\n\n"
        
        for item_name, diff in new_items:
            translated = translate(item_name)
            if diff > 0:
                message += f"<b>Появился:</b> {translated} +{diff}\n"
        
        return message
    
    def get_all_changes(self, old_data: Dict, new_data: Dict) -> Dict[str, int]:
        """Получить изменения - ТОЛЬКО УВЕЛИЧЕНИЕ"""
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
                
                # ТОЛЬКО если количество УВЕЛИЧИЛОСЬ
                if new_q > old_q:
                    diff = new_q - old_q
                    changes[name] = diff
                    logger.info(f"✅ {name} увеличилось: {old_q} → {new_q} (+{diff})")
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
                
                if new_q > old_q:
                    diff = new_q - old_q
                    changes[name] = diff
                    logger.info(f"✅ {name} увеличилось: {old_q} → {new_q} (+{diff})")
                    processed.add(name)
                    self.last_seen_items[name] = new_q
        
        if "weather" in new_data:
            old_weather = old_data.get("weather", {})
            new_weather = new_data["weather"]
            
            wtype = new_weather.get("type")
            if wtype and wtype not in processed and wtype in TRANSLATIONS:
                if new_weather.get("active") and not old_weather.get("active"):
                    changes[wtype] = 1
                    logger.info(f"✅ {wtype} началась")
                    processed.add(wtype)
        
        return dict(changes)
    
    def get_user_changes(self, all_changes: Dict[str, int], settings: UserSettings) -> List[tuple]:
        """Фильтруем изменения по настройкам пользователя - ТОЛЬКО УВЕЛИЧЕНИЕ"""
        user_items = []
        
        for name, diff in all_changes.items():
            if diff <= 0:  # Пропускаем уменьшение
                continue
                
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
        logger.info("🚀 Запущен цикл мониторинга API (интервал 10 секунд)")
        
        while True:
            try:
                start_time = datetime.now()
                logger.info("🔄 Проверка API...")
                new_data = self.fetch_api_data(force=True)
                
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
                        if self.posting_channels:
                            for channel in self.posting_channels:
                                try:
                                    for name, qty in main_channel_changes.items():
                                        channel_message = self.format_channel_message(name, qty)
                                        await self.message_queue.queue.put((
                                            int(channel['id']),
                                            channel_message,
                                            'HTML',
                                            None
                                        ))
                                    logger.info(f"✅ В канал {channel['name']}")
                                except Exception as e:
                                    logger.error(f"❌ Ошибка канала {channel['id']}: {e}")
                        
                        # Отправляем пользователям - ТОЛЬКО УВЕЛИЧЕНИЕ
                        notifications_sent = 0
                        for user_id, settings in self.user_manager.users.items():
                            if settings.notifications_enabled:
                                is_subscribed = await self.check_subscription(user_id)
                                
                                if is_subscribed:
                                    user_changes = self.get_user_changes(all_changes, settings)
                                    
                                    if user_changes:
                                        for name, diff in user_changes:
                                            new_q = 0
                                            for item in new_data.get("seeds", []):
                                                if item["name"] == name:
                                                    new_q = item["quantity"]
                                                    break
                                            
                                            if can_send_notification(user_id, name, new_q):
                                                pm_message = self.format_pm_message([(name, diff)])
                                                if pm_message:
                                                    try:
                                                        await self.message_queue.queue.put((
                                                            user_id,
                                                            pm_message,
                                                            'HTML',
                                                            None
                                                        ))
                                                        notifications_sent += 1
                                                        update_last_notification(user_id, name, new_q)
                                                        logger.info(f"✅ Уведомление {user_id}: {name} +{diff}")
                                                    except Exception as e:
                                                        logger.error(f"❌ Ошибка {user_id}: {e}")
                        
                        if notifications_sent > 0:
                            logger.info(f"📨 Отправлено уведомлений: {notifications_sent}")
                        
                        self.last_data = new_data
                    
                elif new_data and not self.last_data:
                    self.last_data = new_data
                    logger.info(f"✅ Первые данные: {new_data.get('lastGlobalUpdate')}")
                
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(5, UPDATE_INTERVAL - elapsed)  # Минимум 5 секунд
                logger.info(f"⏱️ Следующая проверка через {sleep_time:.1f} сек")
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