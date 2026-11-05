# Поднять сервис на своём сервере

Два способа: Docker (проще) и systemd (если хочется без контейнеров).

Важно: **один экземпляр = один владелец**. Не выкладывайте панель в общий доступ —
через неё можно отправлять сообщения от ваших аккаунтов.

---

## 1. Docker Compose

```bash
git clone https://github.com/Js7u5CEh/SenderX.git
cd SenderX
mkdir -p data
cp .env.example data/.env         # задайте PANEL_PASSWORD
cp example_config.txt data/config.txt   # впишите api_id/api_hash/api_name
docker compose up -d --build
```

Панель поднимется на `127.0.0.1:8765` (наружу не торчит). Дальше — nginx
(`deploy/nginx/pochtamt.conf`) с сертификатом Let's Encrypt:

```bash
sudo certbot --nginx -d pochtamt.example.com
```

Состояние живёт в `./data`: `config.txt`, `.env`, `*.session`, `panel.db`,
`sent.jsonl`. Бэкап — это копия каталога `data`.

```bash
docker compose logs -f worker     # что делает воркер
docker compose restart worker     # перезапуск отправки
```

---

## 2. systemd без Docker

```bash
sudo useradd -m -s /bin/bash senderx
sudo mkdir -p /opt/senderx && sudo chown senderx:senderx /opt/senderx
sudo -u senderx git clone https://github.com/Js7u5CEh/SenderX.git /opt/senderx
cd /opt/senderx
sudo -u senderx python3 -m venv .venv
sudo -u senderx .venv/bin/pip install -r requirements.txt

sudo -u senderx cp .env.example .env          # пароль панели
sudo -u senderx cp example_config.txt config.txt   # аккаунты
sudo -u senderx .venv/bin/python auth_login.py     # вход в Telegram: QR или код

sudo cp deploy/systemd/pochtamt-panel.service  /etc/systemd/system/
sudo cp deploy/systemd/pochtamt-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pochtamt-panel pochtamt-worker
systemctl status pochtamt-panel --no-pager
```

Логи: `journalctl -u pochtamt-worker -f`.

---

## 3. Первый запуск

1. Откройте панель, войдите по паролю из `.env`.
2. **Настройки** → аккаунт: квота в сутки (новому 15–20), при желании включите прогрев с сегодняшней даты.
3. **Получатели** → импорт базы: `username;Имя`, по одному в строке.
4. **Кампании** → новая: вступление, текст с `<ЕгоИмя>` и вариантами `{так|иначе}`, список,
   лимит в час, окно по часам, при необходимости — время старта.
5. **Предпросмотр текста** — проверить, как раскроются варианты и имена.
6. «Запустить». Дальше воркер ведёт очередь сам: квитанции, паузы, сторож, сводка в Telegram.

---

## 4. Что нельзя делать

- Держать панель открытой в интернет без HTTPS и пароля.
- Отдавать доступ посторонним: это доступ к вашим аккаунтам.
- Писать людям без согласия. Telegram банит за это аккаунты, а в РФ реклама
  без согласия получателя запрещена (ст. 18 ФЗ «О рекламе»).
  Инструмент рассчитан на свою базу: клиенты, подписчики, те, кто ждал сообщение.
