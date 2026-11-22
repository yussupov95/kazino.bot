# -*- coding: utf-8 -*-
"""Передача денег между игроками и защита от подозрительных переводов."""
import json
import time

from config import (
    err_text, _here, OWNER_AMOUNT_RE, OWNER_ID, TRANSFER_ALERT_PAIR, TRANSFER_COOLDOWN,
    TRANSFER_DAILY_LIMIT, TRANSFER_MAX, TRANSFER_MIN, TRANSFER_PAIR_LIMIT, TRANSFER_RECEIVE_LIMIT,
)
from database import economy, get_user, save_economy, today_str, vip_active
from helpers import (
    fmt_duration, fmt_num, get_names, mention, no_target, parse_amount, parse_target, send,
)
from logs import log_action


# ---------- Передача денег ----------
def _day_total(user, key_day, key_sum):
    """Сколько игрок уже передал / получил переводами сегодня (счётчик сам обнуляется в полночь)."""
    return int(user.get(key_sum, 0)) if user.get(key_day) == today_str() else 0

def _add_day_total(user, key_day, key_sum, amount):
    user[key_sum] = _day_total(user, key_day, key_sum) + amount
    user[key_day] = today_str()

_MAX_BALANCE = 9 * 10 ** 18          # в базе (SQLite) число не может быть больше ~9,2 квинтиллиона
_GUARD_FILE = _here("transfer_guard.json")
_pair_totals = {}     # {"день": {"отправитель>получатель": сумма}} — переживает перезапуск

def _guard_load():
    try:
        with open(_GUARD_FILE, encoding="utf-8") as f:
            _pair_totals.update(json.load(f))
    except Exception:
        pass

def _guard_add(uid, target, amount):
    """Прибавляет к сумме «uid → target» за сегодня, возвращает (было, стало)."""
    day = today_str()
    for k in [k for k in _pair_totals if k != day]:
        del _pair_totals[k]
    pairs = _pair_totals.setdefault(day, {})
    key = f"{uid}>{target}"
    before = pairs.get(key, 0)
    pairs[key] = before + amount
    try:
        with open(_GUARD_FILE, "w", encoding="utf-8") as f:
            json.dump(_pair_totals, f)
    except Exception as e:
        print(f"Не удалось сохранить журнал переводов: {err_text(e)}")
    return before, before + amount

def _notify_big_transfer(peer_id, uid, target, amount, pair_total):
    """Уведомление владельцу в ЛС: игрок раздаёт много денег одному человеку."""
    try:
        names = get_names([uid, target])
        s_user, r_user = get_user(uid), get_user(target)
        text = (f"🚨 Подозрительные переводы\n"
                f"Отправитель: {names.get(uid, '?')} (vk.com/id{uid}, ID {uid})\n"
                f"Получатель: {names.get(target, '?')} (vk.com/id{target}, ID {target})\n"
                f"Этот перевод: {fmt_num(amount)} 💰\n"
                f"Всего ему за сегодня от этого игрока: {fmt_num(pair_total)} 💰\n"
                f"Баланс отправителя: {fmt_num(s_user['money'])} 💰\n"
                f"Баланс получателя: {fmt_num(r_user['money'])} 💰\n"
                f"Беседа: peer_id {peer_id}\n"
                f"Время: {time.strftime('%d.%m.%Y %H:%M:%S')}")
        send(OWNER_ID, text)
    except Exception as e:
        print(f"Не удалось уведомить владельца о переводе: {err_text(e)}")

