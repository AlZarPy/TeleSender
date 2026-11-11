"""Оформление профиля купленного аккаунта — до прогрева.

Правило: пока профиль не готов, аккаунт в прогрев не идёт (warmup.should_tick
проверяет profile_ready). Оформление делает сразу четыре вещи:
  1. скрывает номер телефона от всех;
  2. ставит русское имя и фамилию;
  3. меняет юзернейм на схему пула (по умолчанию *_terra);
  4. добавляет описание и аватарку.

    python tools/prepare_profile.py --group a --dry-run
    python tools/prepare_profile.py --group a
    python tools/prepare_profile.py --accounts acct_c4,acct_c5
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config_loader import load_config_from_txt  # noqa: E402
from proxy_config import parse_proxy  # noqa: E402
from telethon import TelegramClient, functions  # noqa: E402
from telethon.tl.types import InputPrivacyKeyPhoneNumber, InputPrivacyValueDisallowAll  # noqa: E402

from panel import db  # noqa: E402

MEDIA = ROOT / "media"

# Имена: фамилия → юзернейм → аватарка → ниша в описании
PEOPLE = [
    {"first": "Ирина", "last": "Белова", "user": "irina_belova_terra", "avatar": "av_batch3_f1.png",
     "niche": "ИИ-агенты"},
    {"first": "Татьяна", "last": "Гусева", "user": "tatyana_guseva_terra", "avatar": "av_batch3_f2.png",
     "niche": "Контент-завод"},
    {"first": "Марина", "last": "Лебедева", "user": "marina_lebedeva_terra", "avatar": "av_holo_f3.png",
     "niche": "Нейропродавец"},
    {"first": "Юлия", "last": "Сорокина", "user": "yulia_sorokina_terra", "avatar": "av_holo_f4.png",
     "niche": "ИИ в бизнес-процессах"},
    {"first": "Ксения", "last": "Морозова", "user": "ksenia_morozova_terra", "avatar": "av_batch3_f2.png",
     "niche": "Вайбкодинг"},
    {"first": "Григорий", "last": "Фомин", "user": "grigory_fomin_terra", "avatar": "av_holo_m4.png",
     "niche": "ИИ-продавец"},
    {"first": "Артём", "last": "Захаров", "user": "artem_zakharov_terra", "avatar": "av_batch3_m1.png",
     "niche": "ИИ-агенты"},
    {"first": "Никита", "last": "Ершов", "user": "nikita_ershov_terra", "avatar": "av_batch3_m2.png",
     "niche": "Контент-завод"},
    {"first": "Роман", "last": "Тихонов", "user": "roman_tikhonov_terra", "avatar": "av_holo_m5.png",
     "niche": "Нейропродавец"},
    {"first": "Павел", "last": "Кузнецов", "user": "pavel_kuznetsov_terra", "avatar": "av_holo_m6.png",
     "niche": "Вайбкодинг"},
    {"first": "Степан", "last": "Орлов", "user": "stepan_orlov_terra", "avatar": "av_batch3_m3.png",
     "niche": "ИИ в бизнес-процессах"},
]

BIO = ("Куратор Школы взрывного роста AI, сообщества предпринимателей «Терра». "
       "Направление: {niche}. 13 ноября, Конгресс-центр ЦМТ, Москва — открытие 41-го потока.")


def proxy_map() -> dict[str, str]:
    out = {}
    for line in (ROOT / "proxies.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and ";" in line:
            name, url = line.split(";", 1)
            out[name] = url
    return out


async def prepare(name: str, person: dict, cfg: dict, px: dict, dry: bool) -> list[str]:
    lines: list[str] = []
    if name not in px:
        return [f"{name}: нет прокси — пропуск"]

    _k, host, port, rdns, user, pwd = parse_proxy(px[name])
    client = TelegramClient(name, cfg[name]["api_id"], cfg[name]["api_hash"],
                            proxy=("socks5", host, int(port), rdns, user, pwd),
                            connection_retries=1, request_retries=1, timeout=30)
    await client.connect()
    try:
        me = await client.get_me()
        lines.append(f"{name}: сейчас {me.first_name or '—'} @{me.username or '—'}")

        if dry:
            lines.append(f"   стало бы: {person['first']} {person['last']} @{person['user']}")
            return lines

        # 1. телефон скрыть от всех
        try:
            await client(functions.account.SetPrivacyRequest(
                key=InputPrivacyKeyPhoneNumber(),
                rules=[InputPrivacyValueDisallowAll()]))
            lines.append("   телефон скрыт")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"   ! телефон: {type(exc).__name__}")

        # 2. имя
        try:
            await client(functions.account.UpdateProfileRequest(
                first_name=person["first"], last_name=person["last"]))
            lines.append(f"   имя: {person['first']} {person['last']}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"   ! имя: {type(exc).__name__}")

        # 3. юзернейм
        try:
            await client(functions.account.UpdateUsernameRequest(username=person["user"]))
            lines.append(f"   юзернейм: @{person['user']}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"   ! юзернейм: {type(exc).__name__} (возможно занят)")

        # 4. описание
        try:
            await client(functions.account.UpdateProfileRequest(
                about=BIO.format(niche=person["niche"])[:70]))
            lines.append("   описание добавлено")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"   ! описание: {type(exc).__name__}")

        # 5. аватарка
        avatar = MEDIA / person["avatar"]
        if avatar.exists():
            try:
                await client(functions.photos.UploadProfilePhotoRequest(
                    file=await client.upload_file(str(avatar))))
                lines.append(f"   аватарка: {avatar.name}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"   ! аватарка: {type(exc).__name__}")
        else:
            lines.append(f"   ! нет файла аватарки {avatar.name}")

        db.execute("UPDATE accounts SET profile_ready=1, note=? WHERE session_name=?",
                   (f"{person['first']} {person['last']} @{person['user']} · {person['niche']}", name))
        return lines
    finally:
        await client.disconnect()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", default="")
    ap.add_argument("--group", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", type=int, default=0, help="перемешать выдачу имён")
    args = ap.parse_args()

    db.init()
    if args.accounts:
        names = [a.strip() for a in args.accounts.split(",") if a.strip()]
    elif args.all:
        names = [r["session_name"] for r in
                 db.q("SELECT session_name FROM accounts WHERE status='active' AND profile_ready=0 "
                      "ORDER BY session_name")]
    else:
        names = [r["session_name"] for r in
                 db.q("SELECT session_name FROM accounts WHERE status='active' AND grp=? "
                      "AND profile_ready=0 ORDER BY session_name", (args.group,))]
    if not names:
        print("некому оформлять: либо все готовы, либо группа пуста")
        return 0

    pool = list(PEOPLE)
    random.Random(args.seed).shuffle(pool)
    cfg = {a["session_name"]: a for a in load_config_from_txt(None, quiet=True)}
    px = proxy_map()

    for i, name in enumerate(names):
        person = pool[i % len(pool)]
        try:
            for line in await prepare(name, person, cfg, px, args.dry_run):
                print(line)
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: ОШИБКА {type(exc).__name__}: {str(exc)[:80]}")
        await asyncio.sleep(4)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
