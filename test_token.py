import requests

# Простой запрос к API токена
url = "https://csgo-guides.ru/garden-horizons/ws-token.php"

# Заголовки как у браузера
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://csgo-guides.ru/garden-horizons/",
    "Origin": "https://csgo-guides.ru"
}

# Делаем запрос
response = requests.get(url, headers=headers)

# Выводим результат
print("Статус:", response.status_code)
print("Ответ:", response.text)