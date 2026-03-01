import requests
import websocket
import json
import time

# 1. ПОЛУЧАЕМ СВЕЖИЙ ТОКЕН
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
print(f"✅ Токен получен: {token[:30]}...")

# 2. СРАЗУ ПОДКЛЮЧАЕМСЯ К WEBSOCKET
ws_url = f"wss://ws.grow-a-garden.ru/ws/stock?token={token}"
print(f"🔌 Подключаюсь к {ws_url}")

def on_message(ws, message):
    print("\n📨 ПОЛУЧЕНО:")
    if message == "pong":
        print("🏓 pong")
        return
    try:
        data = json.loads(message)
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except:
        print(message)

def on_error(ws, error):
    print(f"❌ Ошибка: {error}")

def on_close(ws, close_status_code, close_msg):
    print("🔌 Соединение закрыто")

def on_open(ws):
    print("✅ Подключено к WebSocket!")

ws = websocket.WebSocketApp(ws_url,
                            on_open=on_open,
                            on_message=on_message,
                            on_error=on_error,
                            on_close=on_close)

ws.run_forever()