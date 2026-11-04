# Как поднять канал, где MTProto вообще проходит

Проблема, которую это решает: SOCKS5 от обычного прокси-сервиса пускает
`api.telegram.org` (это HTTPS с SNI), но режет сырые соединения к дата-центрам
`149.154.*` / `91.108.*` — Telethon не может подключиться. Проверка:

```bash
python diagnose.py
```

Нужен канал, где эти подсети открыты. Два рабочих варианта.

---

## Вариант A. VPS + SSH-туннель (ничего не ставить на сервер)

Подходит любой VPS за €3–5 (Hetzner, Aeza, Timeweb и т.п.), где Telegram не заблокирован.
На сервере **ничего** устанавливать не нужно — SOCKS5 поднимает сам SSH.

**1. Проверить с сервера, что DC доступны** (обязательно, иначе смысла нет):

```bash
ssh root@<IP>
for ip in 149.154.167.51 149.154.175.53 91.108.56.130; do
  timeout 5 bash -c "echo > /dev/tcp/$ip/443" && echo "$ip ok" || echo "$ip FAIL"
done
```

Все три `ok` — годится.

**2. На Windows-машине поднять туннель:**

```cmd
ssh -N -D 1080 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes root@<IP>
```

Окно должно остаться открытым (это и есть туннель). Автозапуск при входе в систему:

```cmd
schtasks /Create /SC ONLOGON /TN "SenderX SSH tunnel" /TR "ssh -N -D 1080 -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes root@<IP>" /F
```

**3. В `config.txt`:**

```
proxy=socks5://127.0.0.1:1080
```

**4. Проверить:** `python diagnose.py` → все DC `✓`, затем `python main.py --check-net`.

---

## Вариант B. VPS + microsocks (постоянный SOCKS5 с паролем)

Если туннель на ноутбуке неудобен (нужен канал и без вашего ПК).

```bash
# на сервере, Ubuntu/Debian
apt-get update && apt-get install -y microsocks ufw
USER=senderx; PASS=$(openssl rand -hex 12); PORT=1080

cat >/etc/systemd/system/microsocks.service <<EOF
[Unit]
Description=microsocks SOCKS5
After=network.target

[Service]
ExecStart=/usr/bin/microsocks -i 0.0.0.0 -p ${PORT} -u ${USER} -P ${PASS}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now microsocks
ufw allow ${PORT}/tcp
echo "proxy=socks5://${USER}:${PASS}@<IP>:${PORT}"
```

Последнюю строку вставьте в `config.txt`. Порт лучше не 1080, а случайный
(например 34567), и ограничить доступ по IP: `ufw allow from <ваш IP> to any port <PORT>`.

---

## Чего НЕ делать

- **Публичные MTProxy из каналов** — владелец видит все ваши подключения и может
  логировать метаданные; живут дни.
- **@MTProxybot без своего сервера** — он не выдаёт прокси, а регистрирует ваш
  (нужен `host:port` уже работающего mtproxy + секрет из него).
- **Fake-TLS MTProxy** (`secret` начинается на `ee…`) — Telethon такой режим не
  реализует, работает только обфусцированный (`dd…` или без префикса).

## Если MTProxy всё-таки нужен

На VPS с Docker:

```bash
docker run -d --name mtg --restart=always -p 443:3128 \
  nineseconds/mtg:2 simple-run 0.0.0.0 3128 <16-байтовый-hex-секрет>
```

Секрет сгенерировать: `openssl rand -hex 16`. Затем в `config.txt`:

```
proxy=mtproxy://<IP>:443/<секрет>
```

Регистрация в @MTProxybot (`/newproxy` → `<IP>:443` → секрет) нужна только для
статистики и монетизации, для работы прокси не обязательна.
