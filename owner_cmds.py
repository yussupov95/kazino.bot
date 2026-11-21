# -*- coding: utf-8 -*-
"""Команды владельца в личных сообщениях бота."""
from config import DRONE_WORDS, MAX_GRANT, OWNER_AMOUNT_RE, OWNER_COMMANDS, OWNER_ID
from database import get_user, save_economy
from helpers import (
    drone_command, fmt_num, get_names, mention, parse_amount, send, target_from_text,
)
from logs import log_action
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
