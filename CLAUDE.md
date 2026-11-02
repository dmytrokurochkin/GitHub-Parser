# CLAUDE.md

Робочі нотатки для того, хто змінює цей репозиторій: як він влаштований і на що вже наступали.
Мова: код, коментарі, назви, логи, повідомлення комітів англійською; тексти для людей (пости в каналі, повідомлення адміну, `deploy.sh`, README, `.env.example`) українською.

## 1. Що це за проєкт

Бот публікує в Telegram-канал топ-10 трендових репозиторіїв GitHub: за день (щодня), за тиждень (у неділю) і за місяць (1-го числа), о 06:00 за Варшавою, з хештегами `#day` / `#week` / `#month`. Відповідає лише власнику (`ADMIN_ID`). Працює в Docker на Debian-ноутбуці власника. Публічний репозиторій `dmytrokurochkin/GitHub-Parser`, секретів у ньому немає. Статус: перша версія, на реальному каналі ще не запускалась.

Реклами й монетизації тут немає свідомо: рекламний бот буде окремим проєктом.

| Що | Чим |
|---|---|
| Telegram | aiogram 3.31.0, long polling, HTML parse mode |
| Тренди | парсинг github.com/trending (BeautifulSoup), запасний варіант: GitHub Search API |
| Описи | LLM Lapathonia через `openai.AsyncOpenAI` (як в AI-Bot-v2), кеш у SQLite на 30 днів |
| Стан | SQLite через aiosqlite, `data/bot.db` |
| Сервер | Docker Compose, `deploy.sh` |

## 2. Структура репозиторія

```
main.py                 # точка входу: перевірка .env, перевірка каналу, бот + цикл розкладу
core/config.py          # змінні з .env на рівні модуля, missing()
core/loader.py          # create_bot(): HTML, прев'ю посилань вимкнені за замовчуванням
core/utils.py           # redact()/RedactFilter (токени не йдуть у логи), utf16_len, visible_len
database.py             # Database: runs, appearances, descriptions, settings
services/periods.py     # Period (day/week/month), Schedule: last_slot/next_slot
services/trending.py    # Repo, parse_trending() (HTML), parse_search() (JSON)
services/github.py      # GitHubClient: сторінка trending, пошук, README
services/llm.py         # Describer: опис українською, кеш, запасний варіант на оригінальний опис
services/formatter.py   # build_post()/fit_post(): текст посту в межах 4096 символів
services/publisher.py   # Publisher: пост у канал з картинкою як прев'ю, повідомлення адміну
services/digest.py      # DigestService: розклад, догонка, захист від дублів, повтори, алерти
handlers/admin.py       # admin_router: /status /preview /test /post /pause /resume
assets/                 # day.png week.png month.png + make_banners.py (Pillow, лише для розробника)
tests/                  # pytest; fixtures/ — справжні сторінки trending (обрізані)
Dockerfile, docker-compose.yml, deploy.sh
```

## 3. Конфігурація (.env)

| Змінна | Обов'язкова | Призначення |
|---|---|---|
| `BOT_TOKEN` | так | токен бота |
| `CHANNEL_ID` | так | `@username` або `-100...` |
| `ADMIN_ID` | так | єдиний, кому бот відповідає і пише помилки |
| `CHANNEL_LINK` | ні | посилання у футері; порожньо: `@username` каналу з `get_chat` |
| `GITHUB_TOKEN` | ні | 5000 запитів/год замість 60 на IP |
| `LAPATHONIA_API_KEY` | ні | без нього описи оригінальні, англійською |
| `LAPATHONIA_BASE_URL`, `LLM_MODEL` | ні | провайдер і модель, типово MamayLM-Gemma-3-27B |
| `TIMEZONE`, `POST_TIME`, `WEEKLY_DAY`, `MONTHLY_DAY` | ні | розклад: `Europe/Warsaw`, `06:00`, `sunday`, `1` (1-28) |
| `CATCH_UP_HOURS` | ні | скільки годин після слоту пропущений пост ще наздоганяється, 12 |
| `TOP_SIZE` | ні | 1-25, типово 10 |
| `IMAGES_URL` | ні | звідки Telegram бере `{day,week,month}.png` |
| `DATA_DIR` | ні | ставить Dockerfile: `/app/data` (змонтовано `./data`) |
| `GITHUB_API_URL`, `GITHUB_WEB_URL` | ні | лише для тестів |

