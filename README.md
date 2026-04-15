# Иду к врачу | Telegram Mini App

MVP проекта для записи к врачу и подготовки детей к медицинским процедурам.

## Структура проекта

- `backend/` - FastAPI сервер, SQLAlchemy (SQLite), Jinja2 шаблоны для админки.
- `bot/` - Telegram бот на aiogram 3.x.
- `frontend/` - Статические файлы Mini App (HTML/CSS/JS).
- `materials/` - Ассеты (SVG, изображения, ТЗ).

## Установка и запуск

1. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

2. Настройте переменные окружения в `.env`:
   - `BOT_TOKEN` - токен вашего бота от @BotFather.

3. Запуск Backend:
   ```bash
   uvicorn backend.app.main:app --reload
   ```

4. Запуск Бота:
   ```bash
   python -m bot.main
   ```

## Админ-панель
Доступна по адресу: `http://localhost:8000/admin/tickets`

## Особенности реализации
- **БД**: Локальная SQLite (`app.db`).
- **МИС**: Используется `MockMISProvider` для генерации слотов.
- **ПДн**: Реализован экран согласия в Mini App.
- **Напоминания**: Бот отправляет уведомления за 3 часа до приема.
