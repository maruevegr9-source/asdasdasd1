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

print("🔥 ТЕСТОВЫЙ РЕЖИМ - ПОЛНЫЙ РАЗБОР")
print(f"📡 Каналы: {list(CHANNELS.keys())}\n")

while True:
    for name, cid in CHANNELS.items():
        try:
            # Читаем последние 10 сообщений для анализа
            r = requests.get(f"https://discord.com/api/v9/channels/{cid}/messages?limit=10", headers=headers)
            if r.status_code == 200:
                msgs = r.json()
                if msgs:
                    print(f"\n{'='*60}")
                    print(f"📊 АНАЛИЗ КАНАЛА: {name.upper()} (ID: {cid})")
                    print(f"{'='*60}")
                    print(f"📨 Всего сообщений в выборке: {len(msgs)}")
                    
                    # Анализируем каждое сообщение
                    for i, msg in enumerate(msgs):
                        print(f"\n--- СООБЩЕНИЕ #{i+1} ---")
                        print(f"🆔 ID: {msg['id']}")
                        print(f"👤 Автор: {msg['author']['username']} (ID: {msg['author']['id']})")
                        print(f"⏰ Время: {msg['timestamp']}")
                        
                        # Проверяем тип сообщения
                        if msg.get('content'):
                            print(f"\n📝 ТЕКСТ ({len(msg['content'])} символов):")
                            print(msg['content'][:500] + "..." if len(msg['content']) > 500 else msg['content'])
                        
                        if msg.get('embeds'):
                            print(f"\n🖼️ EMBED'Ы ({len(msg['embeds'])}):")
                            for j, embed in enumerate(msg['embeds']):
                                print(f"\n--- EMBED {j+1} ---")
                                if embed.get('title'):
                                    print(f"Заголовок: {embed['title']}")
                                if embed.get('description'):
                                    print(f"Описание: {embed['description']}")
                                if embed.get('fields'):
                                    print(f"Поля ({len(embed['fields'])}):")
                                    for k, field in enumerate(embed['fields']):
                                        print(f"  {k+1}. {field.get('name', '')}: {field.get('value', '')}")
                                if embed.get('footer'):
                                    print(f"Футер: {embed['footer'].get('text', '')}")
                                if embed.get('image'):
                                    print(f"Изображение: {embed['image'].get('url', '')}")
                        
                        if msg.get('attachments'):
                            print(f"\n📎 ВЛОЖЕНИЯ ({len(msg['attachments'])}):")
                            for att in msg['attachments']:
                                print(f"  - {att.get('filename', '')} ({att.get('size', 0)} bytes)")
                        
                        if msg.get('stickers'):
                            print(f"\n🎨 СТИКЕРЫ: {len(msg['stickers'])}")
                        
                        # Проверяем, есть ли вообще какие-то данные
                        has_content = bool(msg.get('content') or msg.get('embeds') or msg.get('attachments'))
                        print(f"\n📊 Есть контент: {'✅ ДА' if has_content else '❌ НЕТ'}")
                        
                        # Если сообщение от Dawnbot, помечаем
                        if msg['author']['id'] == '1392612367329923175':
                            print(f"⭐ ЭТО СООБЩЕНИЕ ОТ DAWNBOT! ⭐")
                            
                            # Проверяем последнее сообщение для отслеживания новых
                            if i == 0:  # самое свежее
                                if last.get(str(cid)) != msg['id']:
                                    print(f"🆕 ЭТО НОВОЕ СООБЩЕНИЕ!")
                                    last[str(cid)] = msg['id']
                    
                    print(f"\n{'='*60}")
            else:
                print(f"❌ Ошибка {r.status_code} в {name}: {r.text}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    print(f"\n⏳ Следующая проверка через 10 секунд...")
    time.sleep(10)