## 4. Архітектура: карта модулів

| Модуль | Відповідальність |
|---|---|
| `Schedule.last_slot(key, now)` | останній запланований момент періоду ≤ now; з нього ключ запуску `day:2026-10-30` |
| `DigestService.post_scheduled` | чи слот у вікні догонки, чи запуск ще не вийшов, чи не чекаємо повтору; збирає і надсилає під `_lock` |
| `DigestService.post_now` | `/post`: збирає і надсилає поточний запуск періоду незалежно від статусу (`force`) |
| `DigestService.build` | trending → (порожньо/помилка) → пошук; сортування за `stars_gained`; описи; історія для 🆕/🔁; текст |
| `DigestService._send` | `db.start` (claim) → `publish` → статус за типом помилки, `appearances` після успіху |
| `Database.history` | для кожного репо: `None` ніколи не був (🆕), `n` у скількох останніх постах поспіль (🔁) |
| `Describer.describe` | кеш → README → LLM → `clean_answer`; помилка або відповідь < 15 символів дає оригінальний опис |
| `fit_post` | ріже описи (220 → … → 0), поки видима довжина ≤ 4096 UTF-16 |

## 5. Як це працює

1. `main.py`: `config.missing()` → вихід з кодом 2. `check_channel()`: чи бот адмін каналу з `can_post_messages`, `@username` для футера. Повідомлення адміну про старт, меню команд, polling + `service.run()`.
2. `service.run()`: `recover()` (усі `posting` → `unknown` + алерт), далі кожні 30 с `run_due()` по `day`, `week`, `month` саме в цьому порядку (1-го в неділю виходять три пости поспіль).
3. `post_scheduled`: пауза → вихід; `now - slot > CATCH_UP_HOURS` → вихід (пропущено назавжди); статус запуску не `None`/`failed` → вихід; `_retry_at` ще не настав → вихід.
4. `build`, потім `_send`: `start()` атомарно ставить `posting` (лише для нового або `failed`), `send_message` з картинкою, далі `posted` + `appearances`.
5. Статуси: `posting` → `posted` | `failed` (Telegram відмовив або `RetryAfter`, повтор через 15 хв / `retry_after`) | `unknown` (тайм-аут, мережа, 5xx; автоматично не повторюється).

## 6. Пастки, про які треба знати наперед

