import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import defaultdict

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

# Загружаем переменные окружения
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = "-1002808838893"  # НОВЫЙ ID канала
API_URL = os.getenv("API_URL", "https://garden-horizons-stock.dawidfc.workers.dev/api/stock")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "15"))
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

# Ссылки
CHANNEL_LINK = "https://t.me/GardenHorizonsStocks"
BOT_LINK = "https://t.me/GardenHorizons_StocksBot"
CHAT_LINK = "https://t.me/GardenHorizons_Trade"

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

# Список РАЗРЕШЕННЫХ растений для канала (ТОЛЬКО ЭТИ ТРИ!)
ALLOWED_CHANNEL_ITEMS = ["Potato", "Cabbage", "Cherry"]

# Списки для удобства
SEEDS_LIST = ["Carrot", "Corn", "Onion", "Strawberry", "Mushroom", "Beetroot", "Tomato", "Apple", "Rose", "Wheat", "Banana", "Plum", "Potato", "Cabbage", "Cherry"]
GEAR_LIST = ["Watering Can", "Basic Sprinkler", "Harvest Bell", "Turbo Sprinkler", "Favorite Tool", "Super Sprinkler"]
WEATHER_LIST = ["fog", "rain", "snow", "storm", "sandstorm", "starfall"]

# Редкие предметы
RARE_ITEMS = ["Super Sprinkler", "Favorite Tool", "starfall"]

def translate(text: str) -> str:
    """Перевод текста на русский"""
    return TRANSLATIONS.get(text, text)

def is_rare(item_name: str) -> bool:
    """Проверка, является ли предмет редким"""
    return item_name in RARE_ITEMS

def is_allowed_for_channel(item_name: str) -> bool:
    """Проверка, разрешен ли предмет для отправки в канал"""
    return item_name in ALLOWED_CHANNEL_ITEMS

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

class GardenHorizonsBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.user_manager = UserManager()
        self.last_data: Optional[Dict] = None
        self.mailing_text: Optional[str] = None
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
        self.application.add_handler(CommandHandler("testapi", self.cmd_test_api))  # Новая тестовая команда
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
    
    async def check_subscription(self, user_id: int) -> bool:
        """Проверка подписки ТОЛЬКО по числовому ID канала"""
        try:
            if not CHANNEL_ID:
                logger.error("CHANNEL_ID не задан!")
                return False
            
            member = await self.application.bot.get_chat_member(
                chat_id=int(CHANNEL_ID),
                user_id=user_id
            )
            
            valid_statuses = [
                ChatMember.MEMBER,
                ChatMember.OWNER,
                ChatMember.ADMINISTRATOR,
                ChatMember.RESTRICTED
            ]
            
            is_subscribed = member.status in valid_statuses
            logger.info(f"Проверка подписки {user_id}: {member.status} -> {is_subscribed}")
            
            return is_subscribed
            
        except Exception as e:
            logger.error(f"❌ Ошибка проверки подписки {user_id}: {e}")
            return False
    
    async def require_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Универсальная проверка подписки"""
        user = update.effective_user
        
        is_subscribed = await self.check_subscription(user.id)
        
        if not is_subscribed:
            text = (
                "🌱 <b>Добро пожаловать в Garden Horizons Stock Bot!</b> 🌱\n\n"
                "❌ <b>Для использования бота необходимо подписаться на наш канал:</b>\n"
                f"{CHANNEL_LINK}\n\n"
                "После подписки нажми кнопку ниже 👇"
            )
            
            keyboard = [
                [InlineKeyboardButton("📢 ПОДПИСАТЬСЯ НА КАНАЛ", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_subscription")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_html(text, reply_markup=reply_markup)
            elif update.callback_query:
                await update.callback_query.edit_message_text(
                    text=text,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            
            return False
        
        return True
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        self.user_manager.get_user(user.id, user.username or user.first_name)
        
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
            keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_main")]]
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
        
        if user.id != ADMIN_ID:
            await update.message.reply_html("<b>❌ У вас нет прав!</b>")
            return
        
        if not context.args:
            await update.message.reply_html(
                "<b>📧 РАССЫЛКА</b>\n\n"
                "Использование: /mailing текст"
            )
            return
        
        self.mailing_text = " ".join(context.args)
        
        text = (
            f"<b>📧 ПОДТВЕРЖДЕНИЕ РАССЫЛКИ</b>\n\n"
            f"<b>Текст:</b>\n{self.mailing_text}\n\n"
            f"<b>Получателей:</b> {len(self.user_manager.users)}\n\n"
            f"Подтвердите:"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ ПОДТВЕРДИТЬ", callback_data="mailing_confirm"),
                InlineKeyboardButton("❌ ОТМЕНИТЬ", callback_data="mailing_cancel")
            ]
        ]
        
        await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def cmd_test_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тестовая команда для проверки API"""
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_html("<b>❌ Только для админа!</b>")
            return
        
        await update.message.reply_html("<b>🔍 Тестирую API...</b>")
        
        # Запрос без force
        data1 = self.fetch_api_data(force=False)
        
        # Запрос с force
        data2 = self.fetch_api_data(force=True)
        
        # Текущее время сервера
        current_time = datetime.now().isoformat()
        
        msg = (
            f"<b>📊 ТЕСТ API</b>\n\n"
            f"<b>Без force:</b>\n{data1.get('lastGlobalUpdate') if data1 else '❌'}\n\n"
            f"<b>С force:</b>\n{data2.get('lastGlobalUpdate') if data2 else '❌'}\n\n"
            f"<b>Текущее время:</b>\n{current_time}\n\n"
            f"<b>Данные совпадают:</b> "
            f"{'✅ ДА' if data1 and data2 and data1.get('lastGlobalUpdate') == data2.get('lastGlobalUpdate') else '❌ НЕТ'}"
        )
        
        await update.message.reply_html(msg)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        settings = self.user_manager.get_user(user.id)
        
        # Специальные callback без проверки подписки
        if query.data == "check_subscription":
            is_subscribed = await self.check_subscription(user.id)
            
            if is_subscribed:
                await self.show_main_menu_callback(query)
            else:
                await query.edit_message_text(
                    text="❌ <b>Вы еще не подписались!</b>",
                    parse_mode='HTML'
                )
            return
        
        # Все остальные callback требуют подписки
        if not await self.require_subscription(update, context):
            return
        
        if query.data == "mailing_confirm":
            if user.id != ADMIN_ID:
                return
            
            await query.edit_message_text(text="<b>📧 Начинаю рассылку...</b>", parse_mode='HTML')
            
            success = 0
            failed = 0
            failed_users = []
            
            for uid in self.user_manager.get_all_users():
                try:
                    await self.application.bot.send_message(
                        chat_id=uid,
                        text=f"<b>📢 РАССЫЛКА</b>\n\n{self.mailing_text}",
                        parse_mode='HTML'
                    )
                    success += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    failed += 1
                    failed_users.append(uid)
                    logger.error(f"Ошибка {uid}: {e}")
            
            report = (
                f"<b>📊 ОТЧЕТ</b>\n\n"
                f"✅ Успешно: {success}\n"
                f"❌ Ошибок: {failed}\n"
                f"👥 Всего: {len(self.user_manager.users)}"
            )
            
            if failed_users:
                report += f"\n\n❌ Не удалось:\n"
                for uid in failed_users[:10]:
                    report += f"• {uid}\n"
            
            await self.application.bot.send_message(
                chat_id=ADMIN_ID,
                text=report,
                parse_mode='HTML'
            )
            
            self.mailing_text = None
        
        elif query.data == "mailing_cancel":
            self.mailing_text = None
            await query.edit_message_text(text="❌ Отменено", parse_mode='HTML')
        
        elif query.data == "menu_main":
            await self.show_main_menu_callback(query)
        
        elif query.data == "menu_settings":
            await self.show_main_settings_callback(query, settings)
        
        elif query.data == "menu_stock":
            await self.show_stock_callback(query)
        
        elif query.data == "notifications_on":
            settings.notifications_enabled = True
            self.user_manager.save_users()
            await query.edit_message_text(text="<b>✅ Уведомления включены!</b>", parse_mode='HTML')
            await asyncio.sleep(1)
            await self.show_main_menu_callback(query)
        
        elif query.data == "notifications_off":
            settings.notifications_enabled = False
            self.user_manager.save_users()
            await query.edit_message_text(text="<b>✅ Уведомления выключены</b>", parse_mode='HTML')
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
        text = (
            "🌱 <b>Добро пожаловать в Garden Horizons Stock Bot!</b> 🌱\n\n"
            f"<b>Канал</b> - {CHANNEL_LINK}\n"
            f"<b>Чат</b> - {CHAT_LINK}\n\n"
            "Выберите действие:"
        )
        
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
        
        await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_main_menu_callback(self, query):
        text = (
            "🌱 <b>Добро пожаловать в Garden Horizons Stock Bot!</b> 🌱\n\n"
            f"<b>Канал</b> - {CHANNEL_LINK}\n"
            f"<b>Чат</b> - {CHAT_LINK}\n\n"
            "Выберите действие:"
        )
        
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
        
        await query.edit_message_text(
            text=text,
            parse_mode='HTML',
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
                InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather")
            ],
            [InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_main")]
        ]
        
        await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_main_settings_callback(self, query, settings: UserSettings):
        status = "🔔 ВКЛ" if settings.notifications_enabled else "🔕 ВЫКЛ"
        text = f"<b>⚙️ АВТО-СТОК</b>\n\n<b>Уведомления: {status}</b>\n\nВыберите категорию:"
        
        keyboard = [
            [
                InlineKeyboardButton("🌱 СЕМЕНА", callback_data="settings_seeds"),
                InlineKeyboardButton("⚙️ СНАРЯЖЕНИЕ", callback_data="settings_gear")
            ],
            [
                InlineKeyboardButton("🌤️ ПОГОДА", callback_data="settings_weather")
            ],
            [InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_main")]
        ]
        
        await query.edit_message_text(
            text=text,
            parse_mode='HTML',
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
        
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_settings")])
        
        await query.edit_message_text(
            text=text,
            parse_mode='HTML',
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
        
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_settings")])
        
        await query.edit_message_text(
            text=text,
            parse_mode='HTML',
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
        
        keyboard.append([InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_settings")])
        
        await query.edit_message_text(
            text=text,
            parse_mode='HTML',
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
        await query.edit_message_text(text="<b>🔍 Получаю данные...</b>", parse_mode='HTML')
        
        data = self.fetch_api_data(force=True)
        if not data:
            await query.edit_message_text(text="<b>❌ Ошибка</b>", parse_mode='HTML')
            return
        
        message = self.format_stock_message(data)
        if message:
            keyboard = [[InlineKeyboardButton("🔙 НАЗАД", callback_data="menu_main")]]
            await query.edit_message_text(
                text=message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    def fetch_api_data(self, force=False) -> Optional[Dict]:
        """Получение данных из API с подробным логированием и анти-кэш заголовками"""
        try:
            url = API_URL
            if force:
                url = f"{API_URL}?t={int(datetime.now().timestamp())}"
            
            # Заголовки против кэширования
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
                
                # Логируем первые несколько предметов для отладки
                seeds = data["data"].get("seeds", [])
                if seeds:
                    logger.info(f"🌱 Семена в стоке: {[(s['name'], s['quantity']) for s in seeds if s['quantity'] > 0]}")
                
                gear = data["data"].get("gear", [])
                if gear:
                    logger.info(f"⚙️ Снаряжение в стоке: {[(g['name'], g['quantity']) for g in gear if g['quantity'] > 0]}")
                
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
    
    def format_channel_message(self, item_name: str, quantity: int) -> str:
        """Форматирование сообщения для канала"""
        translated = translate(item_name)
        
        return (
            f"✨ <b>{translated}</b>\n"
            f"<b>Количество:</b> {quantity} шт.\n"
            f"━━━━━━━━━━━━━━\n"
            f"<a href='{CHANNEL_LINK}'>Наш канал</a> | <a href='{BOT_LINK}'>Авто-сток</a> | <a href='{CHAT_LINK}'>Наш чат</a>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👀 Включи уведомления в канале!"
        )
    
    def format_pm_message(self, new_items: List[tuple]) -> str:
        """Форматирование сообщения для лички"""
        if not new_items:
            return None
        
        message = "<b>🔔 ОБНОВЛЕНИЕ СТОКА</b>\n\n"
        
        for item_name, quantity in new_items:
            translated = translate(item_name)
            message += f"<b>Появился:</b> {translated} +{quantity}\n"
        
        return message
    
    def get_changed_items(self, old_data: Dict, new_data: Dict) -> Dict[str, int]:
        """
        Получить УНИКАЛЬНЫЕ изменения между старыми и новыми данными
        Возвращает словарь {название: общее_количество}
        """
        changed_items = defaultdict(int)
        processed = set()
        
        # Проверяем семена
        if "seeds" in new_data:
            old_seeds = {s["name"]: s["quantity"] for s in old_data.get("seeds", [])}
            new_seeds = {s["name"]: s["quantity"] for s in new_data["seeds"]}
            
            for name, quantity in new_seeds.items():
                if name in processed:
                    continue
                    
                if name not in TRANSLATIONS:
                    continue
                
                old_q = old_seeds.get(name, 0)
                if old_q != quantity and quantity > 0 and old_q == 0:
                    changed_items[name] += quantity
                    processed.add(name)
        
        # Проверяем снаряжение
        if "gear" in new_data:
            old_gear = {g["name"]: g["quantity"] for g in old_data.get("gear", [])}
            new_gear = {g["name"]: g["quantity"] for g in new_data["gear"]}
            
            for name, quantity in new_gear.items():
                if name in processed:
                    continue
                    
                if name not in TRANSLATIONS:
                    continue
                
                old_q = old_gear.get(name, 0)
                if old_q != quantity and quantity > 0 and old_q == 0:
                    changed_items[name] += quantity
                    processed.add(name)
        
        # Проверяем погоду
        if "weather" in new_data:
            old_weather = old_data.get("weather", {})
            new_weather = new_data["weather"]
            
            wtype = new_weather.get("type")
            if wtype and wtype not in processed and wtype in TRANSLATIONS:
                if new_weather.get("active") and not old_weather.get("active"):
                    changed_items[wtype] += 1
                    processed.add(wtype)
        
        return dict(changed_items)
    
    def get_user_changed_items(self, old_data: Dict, new_data: Dict, settings: UserSettings) -> List[tuple]:
        """
        Получить изменения ТОЛЬКО для конкретного пользователя с учетом его настроек
        """
        user_items = []
        processed = set()
        
        # Проверяем семена
        if "seeds" in new_data:
            old_seeds = {s["name"]: s["quantity"] for s in old_data.get("seeds", [])}
            new_seeds = {s["name"]: s["quantity"] for s in new_data["seeds"]}
            
            for name, quantity in new_seeds.items():
                if name in processed:
                    continue
                    
                if name in settings.seeds and not settings.seeds[name].enabled:
                    continue
                if name not in TRANSLATIONS:
                    continue
                
                old_q = old_seeds.get(name, 0)
                if old_q != quantity and quantity > 0 and old_q == 0:
                    user_items.append((name, quantity))
                    processed.add(name)
        
        # Проверяем снаряжение
        if "gear" in new_data:
            old_gear = {g["name"]: g["quantity"] for g in old_data.get("gear", [])}
            new_gear = {g["name"]: g["quantity"] for g in new_data["gear"]}
            
            for name, quantity in new_gear.items():
                if name in processed:
                    continue
                    
                if name in settings.gear and not settings.gear[name].enabled:
                    continue
                if name not in TRANSLATIONS:
                    continue
                
                old_q = old_gear.get(name, 0)
                if old_q != quantity and quantity > 0 and old_q == 0:
                    user_items.append((name, quantity))
                    processed.add(name)
        
        # Проверяем погоду
        if "weather" in new_data:
            old_weather = old_data.get("weather", {})
            new_weather = new_data["weather"]
            
            wtype = new_weather.get("type")
            if wtype and wtype not in processed and wtype in settings.weather:
                if settings.weather[wtype].enabled:
                    if new_weather.get("active") and not old_weather.get("active"):
                        user_items.append((wtype, 1))
                        processed.add(wtype)
        
        return user_items
    
    async def monitor_loop(self):
        """Основной цикл мониторинга"""
        logger.info("🚀 Запущен цикл мониторинга API")
        
        while True:
            try:
                start_time = datetime.now()
                logger.info("🔄 Проверка API...")
                new_data = self.fetch_api_data(force=True)
                
                if new_data:
                    logger.info(f"📊 Текущие данные: {new_data.get('lastGlobalUpdate')}")
                
                if new_data and self.last_data:
                    # Проверяем, изменились ли данные
                    if new_data.get("lastGlobalUpdate") != self.last_data.get("lastGlobalUpdate"):
                        logger.info(f"✅ Обнаружены изменения: {new_data.get('lastGlobalUpdate')}")
                        
                        # 1. ПОЛУЧАЕМ УНИКАЛЬНЫЕ ИЗМЕНЕНИЯ
                        all_changes = self.get_changed_items(self.last_data, new_data)
                        logger.info(f"📦 Всего изменений: {len(all_changes)}")
                        
                        # 2. ФИЛЬТРУЕМ ТОЛЬКО РАЗРЕШЕННЫЕ ПРЕДМЕТЫ ДЛЯ КАНАЛА
                        channel_changes = {}
                        for name, qty in all_changes.items():
                            if is_allowed_for_channel(name):
                                channel_changes[name] = qty
                        
                        # Отправляем в канал ТОЛЬКО разрешенные предметы
                        if CHANNEL_ID and channel_changes:
                            logger.info(f"📢 Отправка {len(channel_changes)} разрешенных предметов в канал")
                            
                            for name, total_qty in channel_changes.items():
                                channel_message = self.format_channel_message(name, total_qty)
                                try:
                                    await self.application.bot.send_message(
                                        chat_id=int(CHANNEL_ID),
                                        text=channel_message,
                                        parse_mode='HTML',
                                        disable_web_page_preview=True
                                    )
                                    logger.info(f"✅ В канал отправлено: {name} x{total_qty}")
                                    await asyncio.sleep(0.5)
                                except Exception as e:
                                    logger.error(f"❌ Ошибка отправки в канал: {e}")
                        
                        # 3. Отправляем персональные уведомления пользователям (без ограничений)
                        notifications_sent = 0
                        for user_id, settings in self.user_manager.users.items():
                            if settings.notifications_enabled:
                                is_subscribed = await self.check_subscription(user_id)
                                
                                if is_subscribed:
                                    user_changes = self.get_user_changed_items(
                                        self.last_data, new_data, settings
                                    )
                                    
                                    if user_changes:
                                        pm_message = self.format_pm_message(user_changes)
                                        if pm_message:
                                            try:
                                                await self.application.bot.send_message(
                                                    chat_id=user_id,
                                                    text=pm_message,
                                                    parse_mode='HTML'
                                                )
                                                notifications_sent += 1
                                                logger.info(f"✅ Уведомление отправлено {user_id}")
                                                await asyncio.sleep(0.1)
                                            except Exception as e:
                                                logger.error(f"❌ Ошибка отправки {user_id}: {e}")
                        
                        if notifications_sent > 0:
                            logger.info(f"📨 Отправлено уведомлений: {notifications_sent}")
                        
                        self.last_data = new_data
                    
                elif new_data and not self.last_data:
                    # Первый запуск
                    self.last_data = new_data
                    logger.info(f"✅ Получены первые данные: {new_data.get('lastGlobalUpdate')}")
                
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(1, UPDATE_INTERVAL - elapsed)
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
        
        asyncio.create_task(self.monitor_loop())
        
        await self.application.initialize()
        await self.application.start()
        
        logger.info("🤖 Бот запущен")
        logger.info(f"📡 API: {API_URL}")
        logger.info(f"📱 Канал: {CHANNEL_ID}")
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