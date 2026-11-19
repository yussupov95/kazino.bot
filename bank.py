# -*- coding: utf-8 -*-
"""Банк: вклады, плавный рост до +10% за неделю, комиссия 3% при снятии."""
import time

from config import (
    BANK_BONUS_DAYS, BANK_FEE_PERCENT, BANK_MAX_BONUS_PERCENT, BANK_MAX_LOTS, BANK_MERGE_SECONDS,
)
from database import economy, get_user, save_economy
from helpers import fmt_duration, fmt_num, get_names, mention, parse_amount, send

WEEK = BANK_BONUS_DAYS * 86400
DEPOSIT_WORDS = ("положить", "вложить", "внести", "пополнить", "deposit")
WITHDRAW_WORDS = ("забрать", "взять", "снять", "вывести", "withdraw")


def _lots(uid):
    return economy.setdefault("bank", {}).get(str(uid), [])


def lot_bonus(lot, now):
    """Проценты по вкладу (целые числа, без ошибок округления): растут линейно, максимум +BANK_MAX_BONUS_PERCENT%."""
    elapsed = min(max(0, int(now - lot["t"])), WEEK)
    return lot["a"] * BANK_MAX_BONUS_PERCENT * elapsed // (100 * WEEK)


def lot_value(lot, now):
    return lot["a"] + lot_bonus(lot, now)


def bank_total(uid, now=None):
    now = now or time.time()
    return sum(lot_value(l, now) for l in _lots(uid))


def deposit(uid, amount, now=None):
    now = now or time.time()
    lots = economy.setdefault("bank", {}).setdefault(str(uid), [])
    if lots and now - lots[-1]["t"] < BANK_MERGE_SECONDS:     # вклады в пределах часа сливаются (средневзвешенное время)
        last = lots[-1]
        total = last["a"] + amount
        last["t"] = (last["a"] * last["t"] + amount * now) / total
        last["a"] = total
    else:
        lots.append({"a": amount, "t": now})


def withdraw_value(uid, amount, now=None):
    """Списывает со счёта amount (с учётом процентов), сначала самые старые вклады."""
    now = now or time.time()
    lots = _lots(uid)
    left = amount
    for lot in list(lots):
        if left <= 0:
            break
        v = lot_value(lot, now)
        if v <= left:
            left -= v
            lots.remove(lot)
        else:
            take_base = min(lot["a"], (left * lot["a"] + v - 1) // v)
            lot["a"] -= take_base
            left = 0
            if lot["a"] <= 0:
                lots.remove(lot)
    if not lots:
        economy.setdefault("bank", {}).pop(str(uid), None)


def bank_text(uid, now=None):
    now = now or time.time()
    lots = _lots(uid)
    base = sum(l["a"] for l in lots)
    total = sum(lot_value(l, now) for l in lots)
    names = get_names([uid])
    lines = [f"🏦 Банк — {mention(uid, names)}",
             f"💰 На счёте: {fmt_num(total)}"]
    if lots:
        lines.append(f"📈 Проценты: +{fmt_num(total - base)} (вложено {fmt_num(base)})")
        growing = [WEEK - (now - l["t"]) for l in lots if now - l["t"] < WEEK]
        if growing:
            lines.append(f"⏳ До максимума (+{BANK_MAX_BONUS_PERCENT}%): {fmt_duration(min(growing))}")
        else:
            lines.append(f"✅ Все вклады набрали максимум +{BANK_MAX_BONUS_PERCENT}%")
    lines.append("")
    lines.append(f"Вклад растёт до +{BANK_MAX_BONUS_PERCENT}% за {BANK_BONUS_DAYS} дн. Комиссия за снятие: {BANK_FEE_PERCENT}%.")
    lines.append("• банк положить СУММА (или «все»)\n• банк забрать СУММА (или «все»)")
    return "\n".join(lines)


def cmd_bank(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if uid <= 0:
        return
    parts = rest.split()
    sub = parts[0].lower().replace("ё", "е") if parts else ""
    if not sub:
        send(peer_id, bank_text(uid))
        return
    if sub in DEPOSIT_WORDS:
        user = get_user(uid)
        amount = parse_amount(parts[1], user["money"]) if len(parts) > 1 else None
        if amount is None:
            send(peer_id, "⚠ Укажите сумму: банк положить 10кк (или «все»).")
            return
        if amount > user["money"]:
            send(peer_id, f"⚠ Недостаточно денег. Ваш баланс: {fmt_num(user['money'])} 💰")
            return
        lots = _lots(uid)
        if len(lots) >= BANK_MAX_LOTS and time.time() - lots[-1]["t"] >= BANK_MERGE_SECONDS:
            send(peer_id, "⚠ Слишком много отдельных вкладов. Заберите часть денег и попробуйте снова.")
            return
        user["money"] -= amount
        deposit(uid, amount)
        save_economy()
        send(peer_id, f"✅ Вы положили в банк {fmt_num(amount)} 💰\n\n" + bank_text(uid))
    elif sub in WITHDRAW_WORDS:
        total = bank_total(uid)
        amount = parse_amount(parts[1], total) if len(parts) > 1 else None
        if amount is None:
            send(peer_id, "⚠ Укажите сумму: банк забрать 10кк (или «все»).")
            return
        if amount > total:
            send(peer_id, f"⚠ На счёте только {fmt_num(total)} 💰")
            return
        fee = (amount * BANK_FEE_PERCENT + 99) // 100         # округляем вверх, чтобы комиссию нельзя было обойти мелкими снятиями
        get = amount - fee
        withdraw_value(uid, amount)
        get_user(uid)["money"] += get
        save_economy()
        send(peer_id, f"✅ Снято со счёта: {fmt_num(amount)}\n"
                      f"💸 Комиссия {BANK_FEE_PERCENT}%: {fmt_num(fee)}\n"
                      f"💰 Вы получили: {fmt_num(get)}\n\n" + bank_text(uid))
    elif slash:
        send(peer_id, "ℹ️ Команды: банк · банк положить СУММА · банк забрать СУММА")
