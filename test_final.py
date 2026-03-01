import requests
import websocket
import json

# 1. ПОЛУЧАЕМ ТОКЕН
print("🔑 Получаем токен...")
url = "https://csgo-guides.ru/garden-horizons/ws-token.php"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://csgo-guides.ru/garden-horizons/",
    "Origin": "https://csgo-guides.ru"
}
response = requests.get(url, headers=headers)
data = response.json()
token = data['token']
print(f"✅ Токен: {token[:30]}...")

# 2. ПОДКЛЮЧАЕМСЯ К WEBSOCKET С ЗАГОЛОВКАМИ
ws_url = f"wss://ws.grow-a-garden.ru/ws/stock?token={token}"
print(f"🔌 Подключаюсь...")

def on_message(ws, message):
    print("\n📨 Данные:", message)

def on_error(ws, error):
    print(f"❌ Ошибка: {error}")

def on_close(ws, close_status_code, close_msg):
    print("🔌 Закрыто")

def on_open(ws):
    print("✅ Подключено!")

# ПЕРЕДАЁМ ЗАГОЛОВКИ В WEBSOCKET
ws = websocket.WebSocketApp(ws_url,
                            header={
                                "Origin": "https://csgo-guides.ru",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                            },
                            on_open=on_open,
                            on_message=on_message,
                            on_error=on_error,
                            on_close=on_close)

ws.run_forever()