# -*- coding: utf-8 -*-
"""Долги между игроками: «дать долг @игрок СУММА [дней]», подтверждение кнопками, возврат, просрочка."""
import re
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    DEBT_ALERT, DEBT_DAILY_PERCENT, DEBT_MAX, DEBT_MAX_ACTIVE, DEBT_MAX_DAYS, DEBT_MAX_PENDING, DEBT_MIN, DEBT_OFFER_TTL,
    DEBT_OVERDUE_MULT, err_text, OWNER_ID,
)
from database import economy, get_user, save_economy
from helpers import (
    edit_message, fmt_duration, fmt_num, fmt_time, get_names, mention, no_target, parse_amount,
    parse_target, send, send_get_cmid,
)

USAGE = ("ℹ️ Долг: дать долг @игрок СУММА [дней]\nПример: дать долг @ivan 100кк 3\n"
         f"Срок — от 1 до {DEBT_MAX_DAYS} дн. (без числа — {DEBT_MAX_DAYS}).")
_last = {"t": 0.0}


def _debts():
    return economy.setdefault("debts", {})

def _new_id():
    seq = economy.setdefault("seq", {})
    seq["debt"] = seq.get("debt", 0) + 1
    return str(seq["debt"])

def owed(d, now=None):
    """Сколько нужно вернуть сейчас: долг + DEBT_DAILY_PERCENT% от суммы за каждый день (начатые сутки считаются)."""
    now = now or time.time()
    start = d.get("accepted") or d["t"]
    days = max(1, -(-int(now - start) // 86400))
    return d["amount"] + d["amount"] * DEBT_DAILY_PERCENT * days // 100

def _kb(rows, did):
    kb = VkKeyboard(inline=True)
    for label, color, act in rows:
        kb.add_callback_button(label, color, {"cmd": "debt", "a": act, "id": int(did)})
    return kb.get_keyboard()

def _offer_text(d, names):
    lender, borrower = d["lender"], d["borrower"]
    return (f"💸 {mention(lender, names)} предлагает {mention(borrower, names)} долг: {fmt_num(d['amount'])} 💰\n"
            f"⏳ Срок возврата: {d['term']} дн.\n"
            f"📈 При возврате доплата {DEBT_DAILY_PERCENT}% от суммы за каждый день долга.\n"
            f"⚠ Не вернёте вовремя — ваш баланс уйдёт в минус на {fmt_num(d['amount'] * DEBT_OVERDUE_MULT)} 💰.\n\n"
            f"{mention(borrower, names)}, вы принимаете средства?")


def cmd_debt_give(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if uid <= 0:
        return
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, USAGE)
        return
    if target <= 0 or target == uid:
        send(peer_id, "⛔ Долг можно дать только другому игроку.")
        return
    tokens = tail.split()
    amount = parse_amount(tokens[0]) if tokens else None
    if amount is None:
        send(peer_id, USAGE)
        return
    days = DEBT_MAX_DAYS
    if len(tokens) > 1:
        m = re.match(r"(\d+)$", tokens[1])
        if not m:
            send(peer_id, USAGE)
            return
        days = int(m.group(1))
        if not 1 <= days <= DEBT_MAX_DAYS:
            send(peer_id, f"⚠ Срок возврата — от 1 до {DEBT_MAX_DAYS} дней.")
            return
    if amount < DEBT_MIN or amount > DEBT_MAX:
        send(peer_id, f"⚠ Сумма долга: от {fmt_num(DEBT_MIN)} до {fmt_num(DEBT_MAX)} 💰")
        return
    if get_user(uid)["money"] < amount:
        send(peer_id, f"⚠ Недостаточно денег. Ваш баланс: {fmt_num(get_user(uid)['money'])} 💰")
        return
    debts = _debts().values()
    if sum(1 for d in debts if d["lender"] == uid and d["status"] == "pending") >= DEBT_MAX_PENDING:
        send(peer_id, "⚠ У вас уже висят неподтверждённые предложения. Подождите ответа.")
        return
    if sum(1 for d in debts if d["borrower"] == target and d["status"] == "active") >= DEBT_MAX_ACTIVE:
        send(peer_id, f"⚠ У этого игрока уже {DEBT_MAX_ACTIVE} непогашенных долга.")
        return
    did = _new_id()
    d = {"lender": uid, "borrower": target, "amount": amount, "term": days, "status": "pending",
         "peer": peer_id, "t": int(time.time()), "due": 0}
    _debts()[did] = d
    names = get_names([uid, target])
    try:
        d["cmid"] = send_get_cmid(peer_id, _offer_text(d, names),
                                  _kb([("✅ Принять", VkKeyboardColor.POSITIVE, "ok1"),
                                       ("❌ Отказать", VkKeyboardColor.NEGATIVE, "no")], did))
    except Exception as e:
        del _debts()[did]
        print(f"Не удалось отправить предложение долга: {err_text(e)}")
        return
    save_economy()


def debt_action(ev, p):
    """Кнопки под предложением долга. Возвращает подсказку для всплывающего окна."""
    did = str(p.get("id"))
    d = _debts().get(did)
    if not d:
        return "Долг не найден."
    if d["status"] != "pending":
        return "Это предложение уже закрыто."
    if ev["user_id"] != d["borrower"]:
        return "Это предложение адресовано другому игроку."
    act = p.get("a")
    peer, cmid = ev["peer_id"], ev.get("conversation_message_id")
    names = get_names([d["lender"], d["borrower"]])

    def show(text, kb=None):
        try:
            edit_message(peer, cmid, text, kb)
        except Exception as e:
            print(f"Не удалось обновить сообщение о долге: {err_text(e)}")

    if act == "no":
        d["status"], d["closed"] = "declined", int(time.time())
        save_economy()
        show(f"❌ {mention(d['borrower'], names)} отказался от долга {fmt_num(d['amount'])} 💰")
        return "Вы отказались."
    if act == "ok1":                                       # первое нажатие — просим подтвердить
        show(f"❓ {mention(d['borrower'], names)}, подтвердите: вы принимаете {fmt_num(d['amount'])} 💰 "
             f"от {mention(d['lender'], names)}?\n"
             f"Вернуть нужно в течение {d['term']} дн. + {DEBT_DAILY_PERCENT}% за каждый день. Иначе баланс уйдёт в минус на "
             f"{fmt_num(d['amount'] * DEBT_OVERDUE_MULT)} 💰.",
             _kb([("✅ Подтвердить", VkKeyboardColor.POSITIVE, "ok2"),
                  ("❌ Отказать", VkKeyboardColor.NEGATIVE, "no")], did))
        return None
    if act == "ok2":
        if sum(1 for x in _debts().values() if x["borrower"] == d["borrower"] and x["status"] == "active") >= DEBT_MAX_ACTIVE:
            return f"У вас уже {DEBT_MAX_ACTIVE} непогашенных долга."
        lender, borrower = get_user(d["lender"]), get_user(d["borrower"])
        if lender["money"] < d["amount"]:
            d["status"], d["closed"] = "failed", int(time.time())
            save_economy()
            show(f"❌ Долг не оформлен: у {mention(d['lender'], names)} уже недостаточно денег.")
            return "У дающего не хватает денег."
        lender["money"] -= d["amount"]
        borrower["money"] += d["amount"]
        now = time.time()
        d.update(status="active", due=now + d["term"] * 86400, accepted=int(now))
        save_economy()
        show(f"✅ Долг оформлен!\n{mention(d['lender'], names)} → {mention(d['borrower'], names)}: {fmt_num(d['amount'])} 💰\n"
             f"⏳ Вернуть до {fmt_time(d['due'])}\n"
             f"📈 Доплата {DEBT_DAILY_PERCENT}% за каждый день долга.\n"
             f"Вернуть: вернуть долг {did} · Все долги: долги")
        if d["amount"] >= DEBT_ALERT:
            try:
                send(OWNER_ID, f"💸 Долг #{did}: {mention(d['lender'], names)} → {mention(d['borrower'], names)}, "
                               f"{fmt_num(d['amount'])} 💰 на {d['term']} дн.")
            except Exception as e:
                print(f"Не удалось сообщить владельцу о долге: {err_text(e)}")
        return "Долг оформлен."
    return "Кнопка устарела."


def cmd_debts(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    now = time.time()
    mine = [(i, d) for i, d in _debts().items() if d["status"] in ("active", "pending")
            and uid in (d["lender"], d["borrower"])]
    if not mine:
        send(peer_id, "📒 У вас нет долгов и займов.\nДать долг: дать долг @игрок СУММА [дней]")
        return
    ids = {x for _, d in mine for x in (d["lender"], d["borrower"])}
    names = get_names(list(ids))
    owe, lent = [], []
    for i, d in sorted(mine, key=lambda x: int(x[0])):
        left = f"осталось {fmt_duration(d['due'] - now)}" if d["status"] == "active" else "ждёт подтверждения"
        if d["borrower"] == uid:
            owe.append(f"• #{i}: {fmt_num(d['amount'])} 💰 (сейчас вернуть {fmt_num(owed(d, now))}) → "
                       f"{names.get(d['lender'], d['lender'])} ({left})")
        else:
            lent.append(f"• #{i}: {fmt_num(d['amount'])} 💰 ← {names.get(d['borrower'], d['borrower'])} ({left})")
    parts = ["📒 Ваши долги и займы"]
    if owe:
        parts.append("\nВы должны:\n" + "\n".join(owe) + "\nВернуть: вернуть долг НОМЕР")
    if lent:
        parts.append("\nВам должны:\n" + "\n".join(lent))
    send(peer_id, "\n".join(parts))


def cmd_debt_return(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    mine = {i: d for i, d in _debts().items() if d["status"] == "active" and d["borrower"] == uid}
    if not mine:
        send(peer_id, "ℹ️ У вас нет непогашенных долгов.")
        return
    want = rest.strip().lstrip("#")
    if want.isdigit():
        did = want if want in mine else None
    elif len(mine) == 1:
        did = next(iter(mine))
    else:
        send(peer_id, "⚠ Долгов несколько: " + ", ".join(f"#{i}" for i in mine) + ". Напишите: вернуть долг НОМЕР")
        return
    if did is None:
        send(peer_id, "⚠ Такого долга у вас нет. Список: долги")
        return
    d = mine[did]
    borrower = get_user(uid)
    total = owed(d)
    extra = total - d["amount"]
    if borrower["money"] < total:
        send(peer_id, f"⚠ Не хватает денег: нужно {fmt_num(total)} 💰 (долг {fmt_num(d['amount'])} + {fmt_num(extra)} "
                      f"за дни долга), у вас {fmt_num(borrower['money'])} 💰")
        return
    borrower["money"] -= total
    get_user(d["lender"])["money"] += total
    d["status"], d["closed"], d["paid"] = "paid", int(time.time()), total
    save_economy()
    names = get_names([uid, d["lender"]])
    send(peer_id, f"✅ Долг #{did} возвращён: {mention(uid, names)} → {mention(d['lender'], names)}\n"
                  f"Долг: {fmt_num(d['amount'])} 💰 + доплата {fmt_num(extra)} 💰 = {fmt_num(total)} 💰")


def _settle_overdue(did, d, now):
    """Срок вышел, долг не возвращён: баланс заёмщика уходит в минус на сумму × DEBT_OVERDUE_MULT.
    Дающий получает назад только то, что у заёмщика реально было (из воздуха деньги не появляются)."""
    P = d["amount"]
    borrower, lender = get_user(d["borrower"]), get_user(d["lender"])
    bal = borrower["money"]
    back = min(P, max(0, bal))
    borrower["money"] = bal - P * DEBT_OVERDUE_MULT
    lender["money"] += back
    d.update(status="overdue", closed=int(now), recovered=back)
    save_economy()
    names = get_names([d["borrower"], d["lender"]])
    try:
        send(d["peer"], f"⏰ Срок долга #{did} истёк, {mention(d['borrower'], names)} не вернул {fmt_num(P)} 💰.\n"
                        f"Баланс {mention(d['borrower'], names)}: {fmt_num(borrower['money'])} 💰\n"
                        f"{mention(d['lender'], names)} получил обратно: {fmt_num(back)} 💰")
    except Exception as e:
        print(f"Не удалось сообщить о просроченном долге #{did}: {err_text(e)}")


def check_debts():
    """Раз в 15 сек (из tick_loop): истекают предложения, напоминания за сутки, просрочка, чистка старых записей."""
    now = time.time()
    if now - _last["t"] < 15:
        return
    _last["t"] = now
    for did, d in list(_debts().items()):
        st = d.get("status")
        if st == "pending" and now - d["t"] > DEBT_OFFER_TTL:
            d["status"], d["closed"] = "expired", int(now)
            save_economy()
            if d.get("cmid"):
                try:
                    edit_message(d["peer"], d["cmid"], f"⌛ Предложение долга {fmt_num(d['amount'])} 💰 истекло.")
                except Exception as e:
                    print(f"Не удалось обновить предложение долга: {err_text(e)}")
        elif st == "active":
            if now >= d["due"]:
                _settle_overdue(did, d, now)
            elif not d.get("warned") and d["due"] - now < 86400 and d["term"] > 1:
                d["warned"] = True
                save_economy()
                names = get_names([d["borrower"]])
                try:
                    send(d["peer"], f"⏳ {mention(d['borrower'], names)}, до конца срока долга #{did} осталось меньше суток: "
                                    f"верните {fmt_num(d['amount'])} 💰 (вернуть долг {did}).")
                except Exception as e:
                    print(f"Не удалось напомнить о долге #{did}: {err_text(e)}")
        elif st in ("paid", "declined", "expired", "failed", "overdue") and now - d.get("closed", d["t"]) > 30 * 86400:
            del _debts()[did]
