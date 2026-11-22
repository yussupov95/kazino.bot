# -*- coding: utf-8 -*-
"""Команды владельца в личных сообщениях бота."""
import re
import time

from config import (
    BUSINESSES, DRONE_WORDS, MAX_GRANT, MENTION_RE, OWNER_AMOUNT_RE, OWNER_COMMANDS,
    OWNER_ID, PACK_WORDS, PACKS, PERK_TITLES, PETS, VIP_DAYS, VIP_PREFIX, VAMPIRE_TITLE,
)
from database import get_user, save_economy, vip_active
from helpers import (
    drone_command, fmt_num, get_names, LINK_RE, mention, parse_amount, resolve_vk_link, send,
    target_from_message, target_from_text,
)
from donate import give_pack
from logs import log_action
from shop import equipped, SHOP_ITEMS
from staff_money import create_promo
from wipe import find_id, restore_command


# ---------- «хелп-команды» (только владелец, только в ЛС боту) ----------
OWNER_HELP_WORDS = ("хелп-команды", "хелп команды", "хелпкоманды", "help-commands", "help commands")

def owner_help_chunks():
    lines = ["👑 Команды владельца", "Видны только вам и работают в ЛС боту (кроме тех, где указано иначе).", ""]
    for i, (c, d) in enumerate(OWNER_COMMANDS):
        lines += ([""] if i else []) + [f"🔹 {c[:1].upper() + c[1:]}\n{d}"]
    lines += ["", "Команды остальных ролей (вам доступны все): «хелп» в беседе, вкладки по ролям. "
                  "Обычные игровые команды — «команды»."]
    chunks, cur = [], ""
    for line in lines:
        if cur and len(cur) + len(line) + 1 > 3500:
            chunks.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + line
    if cur:
        chunks.append(cur)
    return chunks

def owner_help_command(msg, text):
    if text.lower().replace("ё", "е").strip(" .!?") not in OWNER_HELP_WORDS:
        return False
    for chunk in owner_help_chunks():
        send(msg["peer_id"], chunk)
    return True


# ---------- Выдача и отбор: вампир, питомец, персонаж, бизнес, VIP, доступ, набор ----------
# «выдать вампира ID», «выдать питомца овчарка https://vk.ru/name», «отобрать персонажа 5» (ответом на сообщение).
# Игрока можно указать: ссылкой VK, @упоминанием, ID, либо ответом на его сообщение (в беседе).
GRANT_KINDS = {
    "вампир": "vamp", "вампира": "vamp", "vampire": "vamp", "vamp": "vamp",
    "питомец": "pet", "питомца": "pet", "пит": "pet", "pet": "pet",
    "персонаж": "char", "персонажа": "char", "перс": "char", "char": "char",
    "бизнес": "biz", "business": "biz", "biz": "biz",
    "вип": "vip", "vip": "vip",
    "доступ": "perk", "perk": "perk",
    "набор": "pack", "pack": "pack",
}
PERK_WORDS = {"история": "history", "истории": "history", "history": "history", "хелп": "help", "help": "help",
              "профили": "profiles", "профиль": "profiles", "profiles": "profiles",
              "баланс": "balance", "balance": "balance", "варн": "warn_immune", "иммунитет": "warn_immune"}
GRANT_USAGE = ("ℹ️ Выдать / отобрать (владелец):\n"
               "выдать вампира ID|ссылка\n"
               "выдать питомца сосиска|овчарка|бульдог ID|ссылка\n"
               "выдать персонажа НОМЕР ID|ссылка\n"
               "выдать бизнес пекарня|зоомагазин|автосалон|казино|бомж ID|ссылка\n"
               "выдать вип ID|ссылка [ДНЕЙ]\n"
               "выдать доступ история|хелп|профили|баланс|варн ID|ссылка\n"
               "выдать набор 1–4 ID|ссылка\n"
               "Отобрать: то же со словом «отобрать». В беседе игрока можно указать ответом на сообщение.")

def split_target(msg, text):
    """(игрок, остаток текста). Ссылка VK, @упоминание, «id123», ответ на сообщение или ID в конце."""
    text = text.strip()
    m = LINK_RE.search(text)
    if m:
        uid = resolve_vk_link(m.group(0))
        if uid is not None:
            return uid, (text[:m.start()] + " " + text[m.end():]).strip()
    m = MENTION_RE.search(text)
    if m:
        return int(m.group(1)), (text[:m.start()] + " " + text[m.end():]).strip()
    m = re.search(r"(?:^|\s)id(\d+)(?=\s|$)", text, re.I)
    if m:
        return int(m.group(1)), (text[:m.start()] + " " + text[m.end():]).strip()
    from_msg = target_from_message(msg)
    if from_msg is not None:
        return from_msg, text
    m = re.search(r"(?:^|\s)(\d{5,})\s*$", text)             # длинное число в конце — ID
    if m:
        return int(m.group(1)), text[:m.start()].strip()
    return None, text

