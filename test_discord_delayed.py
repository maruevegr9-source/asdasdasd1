import requests
import json
import time

# ТВОИ ДАННЫЕ (возьми из .env)
DISCORD_TOKEN = "MTE5ODI4NDc2NDA0MjUwNjMyMw.GyqaY8.OTWlAK9fY3NbOy9xThB_xiZkGJJg2tnQR3DDeQ"
DISCORD_GUILD_ID = "1392614350686130198"
CHANNELS = {
    'seeds': 1474799488689377463,
    'gear': 1474799504401236090,
    'weather': 1474799519706255510
}

headers = {'authorization': DISCORD_TOKEN}

print("=" * 50)
print("🔍 ТЕСТ ДОСТУПА К DISCORD (С ЗАДЕРЖКАМИ)")
print("=" * 50)

# 1. Проверяем токен
print("\n1️⃣ ПРОВЕРКА ТОКЕНА:")
time.sleep(2)  # задержка 2 секунды
r = requests.get("https://discord.com/api/v9/users/@me", headers=headers)
print(f"   Статус: {r.status_code}")
if r.status_code == 200:
    user = r.json()
    print(f"   ✅ Успешный вход как: {user['username']}#{user['discriminator']}")
    print(f"   ID: {user['id']}")
else:
    print(f"   ❌ Ошибка: {r.text[:200]}")
    exit()

# 2. Получаем список серверов
print("\n2️⃣ СЕРВЕРА ПОЛЬЗОВАТЕЛЯ:")
time.sleep(2)  # задержка 2 секунды
r = requests.get("https://discord.com/api/v9/users/@me/guilds", headers=headers)
if r.status_code == 200:
    guilds = r.json()
    print(f"   Найдено серверов: {len(guilds)}")
    for guild in guilds:
        if guild['id'] == DISCORD_GUILD_ID:
            print(f"   ✅ НУЖНЫЙ СЕРВЕР: {guild['name']} (ID: {guild['id']})")
        else:
            print(f"   • {guild['name']} (ID: {guild['id']})")
else:
    print(f"   ❌ Ошибка: {r.status_code}")

# 3. Проверяем каналы
print("\n3️⃣ ПРОВЕРКА КАНАЛОВ:")
for name, channel_id in CHANNELS.items():
    print(f"\n   📢 Канал {name.upper()} (ID: {channel_id}):")
    
    time.sleep(3)  # задержка 3 секунды перед каждым каналом
    
    # Получаем информацию о канале
    r = requests.get(f"https://discord.com/api/v9/channels/{channel_id}", headers=headers)
    if r.status_code == 200:
        channel_info = r.json()
        print(f"   ✅ Название канала: {channel_info.get('name', 'N/A')}")
        print(f"   📝 Тип: {channel_info.get('type', 'N/A')}")
    else:
        print(f"   ❌ Канал не доступен: {r.status_code}")
        continue
    
    time.sleep(3)  # задержка 3 секунды перед получением сообщений
    
    # Получаем последние 5 сообщений
    r = requests.get(f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=5", headers=headers)
    if r.status_code == 200:
        messages = r.json()
        print(f"   📨 Получено сообщений: {len(messages)}")
        
        for i, msg in enumerate(messages, 1):
            print(f"\n   --- СООБЩЕНИЕ #{i} ---")
            print(f"   🆔 ID: {msg['id']}")
            print(f"   👤 Автор: {msg['author']['username']} (ID: {msg['author']['id']})")
            print(f"   📝 Текст: {msg.get('content', 'НЕТ ТЕКСТА')[:100]}")
            print(f"   🖼️ Embed'ы: {len(msg.get('embeds', []))}")
            
            if msg.get('embeds'):
                for j, embed in enumerate(msg['embeds']):
                    print(f"      Embed {j+1}:")
                    if embed.get('title'):
                        print(f"         Title: {embed['title']}")
                    if embed.get('description'):
                        print(f"         Description: {embed['description'][:100]}")
                    if embed.get('fields'):
                        print(f"         Fields: {len(embed['fields'])}")
            
            time.sleep(2)  # задержка 2 секунды между сообщениями
    else:
        print(f"   ❌ Не удалось получить сообщения: {r.status_code}")

print("\n" + "=" * 50)
print("✅ ТЕСТ ЗАВЕРШЕН")
print("=" * 50)