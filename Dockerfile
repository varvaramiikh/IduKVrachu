# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости (если нужны)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Директория для volume с файлом БД (миграции и seed выполняются при старте приложения)
RUN mkdir -p /app/data

# Экспонируем порт для FastAPI
EXPOSE 8000

# Команда для запуска (по умолчанию запускаем backend)
# Для одновременного запуска бота и бэкенда в одном контейнере обычно используют supervisord 
# или запускают через скрипт. Здесь приведен пример запуска бэкенда.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
