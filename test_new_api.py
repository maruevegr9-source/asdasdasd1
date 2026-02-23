import requests
import json

url = "https://garden-horizons-stock.dawidfc.workers.dev/api/stock"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
}

try:
    print(f"Проверяем URL: {url}")
    response = requests.get(url, headers=headers, timeout=10)
    
    print(f"\nСтатус ответа: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type', 'не указан')}")
    print(f"Размер ответа: {len(response.content)} байт")
    
    # Покажем первые 200 символов ответа
    print(f"\nПервые 200 символов ответа:")
    print("-" * 50)
    print(response.text[:200])
    print("-" * 50)
    
    # Пробуем распарсить JSON
    try:
        data = response.json()
        print("\n✅ JSON успешно распарсен!")
        print(f"Структура данных: {list(data.keys())}")
        print("\nПример данных:")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:500])
    except json.JSONDecodeError as e:
        print(f"\n❌ Ошибка парсинга JSON: {e}")
        
except requests.exceptions.RequestException as e:
    print(f"Ошибка соединения: {e}")