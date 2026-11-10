"""Приводит 11 аккаунтов к утверждённому виду: имя, аватар, описание со ссылкой, юзернейм.

Запуск: python tools/restyle_accounts.py [--only pechkin01,pechkin02]
Пишет построчный отчёт в stdout и ничего не отправляет.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient  # noqa: E402
from telethon.errors import UsernameInvalidError, UsernameOccupiedError  # noqa: E402
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest  # noqa: E402
from telethon.tl.functions.photos import UploadProfilePhotoRequest  # noqa: E402
from telethon.tl.functions.users import GetFullUserRequest  # noqa: E402

PEOPLE = [
    # аккаунт, имя, фамилия, аватар, юзернейм, роль в описании, инвайт
    ("pechkin01", "Алексей", "Морозов", "m2_desk_neon.jpg", "aleksey_morozov_terra",
     "Куратор · ИИ-агенты · Терра", "6lOUlnEV6-s0MTcy"),
    ("pechkin02", "Мария", "Соколова", "f3_editorial.jpg", "maria_sokolova_terra",
     "Контент-завод · Терра", "D1mV6dYXKQI1NzIy"),
    ("pechkin03", "Дмитрий", "Волков", "m3_laptop_icons.jpg", "dmitry_volkov_terra",
     "ИИ в бизнес-процессах · Терра", "nw29HFPrftxkOTEy"),
    ("pechkin04", "Анна", "Лебедева", "f8_laptop_icons.jpg", "anna_lebedeva_terra",
     "Вайбкодинг · Терра", "Xc2CjPP06FgyYmIy"),
    ("pechkin05", "Сергей", "Крылов", "m1_ginger_blazer.jpg", "sergey_krylov_terra",
     "Нейропродавец · Терра", "-S6K_9plXSllZTYy"),
    ("pechkin06", "Екатерина", "Зайцева", "f5_blonde_corporate.jpg", "ekaterina_zaytseva_terra",
     "ИИ-агенты · Терра", "mhzhl8EhSBQ0MzYy"),
    ("pechkin07", "Вера", "Ковалёва", "f2_painterly.jpg", "vera_kovaleva_terra",
     "ИИ-продавец · Терра", "aAoFNmfbAH9lNzIy"),
    ("pechkin08", "Ольга", "Никитина", "f4_office_laptop.jpg", "olga_nikitina_terra",
     "Контент-завод · Терра", "0xMVJYXk2v1kNDMy"),
    ("pechkin09", "Дарья", "Соловьёва", "f6_blonde_neon.jpg", "darya_solovyeva_terra",
     "ИИ в бизнес-процессах · Терра", "QJp69xWR-7c3YTEy"),
    ("pechkin10", "Наталья", "Ершова", "f1_cyber_implant.jpg", "natalia_ershova_terra",
     "Нейропродавец · Терра", "rB1fO7CvTHsxMTky"),
    ("pechkin11", "Светлана", "Орлова", "f7_cyber_gold.jpg", "svetlana_orlova_terra",
     "Вайбкодинг · Терра", "ewD7xEaauHs3NGUy"),
]


def proxies() -> dict[str, str]:
    out = {}
    for line in Path("proxies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ";" in line:
            name, url = line.split(";", 1)
            out[name.strip()] = url.strip()
    return out


async def restyle(acc, first, last, photo, username, role, invite, cfg, px):
    k, host, port, rdns, user, pwd = parse_proxy(px[acc])
    bio = f"{role}\nt.me/+{invite}"
    client = TelegramClient(acc, cfg["api_id"], cfg["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd),
                            connection_retries=2, request_retries=2, timeout=45)
    try:
        await client.connect()
        me = await client.get_me()

        await client(UpdateProfileRequest(first_name=first, last_name=last))

        got_user = me.username or ""
        if got_user != username:
            try:
                await client(UpdateUsernameRequest(username=username))
                got_user = username
            except (UsernameOccupiedError, UsernameInvalidError) as exc:
                got_user = f"занят ({type(exc).__name__})"

        uploaded = await client.upload_file(str(Path("media/uploads") / photo))
        await client(UploadProfilePhotoRequest(file=uploaded))

        await client(UpdateProfileRequest(first_name=first, last_name=last, about=bio))

        full = await client(GetFullUserRequest(me.id))
        about_now = full.full_user.about or ""
        photos = full.full_user.profile_photo
        ok_bio = role in about_now and invite in about_now
        return (f"{acc}: {first} {last} | @{got_user} | фото {'есть' if photos else 'НЕТ'} "
                f"| описание {'ок' if ok_bio else 'НЕ ЗАПИСАЛОСЬ: ' + about_now[:40]}")
    except Exception as exc:  # noqa: BLE001
        return f"{acc}: ОШИБКА {type(exc).__name__}: {str(exc)[:70]}"
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    cfg = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    px = proxies()
    for row in PEOPLE:
        if only and row[0] not in only:
            continue
        print(await restyle(*row, cfg[row[0]], px), flush=True)
        time.sleep(2)
    print("ГОТОВО", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
