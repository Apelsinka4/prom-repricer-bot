# Prom Repricer Bot

Telegram-бот для моніторингу цін конкурентів на Prom.ua та автоматичного оновлення цін у вашому магазині через Prom API.

## Що робить бот

1. Користувач запускає бота в Telegram.
2. Додає Prom API-ключ, який бот перевіряє запитом до Prom API.
3. Створює завдання моніторингу: SKU або ID свого товару, один чи кілька URL конкурентів, стратегію, мінімальну ціну, собівартість і мінімальну маржу.
4. Фоновий воркер раз на годину перевіряє всі активні завдання.
5. Бот бере найнижчу успішно отриману ціну конкурента і застосовує вибрану стратегію.
6. Ціна не опускається нижче `min_price` і нижче захисту маржі, якщо задано `cost_price` та `min_margin_percent`.
7. Усі перевірки, зміни ціни та помилки записуються в історію.

## Структура

```text
prom_repricer_bot/
├── .env.example
├── requirements.txt
├── main.py
├── bot/
│   ├── config.py
│   ├── database.py
│   ├── keyboards.py
│   ├── main.py
│   ├── parser.py
│   ├── prom_api.py
│   ├── worker.py
│   └── handlers/
│       ├── common.py
│       ├── settings.py
│       └── tasks.py
└── scripts/
    ├── test_db.py
    └── test_parser.py
```

## Вимоги

