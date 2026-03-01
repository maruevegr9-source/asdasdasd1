import websocket
import json
import threading
import time

# Токен из предыдущего шага
TOKEN = "eyJpYXQiOjE3NzIzNjIzNTEsImV4cCI6MTc3MjM2MjM4MSwianRpIjoiNjhiZjM1ODM0MDZiMzNkYmEyNWI2ZTRlIiwiYXVkIjoiZ2FyZGVuLXN0b2NrLXdzIiwib3JpIjoiaHR0cHM6Ly9jc2dvLWd1aWRlcy5ydSJ9.oWzbCCxnOTnOWfiooTwshV1hQWy2ljoB29aqfo1upgM"

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

ws_url = f"wss://ws.grow-a-garden.ru/ws/stock?token={TOKEN}"
print(f"🔌 Подключаюсь к {ws_url}")

ws = websocket.WebSocketApp(ws_url,
                            on_open=on_open,
                            on_message=on_message,
                            on_error=on_error,
                            on_close=on_close)

ws.run_forever()