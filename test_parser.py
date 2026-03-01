import requests
from bs4 import BeautifulSoup
import re
import time

print("🚀 Тестовый парсер Garden Horizons")
print("Нажми Ctrl+C для остановки\n")

while True:
    try:
        # Получаем страницу
        response = requests.get("https://garden-horizons.com")
        soup = BeautifulSoup(response.text, 'html.parser')
        
        print(f"\n🕒 {time.strftime('%H:%M:%S')} - НОВЫЕ ДАННЫЕ:")
        print("-" * 40)
        
        # Ищем семена
        seeds = []
        seed_section = soup.find(text=re.compile("Bill's Seed Shop"))
        if seed_section:
            items = seed_section.find_all_next(text=re.compile(r'(\w+)\s*x(\d+)'))
            for i, item in enumerate(items[:6]):  # первые 6 позиций
                match = re.search(r'(\w+)\s*x(\d+)', item)
                if match:
                    seeds.append(f"{match[1]}: {match[2]} шт")
        
        print("🌱 СЕМЕНА:")
        for seed in seeds:
            print(f"  {seed}")
        
        # Ищем инструменты
        gear = []
        gear_section = soup.find(text=re.compile("Molly's Gear Shop"))
        if gear_section:
            items = gear_section.find_all_next(text=re.compile(r'(\w+)\s*x(\d+)'))
            for i, item in enumerate(items[:4]):  # первые 4 позиции
                match = re.search(r'(\w+)\s*x(\d+)', item)
                if match:
                    gear.append(f"{match[1]}: {match[2]} шт")
        
        print("\n⚙️ ИНСТРУМЕНТЫ:")
        for g in gear:
            print(f"  {g}")
        
        # Ищем погоду
        weather_section = soup.find(text=re.compile("CURRENT WEATHER"))
        if weather_section:
            weather = weather_section.find_next(text=True)
            print(f"\n🌤️ ПОГОДА: {weather}")
        
        print("-" * 40)
        print("⏳ Следующая проверка через 60 секунд...")
        
        time.sleep(60)
        
    except KeyboardInterrupt:
        print("\n👋 Остановлено")
        break
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        time.sleep(10)