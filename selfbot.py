import discord
import asyncio
import requests
import re
from discord.ext import commands

# ===== ТВОИ ДАННЫЕ =====
USER_TOKEN = "MTQ3NzU5Mjg4ODI5MTYyNzExMQ.GZlHyZ.d0YSb83f3VfCUcNgPoMIsF5W7fRG0PFRM9W3O0"
TELEGRAM_TOKEN = "8720227483:AAGgGRK893KQYOg51pjuxImWogFd4Y3t9eg"
TELEGRAM_CHAT_ID = -1002808898833

# ID каналов
CHANNELS = {
    'seeds': 1474799488689377463,
    'gear': 1474799504401236090,
    'weather': 1474799519706255510
}

intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix='!', self_bot=True, intents=intents)

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=data)
        print("✅ Отправлено в Telegram")
    except:
        pass

@client.event
async def on_ready():
    print(f'🔥 Селфбот запущен как {client.user}')
    print(f'📡 Слежу за каналами...')

@client.event
async def on_message(message):
    if message.channel.id not in CHANNELS.values():
        return
    
    channel_type = None
    for name, ch_id in CHANNELS.items():
        if message.channel.id == ch_id:
            channel_type = name
            break
    
    print(f"\n📨 Новое в {channel_type}")
    
    if message.embeds:
        for embed in message.embeds:
            if embed.description:
                items = []
                lines = embed.description.split('\n')
                
                for line in lines:
                    match = re.search(r'<@&(\d+)>\s*\(x(\d+)\)', line)
                    if match:
                        role_id = match.group(1)
                        count = match.group(2)
                        
                        # Ищем роль
                        role = None
                        for guild in client.guilds:
                            role = guild.get_role(int(role_id))
                            if role:
                                break
                        
                        if role:
                            items.append(f"• {role.name}: {count} шт.")
                
                if items:
                    text = f"<b>{channel_type.upper()}</b>\n\n" + "\n".join(items)
                    send_to_telegram(text)

client.run(USER_TOKEN)