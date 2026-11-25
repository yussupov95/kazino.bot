# -*- coding: utf-8 -*-
"""Кланы: склад, уровни, снаряжение, турниры 2 раза в день, топ, аватарка.

Что видно в беседе:  «клан», «клан НАЗВАНИЕ», «топ клан», «клан помощь», «клан принять», «клан чат».
Всё управление (склад, сила, снаряжение, улучшение) — только в ЛС боту, чтобы другие кланы
не узнали, сколько у вас денег и насколько вы сильны.

Данные лежат в bot.db в своих таблицах clans и clan_meta (database.py не менялся).
"""
import json
import os
import random
import re
import tempfile
import time
from datetime import datetime

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

import database as _dbm
from config import CHAT_OFFSET, DONATE_BOT_LINK, DONATE_PREFIX_BANNED, OWNER_ID, err_text, vk_upload
from database import DB_LOCK, freeze_left, get_user, save_economy, today_str
from helpers import (
    edit_message, fmt_num, freeze_text, get_names, mention, msg_photos, parse_amount, parse_target,
    send, send_dm,
)

# =====================================================================================
#                                    НАСТРОЙКИ
#  Всё, что хочется подкрутить (цены, награды, лимиты), лежит здесь.
# =====================================================================================
KK = 1_000_000

CREATE_COST = 10 * KK          # цена создания клана (деньги сразу уходят на склад клана)
NAME_MIN, NAME_MAX = 3, 20     # длина названия
MAX_MEMBERS = 20               # больше участников в клане быть не может

# уровень: сколько мест, во сколько обходится переход НА этот уровень (платится со склада)
LEVELS = {
    1: {"members": 3, "cost": 0, "perks": "склад · до 3 участников"},
    2: {"members": 5, "cost": 500 * KK, "perks": "до 5 участников · магазин: мечи, доспехи, щиты"},
    3: {"members": MAX_MEMBERS, "cost": 1000 * KK, "perks": "до 20 участников · аватарка клана в беседах"},
}
MAX_LEVEL = max(LEVELS)
SHOP_LEVEL = 2                 # с какого уровня открыт магазин снаряжения
AVATAR_LEVEL = 3               # с какого уровня можно поставить аватарку

# снаряжение: цена и прибавка к силе. Каждого вида можно держать не больше, чем участников в клане.
GEAR = {
    "sword":  {"forms": ("меч", "меча", "мечей"),       "icon": "⚔", "price": 25 * KK, "power": 60, "title": "Мечи"},
    "armor":  {"forms": ("доспех", "доспеха", "доспехов"), "icon": "🥋", "price": 25 * KK, "power": 40, "title": "Доспехи"},
    "shield": {"forms": ("щит", "щита", "щитов"),       "icon": "🛡", "price": 15 * KK, "power": 30, "title": "Щиты"},
}
GEAR_WORDS = {
    "меч": "sword", "мечи": "sword", "мечей": "sword", "меча": "sword",
    "доспех": "armor", "доспехи": "armor", "доспехов": "armor", "броня": "armor", "броню": "armor",
    "щит": "shield", "щиты": "shield", "щитов": "shield", "щита": "shield",
}

# сила и бои
P_MEMBER = 100                 # сила одного участника
BATTLE_LUCK = 0.10             # ±10% «удачи» в каждом бою (0 — побеждает строго сильнейший)
BATTLE_MIN_MEMBERS = 2         # в турнире участвуют кланы, где хотя бы столько человек
BATTLE_WINDOWS = ((10, 15), (17, 23))   # два боя в день в случайное время внутри этих окон (часы, время сервера)
BATTLE_LATE_LIMIT = 2 * 3600   # если бот был выключен и бой «опоздал» больше чем на это — бой пропускается
# место: (деньги на склад, репутация)
PRIZES = {1: (500 * KK, 3), 2: (250 * KK, 2), 3: (100 * KK, 1)}
LOSS_REP = -2                  # остальным участникам турнира
UNARMED_REP = -1               # у клана 2+ уровня мечей меньше, чем участников

INVITE_TTL = 24 * 3600         # сколько живёт приглашение
AVATAR_WAIT = 5 * 60           # сколько ждём фото после «клан ава»
CONFIRM_WAIT = 60              # подтверждение роспуска клана

# =====================================================================================
#                                  ХРАНИЛИЩЕ
# =====================================================================================
CLANS = {}                     # id (строкой) → клан
META = {"seq": 0, "battles": 0, "sched": {}}
_snap = {}                     # что уже записано в базу: id → json
_meta_snap = {}
_avatar_wait = {}              # игрок → до какого времени ждём фото
_confirm = {}                  # игрок → (действие, до какого времени)


