# -*- coding: utf-8 -*-
"""Дуэль (револьвер)."""
import random
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    DUEL_CHAMBERS, DUEL_MAX_BULLETS, DUEL_PENDING_SECONDS, DUEL_SHOT_SECONDS, MIN_BET,
)
from database import economy, get_user, save_economy
from helpers import (
    answer_event, edit_message, fmt_num, get_names, mention, no_target, parse_amount,
    parse_target, send, send_get_cmid, with_retry,
)
from logs import log_action


# ---------- Дуэль ----------
def prune_duels():
    now = time.time()
    for k in [k for k, d in economy["duels"].items() if now - d.get("t", 0) > 86400]:
        del economy["duels"][k]

def cmd_duel(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    usage = ("ℹ️ Использование: дуэль СУММА — ответом на сообщение соперника\n"
             "Или: дуэль ID СУММА\nПример: дуэль 1кк")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    amount = parse_amount(parts[0]) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    if target <= 0 or target == uid:
        send(peer_id, "⛔ Выберите в соперники другого участника беседы.")
        return
    if amount < MIN_BET:
        send(peer_id, f"⚠ Минимальная ставка: {fmt_num(MIN_BET)} 💰")
        return
    if get_user(uid)["money"] < amount:
        send(peer_id, f"⚠ У вас недостаточно денег. Баланс: {fmt_num(get_user(uid)['money'])} 💰")
        return
    if get_user(target)["money"] < amount:
        send(peer_id, "⚠ У соперника недостаточно денег для такой ставки.")
        return

    prune_duels()
    economy["seq"]["duel"] += 1
    did = economy["seq"]["duel"]
    duel = {"id": did, "a": uid, "b": target, "bet": amount, "status": "pending",
            "t": int(time.time()), "peer": peer_id, "cmid": None}
    economy["duels"][str(did)] = duel

    names = get_names([uid, target])
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Принять", VkKeyboardColor.POSITIVE, {"cmd": "duel", "act": "acc", "id": did})
    kb.add_callback_button("❌ Отклонить", VkKeyboardColor.NEGATIVE, {"cmd": "duel", "act": "dec", "id": did})
    duel["cmid"] = send_get_cmid(
        peer_id,
        f"🔫 Дуэль!\n{mention(uid, names)} вызывает {mention(target, names)} на дуэль.\n"
        f"Ставка: {fmt_num(amount)} 💰 с каждого (банк: {fmt_num(amount * 2)} 💰)\n\n"
        f"{mention(target, names)}, у вас {DUEL_PENDING_SECONDS} сек., чтобы принять вызов.\n"
        f"После принятия на выстрел даётся {DUEL_SHOT_SECONDS} сек.",
        kb.get_keyboard())
    save_economy()

def duel_page(duel, event_line=""):
    names = get_names([duel["a"], duel["b"]])
    lines = [
        f"🔫 Дуэль: {mention(duel['a'], names)} ⚔ {mention(duel['b'], names)}",
        "",
        f"💰 Ставка: {fmt_num(duel['bet'])}",
        f"🏦 Банк: {fmt_num(duel['bet'] * 2)}",
        "",
        f"🎲 Барабан: {DUEL_CHAMBERS} гнёзд, патронов: {duel['bullets']}",
        f"🔫 Выстрелов сделано: {duel['pos']}",
    ]
    if event_line:
        lines += ["", event_line]
    lines += ["", f"👉 Ход: {mention(duel['turn'], names)}. Нажмите «Выстрелить».",
              f"⏱️ На выстрел {DUEL_SHOT_SECONDS} сек., иначе победа соперника."]
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("🔫 Выстрелить", VkKeyboardColor.NEGATIVE,
                           {"cmd": "duel", "act": "shoot", "id": duel["id"]})
    return "\n".join(lines), kb.get_keyboard()

def duel_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    duel = economy["duels"].get(str(p.get("id")))
    if not duel:
        return "Дуэль не найдена."
    if duel["status"] == "done":
        return "Дуэль уже завершена."
    act = p.get("act")
    a_id, b_id, bet = duel["a"], duel["b"], duel["bet"]
    duel["peer"], duel["cmid"] = peer_id, cmid

    if duel["status"] == "pending":
        if time.time() - duel["t"] > DUEL_PENDING_SECONDS:
            duel["status"] = "done"
            save_economy()
            edit_message(peer_id, cmid, f"⌛ Вызов на дуэль истёк: соперник не ответил за {DUEL_PENDING_SECONDS} сек.")
            return None
        if act == "dec":
            if uid not in (a_id, b_id):
                return "Это не ваша дуэль."
            duel["status"] = "done"
            save_economy()
            names = get_names([uid])
            word = "отозвал вызов" if uid == a_id else "отклонил вызов"
            edit_message(peer_id, cmid, f"🔫 Дуэль отменена: {mention(uid, names)} {word}.")
            return None
        if act == "acc":
            if uid != b_id:
                return "Принять вызов может только соперник."
            a, b = get_user(a_id), get_user(b_id)
            if a["money"] < bet or b["money"] < bet:
                duel["status"] = "done"
                save_economy()
                edit_message(peer_id, cmid, "🔫 Дуэль отменена: у одного из игроков не хватает денег на ставку.")
                return None
            a["money"] -= bet
            b["money"] -= bet
            bullets = random.randint(1, DUEL_MAX_BULLETS)
            barrel = [True] * bullets + [False] * (DUEL_CHAMBERS - bullets)
            random.shuffle(barrel)
            duel.update(status="active", barrel=barrel, pos=0, bullets=bullets,
                        turn=random.choice([a_id, b_id]),
                        deadline=time.time() + DUEL_SHOT_SECONDS,
                        acc_t=time.time(), shown=False)
            save_economy()
            answer_event(ev)  # кнопка сразу перестаёт «крутиться»
            names = get_names([duel["turn"]])
            text, kb = duel_page(duel, f"🎲 Жребий: первым стреляет {mention(duel['turn'], names)}")
            with_retry(lambda: edit_message(peer_id, cmid, text, kb))
            duel["shown"] = True
            duel["deadline"] = time.time() + DUEL_SHOT_SECONDS  # отсчёт — когда игроки увидели кнопку
            save_economy()
        return None

    # Дуэль идёт: стрелять может только тот, чей сейчас ход, и только в пределах времени
    if act != "shoot":
        return None
    if uid not in (a_id, b_id):
        return "Вы не участвуете в этой дуэли."
    if time.time() > duel.get("deadline", 0):
        duel_forfeit(duel)
        return "Время на выстрел вышло."
    if uid != duel["turn"]:
        return "Сейчас не ваш ход."

    hit = duel["barrel"][duel["pos"]]
    duel["pos"] += 1
    answer_event(ev)  # кнопка сразу перестаёт «крутиться»
    names = get_names([a_id, b_id])
    if hit:
        duel["status"] = "done"
        get_user(uid)["money"] += bet * 2
        save_economy()
        log_action(peer_id, uid, f"выиграл дуэль {bet * 2}")
        edit_message(peer_id, cmid,
                     f"🔫 Дуэль: {mention(a_id, names)} ⚔ {mention(b_id, names)}\n\n"
                     f"💥 {mention(uid, names)} попал! Победитель — {mention(uid, names)}\n"
                     f"Выигрыш: +{fmt_num(bet * 2)} 💰\n\n"
                     f"Выстрелов: {duel['pos']} | Патронов в барабане было: {duel['bullets']}/{DUEL_CHAMBERS}")
        return None

    duel["turn"] = b_id if uid == a_id else a_id
    duel["deadline"] = time.time() + DUEL_SHOT_SECONDS
    save_economy()
    text, kb = duel_page(duel, f"💨 Осечка! {mention(uid, names)} промахнулся.")
    edit_message(peer_id, cmid, text, kb)
    return None

# ---------- Дуэль: таймеры ----------
def duel_send_or_edit(duel, text, kb=None):
    if duel.get("cmid"):
        edit_message(duel["peer"], duel["cmid"], text, kb)
    else:
        send(duel["peer"], text, kb)

def duel_forfeit(duel):
    """Игрок не успел выстрелить за DUEL_SHOT_SECONDS — победа соперника."""
    loser = duel["turn"]
    winner = duel["b"] if loser == duel["a"] else duel["a"]
    duel["status"] = "done"
    get_user(winner)["money"] += duel["bet"] * 2
    save_economy()
    log_action(duel["peer"], winner, f"выиграл дуэль {duel['bet'] * 2} (соперник не успел)")
    names = get_names([loser, winner])
    duel_send_or_edit(
        duel,
        f"🔫 Дуэль: {mention(duel['a'], names)} ⚔ {mention(duel['b'], names)}\n\n"
        f"⌛ {mention(loser, names)} не успел выстрелить за {DUEL_SHOT_SECONDS} сек.\n"
        f"Победа присуждается {mention(winner, names)}!\n"
        f"Выигрыш: +{fmt_num(duel['bet'] * 2)} 💰")

def check_duel_timers():
    now = time.time()
    for duel in list(economy["duels"].values()):
        if duel["status"] == "done":
            continue
        if not duel.get("peer"):  # дуэль из старой версии бота: возвращаем ставки
            if duel["status"] == "active":
                get_user(duel["a"])["money"] += duel["bet"]
                get_user(duel["b"])["money"] += duel["bet"]
            duel["status"] = "done"
            save_economy()
            continue
        if duel["status"] == "pending":
            if now - duel["t"] > DUEL_PENDING_SECONDS:
                duel["status"] = "done"
                save_economy()
                names = get_names([duel["b"]])
                duel_send_or_edit(duel, f"⌛ Вызов на дуэль истёк: {mention(duel['b'], names)} "
                                        f"не ответил за {DUEL_PENDING_SECONDS} сек.")
        elif not duel.get("shown", True):  # игроки не увидели кнопку «Выстрелить» — возвращаем ставки
            if now - duel.get("acc_t", now) > 20:
                get_user(duel["a"])["money"] += duel["bet"]
                get_user(duel["b"])["money"] += duel["bet"]
                duel["status"] = "done"
                save_economy()
                duel_send_or_edit(duel, "↩ Дуэль не запустилась из-за сбоя — ставки возвращены.")
        elif now > duel.get("deadline", now + 1):
            duel_forfeit(duel)
