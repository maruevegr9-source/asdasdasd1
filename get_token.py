import os
import re

# Путь к папке с токенами Discord
path = os.path.expandvars(r"%APPDATA%\discord\Local Storage\leveldb")

print("🔍 Ищем токены Discord...")
print(f"📁 Папка: {path}")

if not os.path.exists(path):
    print("❌ Папка не найдена! Discord не установлен?")
    exit()

found = False

# Читаем все .log файлы
for file in os.listdir(path):
    if file.endswith('.log'):
        file_path = os.path.join(path, file)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Ищем токен по паттерну
                tokens = re.findall(r'[a-zA-Z0-9_-]{24}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27}', content)
                if tokens:
                    for token in tokens:
                        print("\n" + "="*50)
                        print("✅ НАЙДЕН ТОКЕН:")
                        print("="*50)
                        print(token)
                        print("="*50 + "\n")
                        found = True
        except:
            pass

# Читаем .ldb файлы
for file in os.listdir(path):
    if file.endswith('.ldb'):
        file_path = os.path.join(path, file)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                tokens = re.findall(r'[a-zA-Z0-9_-]{24}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27}', content)
                if tokens:
                    for token in tokens:
                        print("\n" + "="*50)
                        print("✅ НАЙДЕН ТОКЕН:")
                        print("="*50)
                        print(token)
                        print("="*50 + "\n")
                        found = True
        except:
            pass

if not found:
    print("❌ Токены не найдены. Закрой Discord и попробуй снова.")

input("\nНажми Enter для выхода...")