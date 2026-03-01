import requests
import time
import json
import re

# ===== ТВОИ ДАННЫЕ =====
USER_TOKEN = "MTE5ODI4NDc2NDA0MjUwNjMyMw.Gz2mps.i44drjjzSvDipjLO6UIBpgbjgJMvRKoIvxdurM"
TELEGRAM_TOKEN = "ТВОЙ_ТОКЕН_ТЕЛЕГРАМ"  # ВСТАВЬ СВОЙ
TELEGRAM_CHAT_ID = -1002808898833
GUILD_ID = "1392614350686130198"

# ID каналов Dawn бота
CHANNELS = {
    'seeds': 1474799488689377463,
    'gear': 1474799504401236090,
    'weather': 1474799519706255510
}

headers = {'authorization': USER_TOKEN}
last_messages = {}
role_cache = {}

def get_role_name(role_id):
    """Получает имя роли по ID с сервера"""
    if role_id in role_cache:
        return role_cache[role_id]
    
    try:
        url = f"https://discord.com/api/v9/guilds/{GUILD_ID}/roles"
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            roles = r.json()
            for role in roles:
                role_cache[role['id']] = role['name']
                if role['id'] == str(role_id):
                    return role['name']
    except Exception as e:
        print(f"❌ Ошибка получения роли: {e}")
    
    return f"роль {role_id}"

def send_to_telegram(text):
    """ОТЛАЖЕННАЯ функция отправки в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        print(f"\n📤 Отправка в Telegram...")
        print(f"📊 URL: {url}")
        print(f"📦 Данные: {json.dumps(data, ensure_ascii=False)}")
        
        r = requests.post(url, json=data, timeout=5)
        
        print(f"📊 Статус: {r.status_code}")
        print(f"📋 Ответ: {r.text[:200]}")
        
        if r.status_code == 200:
            print("✅ Успешно отправлено!")
            return True
        else:
            print(f"❌ Ошибка {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ Исключение: {e}")
        return False

def parse_message(msg, channel_name):
    """Парсит сообщение и возвращает текст с названиями предметов"""
    items = []
    
    # Получаем упомянутые роли (это и есть предметы)
    if msg.get('mention_roles'):
        for role_id in msg['mention_roles']:
            role_name = get_role_name(role_id)
            items.append(f"• {role_name}")
    
    # Формируем текст
    if items:
        return f"<b>{channel_name.upper()} | DAWN BOT</b>\n\n" + "\n".join(items)
    return None

print("=" * 60)
print("🚀 DAWN BOT ПАРСЕР С ОТЛАДКОЙ")
print("=" * 60)
print(f"📡 Сервер ID: {GUILD_ID}")
print(f"📡 Каналы: {list(CHANNELS.keys())}")
print(f"📤 Telegram Chat ID: {TELEGRAM_CHAT_ID}")
print("=" * 60)

while True:
    try:
        for channel_name, channel_id in CHANNELS.items():
            print(f"\n🔍 Проверка {channel_name}...")
            
            url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=3"
            r = requests.get(url, headers=headers, timeout=5)
            
            if r.status_code == 200:
                messages = r.json()
                for msg in messages:
                    msg_id = msg['id']
                    
                    if last_messages.get(str(channel_id)) != msg_id:
                        if msg['author']['username'] == 'Dawnbot':
                            print(f"📨 Новое от Dawnbot в {channel_name}!")
                            
                            text = parse_message(msg, channel_name)
                            if text:
                                print(f"📝 Текст для отправки:\n{text}")
                                send_to_telegram(text)
                            
                            last_messages[str(channel_id)] = msg_id
            else:
                print(f"❌ Ошибка Discord: {r.status_code}")
        
        print("\n⏳ Ожидание 10 секунд...")
        time.sleep(10)
        
    except KeyboardInterrupt:
        print("\n👋 Остановлено")
        break
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        time.sleep(30)