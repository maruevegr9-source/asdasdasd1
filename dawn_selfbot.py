import requests
import time
import json

# НОВЫЙ ТОКЕН
USER_TOKEN = "MTE5ODI4NDc2NDA0MjUwNjMyMw.Gz2mps.i44drjjzSvDipjLO6UIBpgbjgJMvRKoIvxdurM"

# ID каналов
CHANNELS = {
    'seeds': 1474799488689377463,
    'gear': 1474799504401236090,
    'weather': 1474799519706255510
}

headers = {'authorization': USER_TOKEN}
last = {}

print("🔥 ТЕСТОВЫЙ РЕЖИМ - ВЫВОД В КОНСОЛЬ")
print(f"📡 Каналы: {list(CHANNELS.keys())}\n")

while True:
    for name, cid in CHANNELS.items():
        try:
            r = requests.get(f"https://discord.com/api/v9/channels/{cid}/messages?limit=1", headers=headers)
            if r.status_code == 200:
                msgs = r.json()
                if msgs:
                    msg = msgs[0]
                    if last.get(str(cid)) != msg['id']:
                        print(f"\n{'='*50}")
                        print(f"📨 НОВОЕ СООБЩЕНИЕ В КАНАЛЕ: {name.upper()}")
                        print(f"{'='*50}")
                        
                        # Выводим всю информацию о сообщении
                        print(f"🆔 ID сообщения: {msg['id']}")
                        print(f"👤 Автор: {msg['author']['username']} (ID: {msg['author']['id']})")
                        print(f"⏰ Время: {msg['timestamp']}")
                        
                        if msg.get('content'):
                            print(f"\n📝 ТЕКСТ:")
                            print(msg['content'])
                        
                        if msg.get('embeds'):
                            print(f"\n🖼️ EMBED'Ы ({len(msg['embeds'])}):")
                            for i, embed in enumerate(msg['embeds']):
                                print(f"\n--- EMBED {i+1} ---")
                                if embed.get('title'):
                                    print(f"Заголовок: {embed['title']}")
                                if embed.get('description'):
                                    print(f"Описание: {embed['description']}")
                                if embed.get('fields'):
                                    for f in embed['fields']:
                                        print(f"Поле: {f['name']} = {f['value']}")
                                if embed.get('footer'):
                                    print(f"Футер: {embed['footer']['text']}")
                        
                        if msg.get('attachments'):
                            print(f"\n📎 ВЛОЖЕНИЯ: {len(msg['attachments'])}")
                        
                        last[str(cid)] = msg['id']
                        print(f"\n{'='*50}")
            else:
                print(f"❌ Ошибка {r.status_code} в {name}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    time.sleep(5)