# SenderX (TeleSender)

📨 Рассылка персонализированных сообщений в Telegram: несколько аккаунтов с
ротацией, шаблоны с именами, защита от повторной отправки и понятные отчёты.

Форк [AlZarPy/TeleSender](https://github.com/AlZarPy/TeleSender) с упором на
предсказуемость: каждое сообщение получает честный статус, неудачи не теряются,
прогон можно остановить и продолжить без спама по второму кругу.

## Возможности

- Отправка по списку `t.me/username` из CSV
- Несколько аккаунтов с ротацией при `FloodWait`
- Шаблоны `<МоёИмя>` / `<ЕгоИмя>` (пустое имя получателя превращается в «друг», а не в дыру в тексте)
- **`sent.jsonl`** — журнал: успешно отправленным повторно не пишем
- **`--dry-run`** — план без обращения к Telegram
- **`--limit`**, `--min-delay`, `--max-delay` — контроль объёма и темпа
- Лимит на аккаунт (`max_per_account`) и паузы настраиваются в конфиге
- Тесты без сети: `python tests/test_smoke.py` и `python tests/test_sender_mock.py`

## Установка

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Настройка аккаунтов

1. Получите `api_id` и `api_hash` на https://my.telegram.org → API development tools.
2. Скопируйте пример и впишите свои значения:

```bash
cp example_config.txt config.txt
```

```
session_name=sender1;api_id=123456;api_hash=ВАШ_HASH;my_name=Александр;min_delay=20;max_delay=60;max_per_account=50
```

`session_name` — имя файла сессии (`.session` создастся сам), `my_name` подставляется
в `<МоёИмя>`. Необязательные `min_delay`/`max_delay`/`max_per_account` по умолчанию
20 / 60 / 50. Если сеть блокирует Telegram — добавьте `proxy=` (см. ниже).

3. Авторизуйте аккаунты — **запускайте сами, в своём терминале**:

```bash
python auth_login.py
```

Телефон, код из Telegram и пароль 2FA вводятся скрыто и уходят только на
api.telegram.org. Файлы `*.session` эквивалентны паролю — они в `.gitignore`.

4. Проверьте связь до Telegram (можно и до входа):

```bash
python main.py --check-net
```

## Получатели

`recipients.csv`, колонка `recipient`. Понимает `t.me/name`, `@name`, `https://t.me/name`.
Мусор (телефоны, инвайт-ссылки, короткие логины) и дубли отбрасываются с отчётом.

```csv
recipient
t.me/username1
@username2
```

## Запуск

```bash
# посмотреть план, ничего не отправляя
python main.py --dry-run

# один тестовый получатель, без пауз
python main.py --limit 1 --min-delay 0 --max-delay 0 --message "Привет, <ЕгоИмя>! Я <МоёИмя>."

# обычный прогон
python main.py --message-file message.txt
```

Ключи: `--config`, `--recipients`, `--message`, `--message-file`, `--limit`,
`--min-delay`, `--max-delay`, `--dry-run`, `--yes`, `--sent-log`, `--ignore-history`.

Итог прогона: отправлено / ошибок / упёрлись в лимит / осталось, с причинами ошибок
(`not_found`, `privacy`, `forbidden`, `self`, `error:ИмяКласса`).

## Что изменилось относительно исходного TeleSender

| Было | Стало |
|---|---|
| Ошибка отправки печаталась, но получатель удалялся из очереди | Статус возвращается наверх; в очередь не возвращается только успешный |
| `FloodWaitError` глотался внутри `send_messages`, ротация аккаунтов не срабатывала | `FloodDetected` прерывает аккаунт, получатель переходит к следующему аккаунту |
| Повторный запуск отправлял всем заново | `sent.jsonl` + `--ignore-history` при необходимости |
| Только интерактивный ввод текста | `--message` / `--message-file` (для cron и тестов) |
| Нет проверки конфига | Валидация с понятными ошибками, маскировка `api_hash` в выводе |
| Дубли и мусор в CSV | Нормализация, дедупликация, отчёт об отброшенных строках |
| Нет `requirements.txt`, сессии не игнорировались | `requirements.txt`, `.gitignore` |
| Тестов не было | 25 проверок в `tests/test_smoke.py` |

## Если Telegram недоступен

В сетях, где TCP до дата-центров Telegram закрыт, вход и отправка падают с таймаутом.
Диагностика: `python main.py --check-net`. Лечится прокси в строке аккаунта:

```
# SOCKS5 (локальный VPN-клиент или удалённый прокси)
session_name=sender1;api_id=123456;api_hash=...;my_name=Александр;proxy=socks5://127.0.0.1:1080

# SOCKS5 с паролем
...;proxy=socks5://user:pass@host:1080

# MTProxy (секрет выдаёт @MTProxybot)
...;proxy=mtproxy://host:443/ee11223344556677
```

Прокси применяется и к `auth_login.py`, и к `main.py`. Для SOCKS5 нужен пакет
`python-socks[asyncio]` (уже в `requirements.txt`).

## Ограничения и безопасность

- Массовая рассылка незнакомым людям нарушает [правила Telegram](https://telegram.org/tos);
  аккаунты за это блокируют. Используйте только для своей аудитории, которая ждёт сообщения.
- Лимиты, которые видит сервер: паузы 20–60 с и `max_per_account` — разумный минимум, не гарантия.
- Ошибки `privacy` означают, что пользователь запретил сообщения от незнакомых — обходить нельзя.
- Никогда не коммитьте `config.txt`, `*.session`, `recipients.csv` и `sent.jsonl`.

## Упаковка в .exe

```bash
pyinstaller --onefile main.py
```