- Python 3.12+
- PostgreSQL або хмарний PostgreSQL-сервіс
- Telegram bot token від [@BotFather](https://t.me/BotFather)
- Prom.ua API token

## Швидкий старт

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Заповніть `.env`:

```env
BOT_TOKEN=your_telegram_bot_token_here
DATABASE_URL=postgresql://user:password@host:5432/database?sslmode=require
SCRAPER_API_KEY=
LOG_LEVEL=INFO
SCRAPER_HEADLESS=true
```

Запуск бота:

```bash
python -m bot.main
```

Або:

```bash
python main.py
```

## Команди

| Команда | Опис |
| --- | --- |
| `/start` | Реєстрація користувача і головне меню |
| `/setkey` | Збереження та валідація Prom API-ключа |
| `/addtask` | Додавання товару, конкурентів, стратегії та захисту маржі |
| `/mytasks` | Перегляд і видалення завдань |
| `/history` | Останні події repricing та помилки |

## Стратегії repricing

| Стратегія | Поведінка |
| --- | --- |
| `beat_by_step` | Ставить ціну нижче найнижчого конкурента на `step` |
| `match_lowest` | Дорівнює найнижчій ціні конкурента |
| `notify_only` | Не змінює ціну, тільки повідомляє, якщо конкурент дешевший |

## Захист маржі

Для кожного завдання можна задати:

- `min_price` — абсолютну мінімальну ціну;
- `cost_price` — собівартість;
- `min_margin_percent` — мінімальну маржу у відсотках.

Нижня межа ціни рахується як максимум із `min_price` та `cost_price + min_margin_percent`.

## База даних

Проєкт використовує PostgreSQL через `asyncpg`.

### `users`

| Поле | Тип | Опис |
| --- | --- | --- |
| `telegram_id` | `BIGINT PRIMARY KEY` | Telegram ID користувача |
| `prom_api_key` | `TEXT` | Prom API-ключ |
| `is_active` | `BOOLEAN` | Чи активний користувач |
| `plan_limit` | `INTEGER` | Ліміт завдань користувача |

### `monitoring_tasks`

| Поле | Тип | Опис |
| --- | --- | --- |
| `task_id` | `SERIAL PRIMARY KEY` | ID завдання |
| `user_id` | `BIGINT` | Власник завдання |
| `my_sku` | `TEXT` | SKU або ID товару на Prom.ua |
| `competitor_url` | `TEXT` | URL товару конкурента |
| `min_price` | `REAL` | Мінімальна ціна |
| `step` | `REAL` | Крок зниження ціни |
| `strategy` | `TEXT` | Стратегія repricing |
| `cost_price` | `REAL` | Собівартість товару |
| `min_margin_percent` | `REAL` | Мінімальна маржа |

### `task_competitors`

| Поле | Тип | Опис |
| --- | --- | --- |
| `competitor_id` | `SERIAL PRIMARY KEY` | ID конкурента |
| `task_id` | `INTEGER` | Завдання моніторингу |
| `competitor_url` | `TEXT` | URL товару конкурента |

### `repricing_events`

| Поле | Тип | Опис |
| --- | --- | --- |
| `event_id` | `BIGSERIAL PRIMARY KEY` | ID події |
| `task_id` | `INTEGER` | Завдання, якщо воно ще існує |
| `user_id` | `BIGINT` | Telegram ID користувача |
| `status` | `TEXT` | Тип події: `updated`, `checked`, `parse_error`, `update_error` тощо |
| `competitor_price` | `REAL` | Ціна конкурента |
| `current_price` | `REAL` | Поточна ціна товару |
| `new_price` | `REAL` | Нова ціна, якщо була розрахована |
| `reason` | `TEXT` | Людське пояснення |
| `error` | `TEXT` | Технічна помилка |

## Перевірки

Unit-тести парсера без live-запитів:

```bash
python -m scripts.test_parser
```

Smoke-тест бази даних:

```bash
python -m scripts.test_db
```

Live-тест парсера з реальною сторінкою:

```bash
python -m scripts.test_parser --live "https://prom.ua/ua/p..."
```

Healthcheck PostgreSQL:

```bash
python -m scripts.healthcheck
```

## Production Deploy

### Docker Compose

1. Скопіюйте `.env.production.example` у `.env` і заповніть секрети.
2. Запустіть:

```bash
docker compose up -d --build
```

Логи:

```bash
docker compose logs -f prom-repricer-bot
```

Контейнер має Docker healthcheck, який запускає `python -m scripts.healthcheck`.

### systemd

Готовий unit-файл лежить у `deploy/prom-repricer-bot.service`.
Короткий сценарій:

```bash
sudo mkdir -p /opt/prom-repricer-bot
sudo rsync -a --exclude .venv --exclude .env ./ /opt/prom-repricer-bot/
cd /opt/prom-repricer-bot
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo cp deploy/prom-repricer-bot.service /etc/systemd/system/prom-repricer-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now prom-repricer-bot
```

Логи:

```bash
journalctl -u prom-repricer-bot -f
```

## Runtime Limits

Production-обмеження задаються через `.env`:

| Змінна | Дефолт | Опис |
| --- | --- | --- |
| `WORKER_INTERVAL_SECONDS` | `3600` | Інтервал повного проходу воркера, мінімум 300 сек |
| `WORKER_TASK_DELAY_SECONDS` | `2` | Пауза між задачами/товарами |
| `MAX_COMPETITORS_PER_TASK` | `5` | Максимум URL конкурентів на один товар |
| `MAX_COMPETITOR_URL_LENGTH` | `2048` | Максимальна довжина одного URL |
| `RATE_LIMIT_WINDOW_SECONDS` | `10` | Вікно rate limit для Telegram-дій |
| `RATE_LIMIT_MAX_EVENTS` | `8` | Максимум дій у вікні |
| `RATE_LIMIT_BLOCK_SECONDS` | `20` | Тимчасове блокування при перевищенні |
| `SCRAPER_HEADLESS` | `true` | Headless-режим браузера для сервера/Docker |

## Важливі примітки

- `.env` не комітиться і має містити реальні токени.
- `DATABASE_URL` має задаватися тільки через `.env` або змінні середовища.
- Парсер використовує `nodriver`, тому для live-парсингу потрібне робоче браузерне середовище.
- `MemoryStorage` в aiogram підходить для MVP, але для продакшену варто перейти на Redis FSM storage.