def _find_pet(word):
    word = word.lower().replace("ё", "е")
    for pid, pet in PETS.items():
        if word in (pid, pet["name"].lower().replace("ё", "е"), pet["kind"].lower().replace("ё", "е"), pid[3:]):
            return pid
    return None

def _find_biz(word):
    word = word.lower().replace("ё", "е")
    for key, b in BUSINESSES.items():
        if word in (key, b["name"].lower().replace("ё", "е")):
            return key
    return None

def owner_grant(msg, verb, text):
    """verb: «выдать» / «отобрать». Возвращает True, если это была команда выдачи (ответ отправлен)."""
    peer_id = msg["peer_id"]
    parts = text.split(maxsplit=1)
    if not parts or parts[0].lower().replace("ё", "е") not in GRANT_KINDS:
        return False
    kind = GRANT_KINDS[parts[0].lower().replace("ё", "е")]
    target, rest = split_target(msg, parts[1] if len(parts) > 1 else "")
    if target is None or target <= 0:
        send(peer_id, GRANT_USAGE)
        return True
    give = verb == "выдать"
    user = get_user(target)
    names = get_names([target])
    who = mention(target, names)
    arg = rest.split()
    word = arg[0].lower().replace("ё", "е") if arg else ""

    if kind == "vamp":
        user["vampire"] = give
        if give:
            user.setdefault("vampire_since", time.time())
        note = f"🧛 {who}: {'теперь ' + VAMPIRE_TITLE if give else 'больше не ' + VAMPIRE_TITLE}."
    elif kind == "pet":
        pid = _find_pet(word) if word else None
        if not pid:
            send(peer_id, "ℹ️ Питомец: сосиска, овчарка или бульдог. Пример: выдать питомца овчарка https://vk.ru/name")
            return True
        pets = user.setdefault("pets", [])
        if give and pid not in pets:
            pets.append(pid)
        elif not give and pid in pets:
            pets.remove(pid)
        note = f"🐾 {who}: питомец «{PETS[pid]['name']}» {'выдан' if give else 'забран'}."
    elif kind == "char":
        item = f"char{word}" if word.isdigit() else None
        if item not in SHOP_ITEMS:
            send(peer_id, "ℹ️ Укажите номер модели персонажа (char5 → 5). Пример: выдать персонажа 5 https://vk.ru/name")
            return True
        items = user.setdefault("items", [])
        if give:
            if item not in items:
                items.append(item)
            user.setdefault("equip", {})["char"] = item
        else:
            while item in items:
                items.remove(item)
            if equipped(user, item):
                user["equip"].pop("char", None)
        note = f"🎭 {who}: персонаж «{SHOP_ITEMS[item][1]}» {'выдан и надет' if give else 'забран'}."
    elif kind == "biz":
        key = _find_biz(word) if word else None
        if not key:
            send(peer_id, "ℹ️ Бизнес: " + ", ".join(b["name"].lower() for b in BUSINESSES.values()))
            return True
        if give:
            user.setdefault("biz", {}).setdefault(key, time.time())
        else:
            user.get("biz", {}).pop(key, None)
            user.get("biz_lvl", {}).pop(key, None)
        note = f"🏢 {who}: бизнес «{BUSINESSES[key]['name']}» {'выдан' if give else 'забран'}."
    elif kind == "vip":
        if give:
            days = int(word) if word.isdigit() and 0 < int(word) <= 3650 else VIP_DAYS
            base = user["vip_until"] if vip_active(user) else time.time()
            user["vip"], user["vip_until"] = True, base + days * 86400
            if user.get("prefix", "") in ("", "VIP✨", VIP_PREFIX):
                user["prefix"] = VIP_PREFIX
            note = f"✨ {who}: VIP выдан на {days} дн."
        else:
            user["vip"], user["vip_until"] = False, 0
            if user.get("prefix") in (VIP_PREFIX, "VIP✨"):
                user.pop("prefix", None)
            note = f"✨ {who}: VIP снят."
    elif kind == "perk":
        perk = PERK_WORDS.get(word)
        if not perk:
            send(peer_id, "ℹ️ Доступ: история, хелп, профили, баланс, варн (иммунитет)")
            return True
        perks = set(user.get("perks") or [])
        perks.add(perk) if give else perks.discard(perk)
        user["perks"] = sorted(perks)
        note = f"🔓 {who}: доступ {PERK_TITLES[perk]} {'выдан' if give else 'снят'}."
    else:                                                       # набор
        key = PACK_WORDS.get(word)
        if not key:
            send(peer_id, "ℹ️ Набор: 1 (Новичка), 2 (VIP), 3 (Ультра), 4 (Премиум)")
            return True
        if not give:
            send(peer_id, "ℹ️ Набор целиком отобрать нельзя — отбирайте части по отдельности (питомец, бизнес, персонаж, доступ).")
            return True
        give_pack(target, key)
        note = f"🎁 {who}: выдан {PACKS[key]['title']}."
    save_economy()
    log_action(peer_id, OWNER_ID, f"{verb} {kind} → {target}: {rest}")
    send(peer_id, note)
    return True

