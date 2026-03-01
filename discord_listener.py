import requests
import time
import json
import re
import html

USER_TOKEN = "MTE5ODI4NDc2NDA0MjUwNjMyMw.Gz2mps.i44drjjzSvDipjLO6UIBpgbjgJMvRKoIvxdurM"
TELEGRAM_TOKEN = "8720227483:AAGgGRK893KQYOg51pjuxImWogFd4Y3t9eg"
TELEGRAM_CHAT_ID = -1002808898833
GUILD_ID = "1392614350686130198"

CHANNELS = {
    'seeds': 1474799488689377463,
    'gear': 1474799504401236090,
    'weather': 1474799519706255510
}

headers = {'authorization': USER_TOKEN}
last_messages = {}
role_cache = {}

# Загружаем сохранённые ID сообщений, чтобы не спамить
try:
    with open('last_messages.json', 'r') as f:
        last_messages = json.load(f)
except:
    last_messages = {}

def save_last_messages():
    try:
        with open('last_messages.json', 'w') as f:
            json.dump(last_messages, f)
    except:
        pass

def get_role_name(role_id):
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
    except:
        pass
    return f"роль {role_id}"

def send_to_telegram(text):
    # Экранируем спецсимволы для HTML
    text = html.escape(text)
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=data, timeout=5)
        if r.status_code == 200:
            print(f"✅ Отправлено")
            return True
        else:
            print(f"❌ Ошибка {r.status_code}: {r.text}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    return False

def parse_message(msg, channel_name):
    items = []
    if msg.get('mention_roles'):
        for role_id in msg['mention_roles']:
            role_name = get_role_name(role_id)
            items.append(f"• {role_name}")
    
    if items:
        return f"<b>{channel_name.upper()} | DAWN BOT</b>\n\n" + "\n".join(items)
    return None

print("🚀 Discord Listener (без спама)")

while True:
    try:
        for channel_name, channel_id in CHANNELS.items():
            url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=1"
            r = requests.get(url, headers=headers, timeout=5)
            
            if r.status_code == 200:
                messages = r.json()
                if messages:
                    msg = messages[0]
                    msg_id = msg['id']
                    
                    # Проверяем по последнему сообщению, а не по всем
                    if last_messages.get(str(channel_id)) != msg_id:
                        if msg['author']['username'] == 'Dawnbot':
                            print(f"\n📨 Новое в {channel_name}")
                            text = parse_message(msg, channel_name)
                            if text:
                                send_to_telegram(text)
                            last_messages[str(channel_id)] = msg_id
                            save_last_messages()
        
        time.sleep(10)
        
    except KeyboardInterrupt:
        print("\n👋 Остановлено")
        break
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        time.sleep(30)