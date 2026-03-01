import requests
import time
import json
import re

# ===== ТВОИ ДАННЫЕ =====
USER_TOKEN = "MTQ3NzU5Mjg4ODI5MTYyNzExMQ.GZlHyZ.d0YSb83f3VfCUcNgPoMIsF5W7fRG0PFRM9W3O0"
TELEGRAM_TOKEN = "ТВОЙ_ТОКЕН_ТЕЛЕГРАМ"
TELEGRAM_CHAT_ID = -1002808898833

# ID каналов
CHANNELS = {
    'seeds': 1474799488689377463,
    'gear': 1474799504401236090,
    'weather': 1474799519706255510
}

STATE_FILE = 'last_messages.json'
CHECK_INTERVAL = 10

headers = {
    'authorization': USER_TOKEN,
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

def load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_state(data):
    with open(STATE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=data)
        print(f"✅ Отправлено в Telegram ({r.status_code})")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

def get_last_messages(channel_id, limit=1):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}"
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"❌ Ошибка Discord {r.status_code}: {r.text[:100]}")
    except:
        pass
    return []

def parse_messages(messages, channel_type):
    if not messages:
        return False
    
    for msg in messages:
        # Парсим embed'ы
        if 'embeds' in msg and msg['embeds']:
            for embed in msg['embeds']:
                if 'description' in embed and embed['description']:
                    desc = embed['description']
                    
                    # Ищем паттерн с ролями
                    items = []
                    lines = desc.split('\n')
                    for line in lines:
                        match = re.search(r'<@&(\d+)>\s*\(x(\d+)\)', line)
                        if match:
                            items.append(f"• Роль {match[1]}: {match[2]} шт.")
                    
                    if items:
                        text = f"<b>{channel_type.upper()}</b>\n\n" + "\n".join(items)
                        send_to_telegram(text)
                        return True
                    
                    # Если нет ролей, отправляем как есть
                    send_to_telegram(f"<b>{channel_type.upper()}</b>\n\n{desc}")
                    return True
        
        # Парсим обычный текст
        elif 'content' in msg and msg['content']:
            send_to_telegram(f"<b>{channel_type.upper()}</b>\n\n{msg['content']}")
            return True
    
    return False

print("🚀 Запуск Discord парсера через requests...")
print(f"📡 Токен: {USER_TOKEN[:20]}...")

last_state = load_state()
print(f"📊 Загружено {len(last_state)} записей")

# Проверка соединения с Discord
test_url = "https://discord.com/api/v9/users/@me"
test = requests.get(test_url, headers=headers)
if test.status_code == 200:
    user_data = test.json()
    print(f"✅ Успешный вход как {user_data.get('username')}#{user_data.get('discriminator')}")
else:
    print(f"❌ Ошибка входа: {test.status_code}")
    print("   Токен недействителен!")
    exit()

while True:
    try:
        for name, channel_id in CHANNELS.items():
            print(f"📡 Проверка {name}...")
            messages = get_last_messages(channel_id, 1)
            
            if messages:
                msg_id = str(messages[0]['id'])
                if last_state.get(str(channel_id)) != msg_id:
                    print(f"📨 Новое сообщение в {name} (ID: {msg_id})")
                    if parse_messages(messages, name):
                        last_state[str(channel_id)] = msg_id
                        save_state(last_state)
            else:
                print(f"⚠️ Нет сообщений в {name} или нет доступа")
        
        print(f"⏳ Ожидание {CHECK_INTERVAL} сек...")
        time.sleep(CHECK_INTERVAL)
        
    except KeyboardInterrupt:
        print("\n👋 Остановлено пользователем")
        break
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        time.sleep(30)