def _db_init():
    with DB_LOCK:
        d = _dbm.db
        d.execute("CREATE TABLE IF NOT EXISTS clans (clan_id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
        d.execute("CREATE TABLE IF NOT EXISTS clan_meta (meta_key TEXT PRIMARY KEY, value TEXT)")
        for cid, raw in d.execute("SELECT clan_id, data FROM clans").fetchall():
            try:
                CLANS[str(cid)] = json.loads(raw)
                _snap[str(cid)] = raw
            except ValueError:
                print(f"Клан {cid}: не удалось прочитать данные")
        for key, raw in d.execute("SELECT meta_key, value FROM clan_meta").fetchall():
            try:
                META[key] = json.loads(raw)
                _meta_snap[key] = raw
            except ValueError:
                pass
    for c in CLANS.values():                      # клан из старой версии: добавляем недостающие поля
        for k, v in _new_clan_fields().items():
            c.setdefault(k, v)


def _new_clan_fields():
    return {"deputy": 0, "level": 1, "bank": 0, "sword": 0, "armor": 0, "shield": 0, "rep": 0,
            "titles": 0, "battles": 0, "wins": 0, "losses": 0, "avatar": "", "chat": 0,
            "deposits": {}, "invites": {}, "last": ""}


def save_clans():
    """Записывает в базу только изменившееся — одной транзакцией."""
    with DB_LOCK:
        rows = {cid: json.dumps(c, ensure_ascii=False, sort_keys=True) for cid, c in CLANS.items()}
        changed = [(int(cid), raw) for cid, raw in rows.items() if _snap.get(cid) != raw]
        gone = [(int(cid),) for cid in _snap if cid not in rows]
        meta = {k: json.dumps(v, ensure_ascii=False) for k, v in META.items()}
        meta_changed = [(k, raw) for k, raw in meta.items() if _meta_snap.get(k) != raw]
        if not (changed or gone or meta_changed):
            return
        d = _dbm.db
        d.execute("BEGIN")
        try:
            if changed:
                d.executemany("INSERT OR REPLACE INTO clans (clan_id, data) VALUES (?, ?)", changed)
            if gone:
                d.executemany("DELETE FROM clans WHERE clan_id = ?", gone)
            if meta_changed:
                d.executemany("INSERT OR REPLACE INTO clan_meta (meta_key, value) VALUES (?, ?)", meta_changed)
            d.execute("COMMIT")
        except Exception:
            d.execute("ROLLBACK")
            raise
        _snap.clear()
        _snap.update(rows)
        _meta_snap.clear()
        _meta_snap.update(meta)


# =====================================================================================
#                                  ВСПОМОГАТЕЛЬНОЕ
# =====================================================================================
def kk(n):
    """25000000 → «25кк», 1500000 → «1.5кк», 500 → «500 💰»."""
    n = int(n)
    if n and n % KK == 0:
        return f"{n // KK:,}кк".replace(",", " ")
    if abs(n) >= KK:
        return (f"{n / KK:.2f}".rstrip("0").rstrip(".")) + "кк"
    return f"{fmt_num(n)} 💰"


def plural(n, forms):
    n = abs(int(n))
    if 11 <= n % 100 <= 14:
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if 2 <= n % 10 <= 4 else forms[2]


def fmt_date(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y")


def _norm(s):
    return str(s).lower().replace("ё", "е").strip()


def clan_of(uid):
    for c in CLANS.values():
        if uid in c["members"]:
            return c
    return None


def level_cap(c):
    return LEVELS[c["level"]]["members"]


def is_owner(c, uid):
    return c["owner"] == uid


def can_manage(c, uid):
    return c["owner"] == uid or c.get("deputy") == uid


def power(c):
    n = len(c["members"])
    total = n * P_MEMBER
    for kind, g in GEAR.items():
        total += min(c[kind], n) * g["power"]
    return total


def power_max(c):
    n = len(c["members"])
    return n * (P_MEMBER + sum(g["power"] for g in GEAR.values()))


def _say(peer_id, text, keyboard=None, attachment=None):
    """Сообщение, которое не должно ронять бота."""
    try:
        send(peer_id, text, keyboard, attachment)
        return True
    except Exception as e:
        if attachment:                       # не открылась картинка — шлём текстом
            try:
                send(peer_id, text, keyboard)
                return True
            except Exception as e2:
                e = e2
        print(f"Клан: не удалось написать {peer_id}: {err_text(e)}")
        return False


def _dm(uid, text, keyboard=None):
    try:
        return send_dm(uid, text, keyboard)
    except Exception as e:
        print(f"Клан: не удалось написать игроку {uid} в ЛС: {err_text(e)}")
        return None


def _notify_staff(c, text, skip=0):
    for uid in {c["owner"], c.get("deputy") or 0}:
        if uid and uid != skip:
            _dm(uid, text)


def _need_dm(msg):
    """True — команда управления вызвана в беседе: объяснили, что писать надо в ЛС."""
    if msg["peer_id"] >= CHAT_OFFSET:
        send(msg["peer_id"],
             "🔒 Управление кланом — только в личных сообщениях боту: там же вся подробная информация о клане.\n"
             f"Откройте диалог: {DONATE_BOT_LINK} — и напишите «клан помощь».")
        return True
    return False


NAME_RE = re.compile(r"^\w[\w \-]{1,18}\w$")


def clean_name(text):
    return re.sub(r"\s+", " ", str(text).strip().strip("«»\"'")).strip()


def find_clan(text, exact=False):
    t = _norm(clean_name(text))
    if not t:
        return None
    for c in CLANS.values():
        if _norm(c["name"]) == t:
            return c
    if exact:
        return None
    hits = [c for c in CLANS.values() if _norm(c["name"]).startswith(t)]
    return hits[0] if len(hits) == 1 else None


def name_error(name):
    if not NAME_RE.match(name):
        return (f"⚠ Название: от {NAME_MIN} до {NAME_MAX} символов — буквы, цифры, пробел, «_» и «-». "
                "Пример: клан создать Тёмные волки")
    low = _norm(name)
    if any(b in low for b in DONATE_PREFIX_BANNED):
        return "⛔ Такое название нельзя: оно похоже на роль персонала или VIP. Придумайте другое."
    if find_clan(name, exact=True):
        return "⚠ Клан с таким названием уже есть."
    return None


def _rank_list():
    """Кланы по репутации: больше репутации → больше титулов → больше участников → старше."""
    return sorted(CLANS.values(), key=lambda c: (-c["rep"], -c["titles"], -len(c["members"]), c["created"]))


def _clean_invites(c):
    now = time.time()
    for uid in [u for u, inv in c["invites"].items() if now - inv.get("t", 0) > INVITE_TTL]:
        del c["invites"][uid]


# =====================================================================================
#                           КАРТОЧКИ: ПУБЛИЧНАЯ (БЕСЕДА) И ПОЛНАЯ (ЛС)
# =====================================================================================
def public_card(c):
    """Для беседы: только то, что не раскрывает сильных и слабых сторон клана."""
    names = get_names(list(c["members"]))
    lines = [f"🏰 Клан «{c['name']}»", ""]
    lines.append(f"👑 Владелец: {mention(c['owner'], names)}")
    lines.append(f"🎖 Зам: {mention(c['deputy'], names) if c.get('deputy') else 'нет'}")
    lines.append(f"⭐ Репутация: {c['rep']}")
    lines.append(f"🏆 Побед в турнирах: {c['titles']}")
    lines.append(f"📅 Основан: {fmt_date(c['created'])}")
    lines.append("")
    lines.append(f"👥 Участники ({len(c['members'])}):")
    for i, uid in enumerate(c["members"], 1):
        mark = "👑 " if uid == c["owner"] else "🎖 " if uid == c.get("deputy") else ""
        lines.append(f"{i}. {mark}{mention(uid, names)}")
    return "\n".join(lines)


def _battles_left_today():
    sched = META.get("sched") or {}
    if sched.get("day") != today_str():
        return len(BATTLE_WINDOWS)
    return sum(1 for d in sched.get("done", []) if not d)


def private_card(c, uid):
    names = get_names(list(c["members"]))
    n = len(c["members"])
    cap = level_cap(c)
    lines = [f"🏰 Клан «{c['name']}» · {c['level']} ур.", ""]
    lines.append(f"💰 Склад: {kk(c['bank'])}  (деньги со склада забрать нельзя)")
    lines.append(f"⭐ Репутация: {c['rep']}   🏆 Титулов: {c['titles']}")
    lines.append(f"⚔ Битв: {c['battles']} (побед в боях: {c['wins']}, поражений: {c['losses']})")
    lines.append(f"💪 Сила клана: {power(c)} из {power_max(c)} возможных")
    lines.append(f"👥 Участники: {n}/{cap}")
    lines.append("")
    if c["level"] >= SHOP_LEVEL:
        lines.append("🛒 Снаряжение (не больше, чем участников):")
        for kind, g in GEAR.items():
            lines.append(f"{g['icon']} {g['title']}: {c[kind]}/{n} · {kk(g['price'])} за штуку")
        lines.append("Купить: «купить мечи 5», «купить щиты 5», «купить доспехи 5»")
    else:
        lines.append(f"🔒 Магазин снаряжения откроется на {SHOP_LEVEL} уровне.")
    lines.append("")
    if c["level"] < MAX_LEVEL:
        nxt = c["level"] + 1
        cost = LEVELS[nxt]["cost"]
        need = max(0, cost - c["bank"])
        lines.append(f"📈 Следующий уровень ({nxt}): {kk(cost)} — "
                     + ("хватает! «клан улучшить»" if not need else f"не хватает {kk(need)}"))
        lines.append(f"   Даст: {LEVELS[nxt]['perks']}")
    else:
        lines.append("📈 Максимальный уровень достигнут.")
    if c["level"] >= AVATAR_LEVEL:
        lines.append("🖼 Аватарка: " + ("стоит" if c.get("avatar") else "не задана — «клан ава»"))
    lines.append(f"⏰ Битв сегодня осталось: {_battles_left_today()} (время случайное)")
    if c.get("last"):
        lines.append(f"📜 Последняя битва: {c['last']}")
    lines.append("")
    lines.append("👥 Участники и вклад в склад:")
    for i, m in enumerate(sorted(c["members"], key=lambda x: -c["deposits"].get(str(x), 0)), 1):
        mark = "👑 " if m == c["owner"] else "🎖 " if m == c.get("deputy") else ""
        lines.append(f"{i}. {mark}{mention(m, names)} — {kk(c['deposits'].get(str(m), 0))}")
    _clean_invites(c)
    if c["invites"]:
        lines.append(f"\n📨 Ждут ответа на приглашение: {len(c['invites'])}")
    return "\n".join(lines)


def _send_public(peer_id, c):
    text = public_card(c)
    att = c.get("avatar") if c["level"] >= AVATAR_LEVEL else None
    _say(peer_id, text, attachment=att or None)


# =====================================================================================
#                                      ПОМОЩЬ
# =====================================================================================
def help_text(uid=0):
    g = GEAR
    lines = [
        "🏰 КЛАНЫ",
        "Свой клан: склад, участники, снаряжение и турниры против других кланов. "
        "Побеждайте — получайте деньги на склад и репутацию!",
        "",
        "📩 Управление — только в ЛС боту:",
        f"• клан создать НАЗВАНИЕ — создать клан ({kk(CREATE_COST)}, деньги идут на склад)",
        "• клан — подробная информация о вашем клане",
        "• клан положить СУММА — пополнить склад (забрать деньги нельзя!)",
        "• клан добавить ID / ссылку — пригласить игрока (владелец и зам)",
        "• клан принять — принять приглашение (работает и в беседе)",
        "• клан выгнать ID — исключить участника (владелец и зам)",
        "• клан зам ID — назначить зама, «клан зам снять» — снять (владелец)",
        "• клан улучшить — поднять уровень за деньги склада (владелец)",
        "• клан ава — поставить аватарку, потом пришлите фото (владелец, 3 ур.)",
        "• купить мечи 5 / купить щиты 5 / купить доспехи 5 — снаряжение (со склада)",
        "• клан выйти — покинуть клан · клан распустить — удалить клан (склад пропадёт)",
        "",
        "💬 В беседе работают:",
        "• клан — карточка вашего клана · клан НАЗВАНИЕ — чужой клан",
        "• топ клан — лучшие кланы по репутации",
        "• клан чат — итоги турниров будут приходить в эту беседу (владелец и зам)",
        "",
        "📈 Уровни:",
    ]
    for lvl, info in LEVELS.items():
        price = "бесплатно" if not info["cost"] else kk(info["cost"])
        lines.append(f"{lvl} ур. ({price}): {info['perks']}")
    lines += [
        "",
        "🛒 Снаряжение (каждого вида — не больше, чем участников):",
        f"⚔ меч {kk(g['sword']['price'])} · 🥋 доспехи {kk(g['armor']['price'])} · 🛡 щит {kk(g['shield']['price'])}",
        "",
        "⚔ Турниры: 2 раза в день в случайное время все кланы (от "
        f"{BATTLE_MIN_MEMBERS} участников) сражаются на вылет. Сила = участники + снаряжение. "
        "Сильнее клан — больше шансов.",
        f"🥇 {kk(PRIZES[1][0])} и +{PRIZES[1][1]} репутации · 🥈 {kk(PRIZES[2][0])} и +{PRIZES[2][1]} · "
        f"🥉 {kk(PRIZES[3][0])} и +{PRIZES[3][1]}. Остальные: {LOSS_REP} репутации.",
        f"⚠ Если у клана {SHOP_LEVEL}+ уровня мечей меньше, чем участников, в бою репутация ещё {UNARMED_REP}.",
        "Максимум участников в клане — 20.",
    ]
    if uid == OWNER_ID:
        lines += ["", "👑 Владелец бота: клан битва — турнир прямо сейчас · клан удалить НАЗВАНИЕ · клан сброс НАЗВАНИЕ (убрать аватарку)"]
    return "\n".join(lines)


# =====================================================================================
#                                     КОМАНДЫ
# =====================================================================================
def _no_clan_text():
    return ("ℹ️ Вы не состоите в клане.\n"
            "• Посмотреть лучших: «топ клан»\n"
            f"• Создать свой ({kk(CREATE_COST)}): в ЛС боту «клан создать НАЗВАНИЕ»\n"
            "• Все команды: «клан помощь»")


def do_show(msg, uid, tail):
    peer_id = msg["peer_id"]
    in_chat = peer_id >= CHAT_OFFSET
    own = clan_of(uid)
    if tail.strip():
        c = find_clan(tail)
        if not c:
            send(peer_id, "ℹ️ Клан с таким названием не найден. Список лучших: «топ клан»")
            return
        if not in_chat and own and own is c:
            send(peer_id, private_card(c, uid))
            return
        _send_public(peer_id, c)
        return
    if not own:
        send(peer_id, _no_clan_text())
        return
    if in_chat:
        _send_public(peer_id, own)
    else:
        send(peer_id, private_card(own, uid))
        if own["level"] >= AVATAR_LEVEL and own.get("avatar"):
            pass  # аватарка показывается в беседах; в ЛС карточка остаётся текстом


def do_help(msg, uid, tail):
    send(msg["peer_id"], help_text(uid))


def do_top(msg, uid, tail):
    ranked = _rank_list()
    if not ranked:
        send(msg["peer_id"], "🏆 Топ кланов пока пуст. Станьте первыми: в ЛС боту «клан создать НАЗВАНИЕ»")
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 Топ кланов по репутации", ""]
    for i, c in enumerate(ranked[:10], 1):
        lines.append(f"{medals.get(i, str(i) + '.')} {c['name']} — ⭐ {c['rep']} · 👥 {len(c['members'])} · 🏆 {c['titles']}")
    own = clan_of(uid)
    if own and own not in ranked[:10]:
        lines += ["", f"Ваш клан «{own['name']}»: {ranked.index(own) + 1}-е место"]
    lines += ["", "Репутация меняется после каждого турнира (2 раза в день). Подробнее: «клан помощь»"]
    send(msg["peer_id"], "\n".join(lines))


def do_create(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    own = clan_of(uid)
    if own:
        send(peer_id, f"⚠ Вы уже состоите в клане «{own['name']}». Сначала выйдите: «клан выйти».")
        return
    name = clean_name(tail)
    if not name:
        send(peer_id, f"ℹ️ Создать клан: клан создать НАЗВАНИЕ\nПример: клан создать Тёмные волки\nЦена: {kk(CREATE_COST)} — они сразу попадут на склад клана.")
        return
    err = name_error(name)
    if err:
        send(peer_id, err)
        return
    user = get_user(uid)
    if user["money"] < CREATE_COST:
        send(peer_id, f"⚠ Не хватает денег: клан стоит {kk(CREATE_COST)}, у вас {kk(user['money'])}.")
        return
    user["money"] -= CREATE_COST
    META["seq"] = int(META.get("seq", 0)) + 1
    c = {"id": META["seq"], "name": name, "owner": uid, "members": [uid], "created": time.time(),
         **_new_clan_fields()}
    c["bank"] = CREATE_COST
    c["deposits"][str(uid)] = CREATE_COST
    CLANS[str(c["id"])] = c
    save_clans()
    save_economy()
    send(peer_id, f"🎉 Клан «{name}» создан! Вы — владелец.\n\n"
                  f"💰 На складе: {kk(c['bank'])} (забрать деньги со склада нельзя)\n"
                  f"👥 Места: до {level_cap(c)} участников\n\n"
                  "Что дальше:\n"
                  "• клан добавить ID — пригласить друзей\n"
                  "• клан положить СУММА — пополнить склад\n"
                  f"• клан улучшить — {LEVELS[2]['perks']} ({kk(LEVELS[2]['cost'])})\n"
                  "• В нужной беседе напишите «клан чат» — туда будут приходить итоги турниров\n"
                  "• Все команды: «клан помощь»")


def do_deposit(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    amount = parse_amount(tail.split()[0]) if tail.split() else None   # без «все»: случайно не вложить всё
    if amount is None:
        send(peer_id, "ℹ️ Пополнить склад: клан положить СУММА\nПример: клан положить 50кк\n"
                      "⚠ Забрать деньги со склада потом нельзя — только тратить на улучшения и снаряжение.")
        return
    user = get_user(uid)
    if amount > user["money"]:
        send(peer_id, f"⚠ Недостаточно денег. Ваш баланс: {kk(user['money'])}")
        return
    user["money"] -= amount
    c["bank"] += amount
    c["deposits"][str(uid)] = c["deposits"].get(str(uid), 0) + amount
    save_clans()
    save_economy()
    send(peer_id, f"✅ Вы положили {kk(amount)} на склад клана «{c['name']}».\n"
                  f"💰 Склад: {kk(c['bank'])}\n📊 Ваш общий вклад: {kk(c['deposits'][str(uid)])}")


def _invite_keyboard(c, target):
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Вступить", VkKeyboardColor.POSITIVE, {"cmd": "clan", "act": "yes", "c": c["id"], "u": target})
    kb.add_callback_button("❌ Отказать", VkKeyboardColor.NEGATIVE, {"cmd": "clan", "act": "no", "c": c["id"], "u": target})
    return kb.get_keyboard()


def do_invite(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if not can_manage(c, uid):
        send(peer_id, "⛔ Приглашать могут владелец и зам клана.")
        return
    target, _ = parse_target(msg, tail)
    if target is None:
        send(peer_id, "ℹ️ Пригласить: клан добавить ID (или ссылка на страницу VK)\nПример: клан добавить 123456789")
        return
    if target <= 0 or target == uid:
        send(peer_id, "⚠ Этого игрока пригласить нельзя.")
        return
    other = clan_of(target)
    if other:
        send(peer_id, "⚠ Этот игрок уже состоит в клане." if other is not c else "⚠ Этот игрок уже в вашем клане.")
        return
    if len(c["members"]) >= level_cap(c):
        nxt = c["level"] + 1
        hint = (f" Улучшите клан до {nxt} ур. ({kk(LEVELS[nxt]['cost'])}): «клан улучшить»." if c["level"] < MAX_LEVEL else "")
        send(peer_id, f"⚠ В клане нет мест: {len(c['members'])}/{level_cap(c)}.{hint}")
        return
    _clean_invites(c)
    if str(target) in c["invites"]:
        send(peer_id, "ℹ️ Приглашение этому игроку уже отправлено. Оно действует 24 часа.")
        return
    c["invites"][str(target)] = {"t": time.time(), "by": uid}
    save_clans()
    names = get_names([uid, target])
    text = (f"📨 {names.get(uid, 'Игрок')} приглашает вас в клан «{c['name']}»\n"
            f"👥 Участников: {len(c['members'])} · ⭐ Репутация: {c['rep']}\n\n"
            "Приглашение действует 24 часа. Если кнопки не работают, напишите боту: клан принять")
    if _dm(target, text, _invite_keyboard(c, target)) is None:
        send(peer_id, f"📨 Приглашение для {mention(target, names)} создано, но бот не смог написать ему в ЛС.\n"
                      f"Пусть откроет диалог с ботом ({DONATE_BOT_LINK}) и напишет «клан принять».")
        return
    send(peer_id, f"📨 Приглашение отправлено: {mention(target, names)}. Ждём ответа (24 часа).")


def _join(uid, c):
    """(успех, текст). Игрок принимает приглашение в клан c."""
    if clan_of(uid):
        return False, "Вы уже состоите в клане."
    _clean_invites(c)
    if str(uid) not in c["invites"]:
        return False, "Приглашение устарело или отозвано."
    if len(c["members"]) >= level_cap(c):
        return False, "В клане уже нет мест."
    c["members"].append(uid)
    for other in CLANS.values():
        other["invites"].pop(str(uid), None)
    save_clans()
    return True, f"✅ Вы вступили в клан «{c['name']}»! Информация: «клан» (в ЛС боту — подробная)."


def do_accept(msg, uid, tail):
    peer_id = msg["peer_id"]
    if clan_of(uid):
        send(peer_id, "⚠ Вы уже состоите в клане.")
        return
    mine = []
    for c in CLANS.values():
        _clean_invites(c)
        if str(uid) in c["invites"]:
            mine.append(c)
    if not mine:
        send(peer_id, "ℹ️ Для вас нет действующих приглашений в клан.")
        return
    if tail.strip():
        c = find_clan(tail)
        if c not in mine:
            send(peer_id, "ℹ️ Приглашения от клана с таким названием нет.")
            return
    elif len(mine) == 1:
        c = mine[0]
    else:
        send(peer_id, "ℹ️ У вас несколько приглашений: " + ", ".join(f"«{x['name']}»" for x in mine)
             + "\nНапишите: клан принять НАЗВАНИЕ")
        return
    ok, text = _join(uid, c)
    send(peer_id, text)
    if ok:
        names = get_names([uid])
        _notify_staff(c, f"👥 {mention(uid, names)} вступил(а) в клан «{c['name']}». Участников: {len(c['members'])}/{level_cap(c)}")


def do_decline(msg, uid, tail):
    peer_id = msg["peer_id"]
    removed = 0
    for c in CLANS.values():
        if c["invites"].pop(str(uid), None):
            removed += 1
    if removed:
        save_clans()
    send(peer_id, "✅ Приглашения отклонены." if removed else "ℹ️ Приглашений для вас нет.")


def do_kick(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if not can_manage(c, uid):
        send(peer_id, "⛔ Исключать могут владелец и зам клана.")
        return
    target, _ = parse_target(msg, tail)
    if target is None:
        send(peer_id, "ℹ️ Исключить: клан выгнать ID\nПример: клан выгнать 123456789")
        return
    if target not in c["members"]:
        send(peer_id, "⚠ Этого игрока нет в вашем клане.")
        return
    if target == c["owner"]:
        send(peer_id, "⛔ Владельца клана исключить нельзя.")
        return
    if target == uid:
        send(peer_id, "ℹ️ Чтобы покинуть клан, напишите «клан выйти».")
        return
    if target == c.get("deputy") and uid != c["owner"]:
        send(peer_id, "⛔ Зама может исключить только владелец.")
        return
    c["members"].remove(target)
    if c.get("deputy") == target:
        c["deputy"] = 0
    save_clans()
    names = get_names([target])
    send(peer_id, f"✅ {mention(target, names)} исключён(а) из клана. Участников: {len(c['members'])}/{level_cap(c)}")
    _dm(target, f"🚪 Вас исключили из клана «{c['name']}».")


def do_deputy(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if not is_owner(c, uid):
        send(peer_id, "⛔ Назначать зама может только владелец клана.")
        return
    if _norm(tail) in ("снять", "убрать", "нет", "0", "-"):
        if not c.get("deputy"):
            send(peer_id, "ℹ️ У клана нет зама.")
            return
        old, c["deputy"] = c["deputy"], 0
        save_clans()
        send(peer_id, "✅ Зам снят.")
        _dm(old, f"🎖 Вас сняли с должности зама клана «{c['name']}».")
        return
    target, _ = parse_target(msg, tail)
    if target is None:
        send(peer_id, "ℹ️ Назначить зама: клан зам ID · снять: клан зам снять")
        return
    if target not in c["members"] or target == c["owner"]:
        send(peer_id, "⚠ Зама можно назначить только из участников клана (кроме владельца).")
        return
    c["deputy"] = target
    save_clans()
    names = get_names([target])
    send(peer_id, f"✅ {mention(target, names)} назначен(а) замом клана. Зам может приглашать, исключать и покупать снаряжение.")
    _dm(target, f"🎖 Вас назначили замом клана «{c['name']}».")


def do_leave(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if is_owner(c, uid):
        send(peer_id, "⛔ Владелец не может выйти из клана. Если клан не нужен — «клан распустить» (склад пропадёт).")
        return
    c["members"].remove(uid)
    if c.get("deputy") == uid:
        c["deputy"] = 0
    save_clans()
    send(peer_id, f"🚪 Вы покинули клан «{c['name']}». Деньги, которые вы вложили, остаются на его складе.")
    names = get_names([uid])
    _notify_staff(c, f"🚪 {mention(uid, names)} покинул(а) клан «{c['name']}».")


def do_upgrade(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if not is_owner(c, uid):
        send(peer_id, "⛔ Улучшать клан может только владелец.")
        return
    if c["level"] >= MAX_LEVEL:
        send(peer_id, "🏆 У клана уже максимальный уровень.")
        return
    nxt = c["level"] + 1
    cost = LEVELS[nxt]["cost"]
    if c["bank"] < cost:
        send(peer_id, f"⚠ На складе не хватает {kk(cost - c['bank'])}: для {nxt} уровня нужно {kk(cost)}, на складе {kk(c['bank'])}.\n"
                      "Пополнить: клан положить СУММА")
        return
    c["bank"] -= cost
    c["level"] = nxt
    save_clans()
    extra = ""
    if nxt == SHOP_LEVEL:
        extra = "\n🛒 Открыт магазин: «купить мечи 5», «купить щиты 5», «купить доспехи 5»."
    if nxt >= AVATAR_LEVEL:
        extra += "\n🖼 Можно поставить аватарку: «клан ава»."
    send(peer_id, f"🎉 Клан «{c['name']}» теперь {nxt} уровня!\nДоступно: {LEVELS[nxt]['perks']}.\n"
                  f"💰 Склад: {kk(c['bank'])}{extra}")
    _notify_staff(c, f"📈 Клан «{c['name']}» улучшен до {nxt} уровня.", skip=uid)


def do_gear(msg, uid, kind, tail):
    """«купить мечи 10» и т.п. Покупается за деньги склада."""
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    g = GEAR[kind]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if not can_manage(c, uid):
        send(peer_id, "⛔ Покупать снаряжение могут владелец и зам клана.")
        return
    if c["level"] < SHOP_LEVEL:
        send(peer_id, f"🔒 Магазин снаряжения откроется на {SHOP_LEVEL} уровне ({kk(LEVELS[SHOP_LEVEL]['cost'])}). «клан улучшить»")
        return
    n_members = len(c["members"])
    room = n_members - c[kind]
    word = tail.split()[0].lower() if tail.split() else ""
    if word in ("макс", "все", "всё", "max"):
        n = min(room, c["bank"] // g["price"])
    elif word.isdigit():
        n = int(word)
    else:
        send(peer_id, f"ℹ️ Купить: купить {g['title'].lower()} КОЛИЧЕСТВО (или «макс»)\n"
                      f"Цена: {kk(g['price'])} за штуку. Сейчас: {c[kind]}/{n_members}.")
        return
    if room <= 0:
        send(peer_id, f"⚠ {g['title']} уже куплены на всех: {c[kind]}/{n_members}. "
                      "Больше, чем участников в клане, купить нельзя.")
        return
    if n <= 0:
        send(peer_id, f"⚠ На складе не хватает денег даже на один ({kk(g['price'])}). Склад: {kk(c['bank'])}")
        return
    if n > room:
        send(peer_id, f"⚠ Можно купить не больше {room} {plural(room, g['forms'])}: больше, чем участников в клане, держать нельзя.")
        return
    cost = n * g["price"]
    if cost > c["bank"]:
        send(peer_id, f"⚠ Не хватает {kk(cost - c['bank'])}: {n} {plural(n, g['forms'])} стоят {kk(cost)}, на складе {kk(c['bank'])}.")
        return
    c["bank"] -= cost
    c[kind] += n
    save_clans()
    send(peer_id, f"✅ Куплено: {n} {plural(n, g['forms'])} за {kk(cost)}.\n"
                  f"{g['icon']} {g['title']}: {c[kind]}/{n_members} · 💪 Сила: {power(c)}\n💰 Склад: {kk(c['bank'])}")


def do_avatar(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if not is_owner(c, uid):
        send(peer_id, "⛔ Аватарку может ставить только владелец клана.")
        return
    if c["level"] < AVATAR_LEVEL:
        send(peer_id, f"🔒 Аватарка открывается на {AVATAR_LEVEL} уровне ({kk(LEVELS[AVATAR_LEVEL]['cost'])}). «клан улучшить»")
        return
    if _norm(tail) in ("удалить", "убрать", "снять"):
        c["avatar"] = ""
        save_clans()
        send(peer_id, "✅ Аватарка клана убрана.")
        return
    if msg_photos(msg):
        _set_avatar(msg, uid, c)
        return
    _avatar_wait[uid] = time.time() + AVATAR_WAIT
    send(peer_id, "🖼 Пришлите фото для аватарки клана следующим сообщением (в течение 5 минут). Отмена: «отмена».\n"
                  "Она будет показываться, когда в беседе пишут «клан». Неподходящие фото владелец бота удаляет.")


def _rehost_photo(msg):
    """Фото из сообщения → фото сообщества (не пропадёт и откроется в любой беседе)."""
    photos = [a["photo"] for a in (msg.get("attachments") or []) if a.get("type") == "photo"]
    if not photos:
        return None
    try:
        import requests
        sizes = photos[0].get("sizes") or []
        best = max(sizes, key=lambda s: (s.get("width") or 0) * (s.get("height") or 0))
        resp = requests.get(best["url"], timeout=20)
        resp.raise_for_status()
        if len(resp.content) > 15 * 1024 * 1024:
            raise ValueError("слишком большой файл")
        fd, path = tempfile.mkstemp(suffix=".jpg")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(resp.content)
            up = vk_upload.photo_messages(path)[0]
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        return f"photo{up['owner_id']}_{up['id']}"
    except Exception as e:
        print(f"Клан: не удалось перезалить аватарку, использую исходное фото: {err_text(e)}")
    return (msg_photos(msg) or "").split(",")[0] or None


def _set_avatar(msg, uid, c):
    att = _rehost_photo(msg)
    if not att:
        send(msg["peer_id"], "⚠ Не нашёл фото в сообщении. Пришлите картинку (как фото, не файлом).")
        return
    c["avatar"] = att
    save_clans()
    send(msg["peer_id"], "✅ Аватарка клана установлена! Теперь она видна, когда в беседе пишут «клан».")


def do_disband(msg, uid, tail):
    if _need_dm(msg):
        return
    peer_id = msg["peer_id"]
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if not is_owner(c, uid):
        send(peer_id, "⛔ Распустить клан может только владелец.")
        return
    pending = _confirm.get(uid)
    if _norm(tail) in ("подтвердить", "да", "confirm") and pending and pending[0] == "disband" and pending[1] > time.time():
        _confirm.pop(uid, None)
        del CLANS[str(c["id"])]
        save_clans()
        send(peer_id, f"🗑 Клан «{c['name']}» распущен. Склад ({kk(c['bank'])}) пропал безвозвратно.")
        for m in c["members"]:
            if m != uid:
                _dm(m, f"🗑 Клан «{c['name']}» распущен владельцем.")
        return
    _confirm[uid] = ("disband", time.time() + CONFIRM_WAIT)
    send(peer_id, f"⚠ Распустить клан «{c['name']}»? Склад ({kk(c['bank'])}) пропадёт навсегда, участники останутся без клана.\n"
                  "Если уверены, в течение минуты напишите: клан распустить подтвердить")


def do_chat(msg, uid, tail):
    peer_id = msg["peer_id"]
    if peer_id < CHAT_OFFSET:
        send(peer_id, "ℹ️ Эту команду пишут в беседе, куда нужно присылать итоги турниров вашего клана.")
        return
    c = clan_of(uid)
    if not c:
        send(peer_id, _no_clan_text())
        return
    if not can_manage(c, uid):
        send(peer_id, "⛔ Выбрать беседу для итогов могут владелец и зам клана.")
        return
    c["chat"] = peer_id
    save_clans()
    send(peer_id, f"✅ Итоги турниров клана «{c['name']}» теперь будут приходить в эту беседу.")


# ---- команды владельца бота ----
def do_admin_battle(msg, uid, tail):
    if uid != OWNER_ID:
        return
    text = run_battle(forced=True)
    if text is None:
        send(msg["peer_id"], f"ℹ️ Для турнира нужно минимум 2 клана, в каждом от {BATTLE_MIN_MEMBERS} участников.")


def do_admin_delete(msg, uid, tail):
    if uid != OWNER_ID:
        return
    c = find_clan(tail, exact=True)
    if not c:
        send(msg["peer_id"], "ℹ️ Использование: клан удалить ТОЧНОЕ_НАЗВАНИЕ")
        return
    del CLANS[str(c["id"])]
    save_clans()
    send(msg["peer_id"], f"🗑 Клан «{c['name']}» удалён.")


def do_admin_clear_avatar(msg, uid, tail):
    if uid != OWNER_ID:
        return
    c = find_clan(tail)
    if not c:
        send(msg["peer_id"], "ℹ️ Использование: клан сброс НАЗВАНИЕ — убрать аватарку клана")
        return
    c["avatar"] = ""
    save_clans()
    send(msg["peer_id"], f"✅ Аватарка клана «{c['name']}» убрана.")


# =====================================================================================
#                                   ТУРНИР КЛАНОВ
# =====================================================================================
def _fight(a, b):
    pa = power(a) * (1 + random.uniform(-BATTLE_LUCK, BATTLE_LUCK))
    pb = power(b) * (1 + random.uniform(-BATTLE_LUCK, BATTLE_LUCK))
    if pa == pb:
        pa += random.random()
    return (a, b) if pa > pb else (b, a)


def simulate(parts):
    """Турнир на вылет. Возвращает (1-е, 2-е, 3-е место, список боёв (раунд, победитель, проигравший))."""
    current = parts[:]
    random.shuffle(current)
    matches, semi_losers, second = [], [], None
    rnd = 0
    while len(current) > 1:
        rnd += 1
        pool = current[:]
        bye = pool.pop() if len(pool) % 2 else None      # нечётное число: последний по жребию проходит без боя
        nxt, losers = [], []
        for i in range(0, len(pool), 2):
            w, l = _fight(pool[i], pool[i + 1])
            matches.append((rnd, w, l))
            nxt.append(w)
            losers.append(l)
        if bye is not None:
            nxt.append(bye)
        if len(current) in (3, 4):
            semi_losers = losers
        if len(current) == 2:
            second = losers[0]
        current = nxt
    winner = current[0]
    third = None
    if len(semi_losers) == 2:
        third, loser = _fight(semi_losers[0], semi_losers[1])
        matches.append((0, third, loser))                # бой за 3-е место
    elif len(semi_losers) == 1:
        third = semi_losers[0]
    return winner, second, third, matches


def run_battle(forced=False):
    """Проводит турнир, раздаёт награды, шлёт итоги. None — кланов для турнира не хватило."""
    parts = [c for c in CLANS.values() if len(c["members"]) >= BATTLE_MIN_MEMBERS]
    if len(parts) < 2:
        return None
    unarmed = {c["id"] for c in parts if c["level"] >= SHOP_LEVEL and c["sword"] < len(c["members"])}
    winner, second, third, matches = simulate(parts)
    META["battles"] = int(META.get("battles", 0)) + 1
    number = META["battles"]
    places = {c["id"]: p for p, c in enumerate((winner, second, third), 1) if c}
    result = {}
    for c in parts:
        place = places.get(c["id"])
        prize, rep = PRIZES[place] if place else (0, LOSS_REP)
        if c["id"] in unarmed:
            rep += UNARMED_REP
        before = c["rep"]
        c["rep"] = max(0, c["rep"] + rep)
        c["bank"] += prize
        c["battles"] += 1
        if place == 1:
            c["titles"] += 1
        c["last"] = (f"№{number}, {place}-е место" if place else f"№{number}, вылет") + (f", +{kk(prize)}" if prize else "")
        result[c["id"]] = {"place": place, "prize": prize, "rep": c["rep"] - before, "unarmed": c["id"] in unarmed}
    for _, w, l in matches:
        w["wins"] += 1
        l["losses"] += 1
    save_clans()

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"⚔ Турнир кланов №{number} завершён!", ""]
    for place, c in ((1, winner), (2, second), (3, third)):
        if c:
            prize, rep = PRIZES[place]
            lines.append(f"{medals[place]} «{c['name']}» — +{kk(prize)} на склад, репутация +{rep}")
    rest = len(parts) - len(places)
    if rest:
        lines.append(f"Остальные кланы ({rest}): репутация {LOSS_REP}")
    shown = matches[-4:]
    last_round = max(r for r, _, _ in matches)
    if shown:
        lines += ["", "Последние бои:"]
        for rnd, w, l in shown:
            label = "За 3-е место" if rnd == 0 else "Финал" if rnd == last_round else "Бой"
            lines.append(f"• {label}: «{w['name']}» победил «{l['name']}»")
    lines += ["", "Таблица лучших: «топ клан»"]
    public = "\n".join(lines)

    for peer in {c["chat"] for c in parts if c.get("chat", 0) >= CHAT_OFFSET}:
        _say(peer, public)
    for c in parts:
        r = result[c["id"]]
        mine = [f"⚔ Турнир №{number}: клан «{c['name']}» — " + (f"{r['place']}-е место!" if r["place"] else "вылетел.")]
        if r["prize"]:
            mine.append(f"💰 На склад: +{kk(r['prize'])}")
        mine.append(f"⭐ Репутация: {r['rep']:+d} (теперь {c['rep']})")
        if r["unarmed"]:
            mine.append(f"⚠ Мечей меньше, чем участников ({c['sword']}/{len(c['members'])}) — штраф {UNARMED_REP} к репутации. Купить: «купить мечи N»")
        _notify_staff(c, "\n".join(mine))
    return public


def _new_schedule(day):
    midnight = datetime.strptime(day, "%Y-%m-%d").timestamp()
    now = time.time()
    times, done = [], []
    for h1, h2 in BATTLE_WINDOWS:
        lo, hi = midnight + h1 * 3600, midnight + h2 * 3600
        t = random.uniform(lo, hi)
        d = 0
        if t < now:
            if now < hi - 60:
                t = random.uniform(now + 30, hi)       # бота включили посреди окна — бой будет позже в нём
            else:
                d = 1                                   # окно уже прошло
        times.append(int(t))
        done.append(d)
    return {"day": day, "times": times, "done": done}


def check_clan_battles():
    """Вызывается из таймера бота раз в секунду: два случайных турнира в день."""
    now = time.time()
    day = today_str()
    sched = META.get("sched") or {}
    if sched.get("day") != day:
        sched = META["sched"] = _new_schedule(day)
        save_clans()
    for i, t in enumerate(sched["times"]):
        if sched["done"][i] or now < t:
            continue
        sched["done"][i] = 1
        save_clans()                                   # сначала отметка, потом бой: турнир не повторится даже при сбое
        if now - t > BATTLE_LATE_LIMIT:
            continue
        try:
            run_battle()
        except Exception as e:
            print(f"Ошибка турнира кланов: {err_text(e)}")


# =====================================================================================
#                              РАЗБОР КОМАНДЫ «клан ...»
# =====================================================================================
SUBCOMMANDS = {
    "помощь": do_help, "help": do_help, "хелп": do_help, "команды": do_help,
    "топ": do_top, "top": do_top, "рейтинг": do_top,
    "создать": do_create, "создай": do_create, "create": do_create,
    "положить": do_deposit, "вложить": do_deposit, "пополнить": do_deposit, "deposit": do_deposit,
    "добавить": do_invite, "пригласить": do_invite, "invite": do_invite,
    "принять": do_accept, "вступить": do_accept, "accept": do_accept,
    "отклонить": do_decline, "отказаться": do_decline,
    "выгнать": do_kick, "кик": do_kick, "исключить": do_kick,
    "зам": do_deputy, "заместитель": do_deputy,
    "выйти": do_leave, "покинуть": do_leave,
    "улучшить": do_upgrade, "ап": do_upgrade, "улучшение": do_upgrade,
    "ава": do_avatar, "аватар": do_avatar, "аватарка": do_avatar, "фото": do_avatar,
    "распустить": do_disband,
    "чат": do_chat,
    "битва": do_admin_battle, "турнир": do_admin_battle,
    "удалить": do_admin_delete,
    "сброс": do_admin_clear_avatar,
}


def cmd_clan(msg, rest, slash):
    uid = msg["from_id"]
    if uid <= 0:
        return
    word, _, tail = rest.strip().partition(" ")
    sub = word.lower().replace("ё", "е")
    tail = tail.strip()
    if sub == "купить":                                  # «клан купить мечи 5»
        w2, _, t2 = tail.partition(" ")
        kind = GEAR_WORDS.get(w2.lower().replace("ё", "е"))
        if kind:
            do_gear(msg, uid, kind, t2)
        else:
            send(msg["peer_id"], "ℹ️ Купить: «купить мечи 5», «купить щиты 5», «купить доспехи 5»")
        return
    fn = SUBCOMMANDS.get(sub)
    if fn:
        fn(msg, uid, tail)
        return
    do_show(msg, uid, rest.strip())


def cmd_clan_top(msg, rest, slash):
    do_top(msg, msg["from_id"], "")


def cmd_clan_swords(msg, rest, slash):
    do_gear(msg, msg["from_id"], "sword", rest)


def cmd_clan_armor(msg, rest, slash):
    do_gear(msg, msg["from_id"], "armor", rest)


def cmd_clan_shields(msg, rest, slash):
    do_gear(msg, msg["from_id"], "shield", rest)


# =====================================================================================
#                               КНОПКИ И ЛИЧНЫЕ СООБЩЕНИЯ
# =====================================================================================
def clan_action(ev, p):
    """Кнопки «Вступить / Отказать» под приглашением. Возвращает короткий ответ для игрока."""
    uid = ev["user_id"]
    if uid != p.get("u"):
        return "Это приглашение не для вас."
    c = CLANS.get(str(p.get("c")))
    peer_id, cmid = ev["peer_id"], ev.get("conversation_message_id")

    def finish(text):
        try:
            edit_message(peer_id, cmid, text)
        except Exception as e:
            print(f"Клан: не удалось обновить приглашение: {err_text(e)}")

    if not c:
        finish("⌛ Этого клана больше нет.")
        return "Клан уже не существует."
    if p.get("act") == "no":
        if c["invites"].pop(str(uid), None):
            save_clans()
        finish(f"❌ Вы отказались от приглашения в клан «{c['name']}».")
        return "Приглашение отклонено."
    ok, text = _join(uid, c)
    finish(text if ok else f"⚠ {text}")
    if ok:
        names = get_names([uid])
        _notify_staff(c, f"👥 {mention(uid, names)} вступил(а) в клан «{c['name']}». Участников: {len(c['members'])}/{level_cap(c)}")
    return text[:90]


def clan_dm_hook(msg):
    """Личные сообщения боту: клановые команды и фото для аватарки. True — сообщение обработано."""
    uid = msg["from_id"]
    if uid <= 0:
        return False
    text = (msg.get("text") or "").strip()

    wait = _avatar_wait.get(uid)
    if wait:
        if wait < time.time():
            _avatar_wait.pop(uid, None)
        elif msg_photos(msg):
            _avatar_wait.pop(uid, None)
            c = clan_of(uid)
            if c and is_owner(c, uid) and c["level"] >= AVATAR_LEVEL:
                _set_avatar(msg, uid, c)
            else:
                send(msg["peer_id"], "⚠ Аватарку может ставить только владелец клана 3 уровня.")
            return True
        elif _norm(text) in ("отмена", "cancel", "/cancel"):
            _avatar_wait.pop(uid, None)
            send(msg["peer_id"], "❌ Смена аватарки отменена.")
            return True
    if not text:
        return False

    parts = text.split(maxsplit=1)
    raw = parts[0].lower()
    cmd = raw.lstrip("/").replace("ё", "е")
    rest = parts[1] if len(parts) > 1 else ""
    slash = raw.startswith("/")

    is_clan_word = cmd in ("клан", "clan")
    gear_kind = None
    is_top = False
    if cmd in ("купить", "buy") and rest:
        w, _, tail = rest.partition(" ")
        gear_kind = GEAR_WORDS.get(w.lower().replace("ё", "е"))
    elif cmd in ("топ", "top") and _norm(rest) in ("клан", "кланов", "кланы", "clan", "clans"):
        is_top = True
    if not (is_clan_word or gear_kind or is_top):
        return False

    if uid != OWNER_ID:
        left = freeze_left(uid)
        if left > 0:
            send(msg["peer_id"], f"🧊 Ваши команды заморожены {freeze_text(left)}.")
            return True
    if is_clan_word:
        cmd_clan(msg, rest, slash)
    elif gear_kind:
        do_gear(msg, uid, gear_kind, rest.partition(" ")[2])
    else:
        do_top(msg, uid, "")
    return True


_db_init()