- **Дублі.** `unknown` ніколи не надсилається повторно автоматично: після тайм-ауту чи обриву пост може вже бути в каналі. Повтор лише після явної відмови Telegram (`REFUSED` у `services/digest.py`) або `RetryAfter`. Бот, вбитий посеред надсилання, лишає `posting`, і `recover()` при старті робить з нього `unknown`. Адмін вирішує через `/post`.
- **Картинка через прев'ю, не через фото.** Підпис до фото обмежений 1024 символами, а топ з описами займає ~2000. Тому пост є звичайним повідомленням (4096), а шапка йде як `LinkPreviewOptions(url=..., show_above_text=True, prefer_large_media=True)`. URL має бути доступний Telegram ззовні (типово raw.githubusercontent.com цього репо, тому репо публічне). Telegram кешує прев'ю за URL: замінивши картинку, змінюй назву файлу або додай `?v=2` до `IMAGES_URL`.
- **OSS Insight не працює.** Їхній `/v1/trends/repos` з березня 2026 віддає порожньо (`data_quality.status: unavailable`), тому як запасне джерело він не годиться. Запасне джерело: `/search/repositories?q=created:>=...&sort=stars`, це інша метрика (нові репо, усього зірок, без «+N за період»), тому `stars_gained=None`, і формат прибирає «+N».
- **Порядок trending.** GitHub сортує сторінку за власною оцінкою, а не за «stars today». `fetch()` пересортовує за `stars_gained`, щоб номер у пості відповідав числу поруч.
- **Порожній trending означає зламану верстку**, а не «нічого не трендить»: тоді спрацьовує запасне джерело і адміну приходить ℹ️. Тест `tests/test_trending.py` на збережених сторінках ловить зміну селекторів (`article.Box-row`, `h2 a[href]`, `/stargazers`, `/forks`, «N stars today»). Фікстури оновлювати справжніми сторінками.
- **Дати в пості беруться з `now`, ключ запуску зі слоту.** `/post week` у п'ятницю показує останні 7 днів, а запуск належить минулій неділі. Місяць підписується назвою місяця, що містить `day - 15 днів`.
- **DST.** Слот будується з настінного часу (`datetime.combine(date, POST_TIME, tzinfo=zone)`), тому 06:00 лишається 06:00 після переведення годинника. Порівняння aware-datetime ідуть за UTC.
- **tzdata.** У python:slim і на Windows своєї бази часових поясів немає, тому `tzdata` стоїть у requirements, без нього `ZoneInfo` падає.
- **Пауза й догонка.** `/resume` не відрізняє паузу від вимкненого сервера: слот, пропущений менше ніж `CATCH_UP_HOURS` тому, вийде одразу.
- **Перший запуск** у межах вікна догонки одразу публікує поточний денний пост (і тижневий/місячний, якщо їхній слот теж у вікні).
- **Ліміти GitHub без токена.** 60 запитів/год на IP. Пост = 1 запит сторінки + до 10 README (лише для репо без кешованого опису). Пошук має власний ліміт 10/хв.
- **Токени в deploy.sh** йдуть в awk через `ENVIRON` (а не `-v`, який обробляє `\`-послідовності, і не аргументами, які видно в `ps`). `read -s` для секретів. `.env` з правами 600, `cat >` у наявний файл ці права зберігає.
- **`ask_yes` лише латиницею**: у локалі C кирилиця в `[...]` порівнюється побайтово, а «ні» й «так» починаються з того самого байта.
- **Сон ноутбука.** `deploy.sh` маскує `sleep/suspend/hibernate.target` (діє одразу) і пише drop-in для logind (кришка, діє після перезавантаження). `systemd-logind` наживо не перезапускається, бо це може обірвати графічну сесію.
- **Том `./data`, а не `./bot.db`**: відсутній файл Docker створив би як теку, а SQLite ще й тримає поруч `-wal`/`-shm`.

## 7. Правила

- Нова логіка разом з тестом у `tests/`. Перед комітом: `python -m pytest` (усе має пройти). `bash -n deploy.sh`, і `shellcheck deploy.sh`, якщо він є.
- Сервісам потрібні лише методи `GitHubClient`/`Publisher`; тести підставляють `FakeGitHub`/`FakePublisher` з `tests/conftest.py`, час через `Clock`. Нових прихованих звернень до мережі в `DigestService` не додавати.
- API aiogram перевіряти по встановленому пакету (`.venv/Lib/site-packages/aiogram`), а не з пам'яті.
- Не запускати бота з реальним токеном і реальним каналом для перевірок. Для перевірки збирання посту є `/preview` (один період) і `/test` (усі три). Обидві команди лише будують пост через `build()` і нічого не записують у `runs`/`appearances`, тому розклад і позначки 🆕/🔁 в каналі вони не змінюють (описи LLM при цьому кешуються).
- Секрети не логувати: нові токени реєструвати в `add_secret()` у `main.setup_logging()`.
- Коміти: Conventional Commits, тема англійською; без трейлерів співавторства і згадок AI.
