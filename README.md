# Иду к врачу | Telegram Mini App

MVP проекта для записи к врачу и подготовки детей к медицинским процедурам.

## Структура проекта

- `backend/` — FastAPI сервер, SQLAlchemy (SQLite), Jinja2 шаблоны для админки.
- `bot/` — Telegram бот на aiogram 3.x.
- `frontend/` — Статические файлы Mini App (HTML/CSS/JS).
- `materials/` — Ассеты (SVG, изображения, ТЗ).
- `migrations/` — Alembic миграции схемы БД (стартовая ревизия `0001_initial`).

## Миграции БД

Схема управляется Alembic. При старте backend автоматически выполняется
`alembic upgrade head` (см. `backend/app/main.py::_run_migrations`), после чего
запускается seed демо-данных, если БД пуста.

Ручные команды:

```bash
# применить все миграции
alembic upgrade head

# создать новую ревизию
alembic revision -m "add new table"

# откатить на одну ревизию
alembic downgrade -1
```

Файл `alembic.ini` берёт `script_location = migrations`. Стартовая ревизия
`0001_initial` создаёт всю схему через `Base.metadata.create_all`.

## Локальный запуск

1. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

2. Скопируйте `.env.example` в `.env` и заполните значения (минимум `BOT_TOKEN`).

3. Backend (миграции и seed выполнятся автоматически на старте):
   ```bash
   uvicorn backend.app.main:app --reload
   ```

4. Бот:
   ```bash
   python -m bot.main
   ```

При старте оба сервиса печатают в лог переменные окружения (секреты замаскированы)
и сообщение `=== готов к работе ===`.

## Развертывание в docker-compose

Сборка и запуск:

```bash
docker compose build
docker compose up -d
docker compose logs -f backend bot
```

Compose поднимает два сервиса из общего `Dockerfile`:

- `backend` — FastAPI на порту `8000`, выполняет `alembic upgrade head` и seed на старте.
- `bot` — long-polling Telegram бот, стартует после backend.

Оба сервиса монтируют общий volume `db_data → /app/data`, где лежит SQLite-файл.

### Переменные окружения

Значения берутся из `.env` (директива `env_file` в `docker-compose.yml`).
`DATABASE_URL` принудительно переопределяется в compose, чтобы оба сервиса
писали в один и тот же файл на volume.

| Переменная          | Обязательна | Значение по умолчанию                          | Назначение                                                                 |
|---------------------|-------------|------------------------------------------------|----------------------------------------------------------------------------|
| `BOT_TOKEN`         | да          | —                                              | Токен Telegram-бота от @BotFather.                                         |
| `DATABASE_URL`      | нет         | `sqlite+aiosqlite:////app/data/app.db` (compose) | DSN БД. В compose указывает на файл на volume `db_data`.                   |
| `SECRET_KEY`        | нет         | `dev_secret_key`                               | Подпись/валидация Telegram `initData`. В проде задайте уникальное.         |
| `DEBUG`             | нет         | `True`                                         | Режим отладки: пропускает валидацию `initData` и эмулирует оплату.         |
| `WEB_APP_URL`       | нет         | `http://localhost:8000`                        | Публичный HTTPS-URL Mini App. Только при `https://` бот регистрирует Web App. |
| `YOOKASSA_SHOP_ID`  | нет         | `""`                                           | ID магазина в YooKassa (для боевой оплаты).                                |
| `YOOKASSA_SECRET`   | нет         | `""`                                           | Секретный ключ YooKassa.                                                   |

Пример `.env` для боевого деплоя:

```env
BOT_TOKEN=123456:AA...your_token...
SECRET_KEY=замените_на_длинную_случайную_строку
DEBUG=False
WEB_APP_URL=https://miniapp.example.com
YOOKASSA_SHOP_ID=123456
YOOKASSA_SECRET=live_xxxxxxxxxxxxxxxxxxxxxxxx
```

`DATABASE_URL` указывать в `.env` не нужно — compose задаёт его сам.

### Полезные команды

```bash
# применить миграции вручную внутри контейнера
docker compose exec backend alembic upgrade head

# сбросить БД (удалит volume!)
docker compose down -v

# перезапустить только бота
docker compose restart bot
```

## Админ-панель

Доступна по адресу: `http://localhost:8000/admin/tickets`.

## Особенности реализации

- **БД**: SQLite (`app.db`), путь задаётся через `DATABASE_URL`.
- **Миграции**: Alembic, прогоняются автоматически на старте backend.
- **МИС**: Используется `MockMISProvider` для генерации слотов.
- **ПДн**: Реализован экран согласия в Mini App (152-ФЗ).
- **Напоминания**: Бот отправляет уведомления за 3 часа до приёма.
- **Логирование**: Backend пишет каждый HTTP-запрос; бот — каждый incoming update и каждый вызов Telegram API.