def cmd_owner_grant(msg, rest, slash):
    """«выдать …» / «отобрать …» в беседе — только владелец (остальным бот молчит)."""
    if msg["from_id"] != OWNER_ID:
        return
    verb = "отобрать" if msg.get("_verb") == "отобрать" else "выдать"
    if not owner_grant(msg, verb, rest) and slash:
        send(msg["peer_id"], GRANT_USAGE)

def cmd_owner_take(msg, rest, slash):
    msg = dict(msg, _verb="отобрать")
    cmd_owner_grant(msg, rest, slash)

# ---------- Команды владельца в ЛС боту: промокод, деньги себе, режим «беспилотник» ----------
def owner_extra_commands(msg, text):
    """ЛС владельца: «промокод НАЗВАНИЕ СУММА ИСПОЛЬЗОВАНИЙ», «деньги СУММА [ID]», «дрон вкл/выкл».
    True — сообщение обработано."""
    peer_id = msg["peer_id"]
    parts = (text or "").split()
    if not parts:
        return False
    word = parts[0].lower().lstrip("/").replace("ё", "е")

    if word in DRONE_WORDS:
        drone_command(peer_id, parts[1:])
        return True

    if word in ("выдать", "отобрать") and len(parts) > 1 and parts[1].lower().replace("ё", "е") in GRANT_KINDS:
        return owner_grant(msg, word, " ".join(parts[1:]))          # «выдать вампира ссылка», «отобрать питомца …»

    if word in ("промокод", "promo"):
        args = parts[1:]
        usage = ("🎫 Создать промокод: промокод НАЗВАНИЕ СУММА ИСПОЛЬЗОВАНИЙ\n"
                 "Пример: промокод Борз 1кк 1\n"
                 "Его активируют в беседе: «промокод Борз» или просто «Борз». Действует 24 часа.")
        if not args:
            send(peer_id, usage)
            return True
        if len(args) != 3:
            return False
        name, amount_text, uses_text = args
        amount = parse_amount(amount_text, regex=OWNER_AMOUNT_RE)
        if amount is None or not uses_text.isdigit() or int(uses_text) < 1 or len(name) > 32:
            return False
        if amount > MAX_GRANT:
            send(peer_id, f"⚠ Максимум: {fmt_num(MAX_GRANT)} 💰")
            return True
        create_promo(peer_id, OWNER_ID, name, amount, int(uses_text))
        return True

    if word in ("восстановить", "restore"):          # «восстановить ID»; без ID — это база из файла (backup.py)
        return restore_command(msg, " ".join(parts[1:]), strict=True)

    if word in ("забрать", "take"):                  # «забрать ID СУММА»
        args = parts[1:]
        if len(args) != 2:
            return False
        target = find_id(msg, args[0])
        user = get_user(target) if target and target > 0 else None
        amount = parse_amount(args[1], user["money"] if user else None, regex=OWNER_AMOUNT_RE) if user else None
        if user is None or amount is None:
            send(peer_id, "ℹ️ Забрать деньги: забрать ID СУММА (или «все»)")
            return True
        names = get_names([target])
        if amount > user["money"]:
            send(peer_id, f"⚠ У {mention(target, names)} только {fmt_num(user['money'])} 💰")
            return True
        user["money"] -= amount
        save_economy()
        log_action(peer_id, OWNER_ID, f"забрал деньги {amount} у {target} (из ЛС)")
        send(peer_id, f"💰 У {mention(target, names)} забрано {fmt_num(amount)} 💰\nБаланс: {fmt_num(user['money'])} 💰")
        return True

    idx = None
    if word in ("деньги", "money", "себе"):
        idx = 1
    elif word in ("выдать", "дать") and len(parts) > 1 and parts[1].lower().replace("ё", "е") in ("деньги", "money", "себе"):
        idx = 2
    if idx is not None:
        args = parts[idx:]
        if not 1 <= len(args) <= 2:
            return False
        amount = parse_amount(args[0], regex=OWNER_AMOUNT_RE)
        if amount is None:
            return False                                   # «деньги вернули» — обычная фраза
        if amount > MAX_GRANT:
            send(peer_id, f"⚠ Максимум за раз: {fmt_num(MAX_GRANT)} 💰")
            return True
        target = OWNER_ID
        if len(args) == 2:
            target = target_from_text(args[1])
            if target is None or target <= 0:
                send(peer_id, "ℹ️ Деньги себе: деньги СУММА\nДеньги игроку: деньги СУММА ID (или ссылка на него)")
                return True
        user = get_user(target)
        user["money"] += amount
        save_economy()
        log_action(peer_id, OWNER_ID, f"выдал деньги {amount} → {target} (из ЛС)")
        if target == OWNER_ID:
            send(peer_id, f"💰 Вам выдано {fmt_num(amount)} 💰\nБаланс: {fmt_num(user['money'])} 💰")
        else:
            names = get_names([target])
            send(peer_id, f"💰 {mention(target, names)} получил {fmt_num(amount)} 💰\nБаланс: {fmt_num(user['money'])} 💰")
        return True
    return False
