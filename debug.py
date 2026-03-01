import requests
from bs4 import BeautifulSoup

url = "https://garden-horizons.com"
response = requests.get(url)
soup = BeautifulSoup(response.text, 'html.parser')

# Сохраняем HTML для анализа
with open('page.html', 'w', encoding='utf-8') as f:
    f.write(response.text)
print("✅ HTML сохранён в page.html")

# Ищем все тексты с x(число)
print("\n🔍 Поиск паттернов 'слово x123':")
texts = soup.find_all(text=True)
for text in texts:
    if 'x' in text and any(c.isdigit() for c in text):
        print(f"Найдено: {text.strip()}")