def cmd_transfer(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    usage = (f"ℹ️ Использование: передать СУММА — ответом на сообщение участника\n"
             f"Или: передать ID СУММА\n"
             f"Сумма: от {fmt_num(TRANSFER_MIN)} до {fmt_num(TRANSFER_MAX)} 💰\n"
             f"Всего за сутки можно передать: {fmt_num(TRANSFER_DAILY_LIMIT)} 💰, "
             f"одному игроку — не больше {fmt_num(TRANSFER_PAIR_LIMIT)} 💰\n"
             f"Пауза между переводами: {TRANSFER_COOLDOWN} сек. (у VIP паузы нет)")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    is_owner = uid == OWNER_ID          # владелец переводит без лимитов суммы и без паузы
    amount = parse_amount(parts[0], regex=OWNER_AMOUNT_RE if is_owner else None) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    if target <= 0:
        send(peer_id, "⚠ Сообществу деньги передавать нельзя.")
        return
    if target == uid:
        send(peer_id, "⛔ Нельзя передать деньги самому себе.")
        return
    if not is_owner and not TRANSFER_MIN <= amount <= TRANSFER_MAX:
        send(peer_id, f"⚠ Сумма перевода: от {fmt_num(TRANSFER_MIN)} до {fmt_num(TRANSFER_MAX)} 💰")
        return

    sender = get_user(uid)
    now = time.time()
    if not is_owner and not vip_active(sender):
        left = sender.get("last_transfer", 0) + TRANSFER_COOLDOWN - now
        if left > 0:
            send(peer_id, f"⏳ Следующий перевод через {fmt_duration(left)}. "
                          "У VIP-игроков паузы нет — «купить вип».")
            return
    if not is_owner and sender["money"] < amount:       # владелец переводит сколько угодно: баланс не нужен и не списывается
        send(peer_id, f"⚠ Недостаточно денег. Ваш баланс: {fmt_num(sender['money'])} 💰")
        return
    if is_owner and get_user(target)["money"] + amount > _MAX_BALANCE:
        send(peer_id, f"⚠ У получателя баланс не может быть больше {fmt_num(_MAX_BALANCE)} 💰 (предел базы данных).")
        return

    # --- защита экономики: суточные лимиты (владельца не касаются) ---
    track_recv = not is_owner and target != OWNER_ID
    if not is_owner:                                    # одному и тому же игроку — не больше TRANSFER_PAIR_LIMIT за сутки
        pair_sent = _pair_totals.get(today_str(), {}).get(f"{uid}>{target}", 0)
        if TRANSFER_PAIR_LIMIT > 0 and pair_sent + amount > TRANSFER_PAIR_LIMIT:
            can = max(0, TRANSFER_PAIR_LIMIT - pair_sent)
            send(peer_id, f"⛔ Одному и тому же игроку можно передать не больше {fmt_num(TRANSFER_PAIR_LIMIT)} 💰 в сутки. "
                          f"Этому игроку вы уже передали {fmt_num(pair_sent)} 💰, можно ещё {fmt_num(can)} 💰.")
            return
    if not is_owner and TRANSFER_DAILY_LIMIT > 0:
        sent_today = _day_total(sender, "tr_day", "tr_sent")
        if sent_today + amount > TRANSFER_DAILY_LIMIT:
            can = max(0, TRANSFER_DAILY_LIMIT - sent_today)
            send(peer_id, f"⛔ Суточный лимит переводов — {fmt_num(TRANSFER_DAILY_LIMIT)} 💰. "
                          f"Сегодня вы уже передали {fmt_num(sent_today)} 💰, "
                          f"можно ещё {fmt_num(can)} 💰. Лимит обнулится в полночь.")
            return
    if track_recv and TRANSFER_RECEIVE_LIMIT > 0:
        got_today = _day_total(economy["users"].get(str(target), {}), "tr_rday", "tr_recv")
        if got_today + amount > TRANSFER_RECEIVE_LIMIT:
            can = max(0, TRANSFER_RECEIVE_LIMIT - got_today)
            send(peer_id, "⛔ Этот игрок сегодня уже получил максимум переводов. " +
                          (f"Ему можно передать ещё {fmt_num(can)} 💰." if can else "Попробуйте завтра."))
            return

    receiver = get_user(target)
    if not is_owner:
        sender["money"] -= amount
    receiver["money"] += amount
    sender["last_transfer"] = now
    if not is_owner:
        _add_day_total(sender, "tr_day", "tr_sent", amount)
    if track_recv:
        _add_day_total(receiver, "tr_rday", "tr_recv", amount)
    save_economy()
    if not is_owner:
        _before, _after = _guard_add(uid, target, amount)
        if _after > TRANSFER_ALERT_PAIR:
            _notify_big_transfer(peer_id, uid, target, amount, _after)
    log_action(peer_id, uid, f"передал {amount} → {target}")
    names = get_names([uid, target])
    text = f"💸 {mention(uid, names)} передал {mention(target, names)}: {fmt_num(amount)} 💰"
    if not is_owner and TRANSFER_DAILY_LIMIT > 0:
        text += f"\nНа сегодня можно передать ещё: {fmt_num(max(0, TRANSFER_DAILY_LIMIT - _day_total(sender, 'tr_day', 'tr_sent')))} 💰"
    send(peer_id, text)

# ---------- выполняется при запуске ----------
_guard_load()
