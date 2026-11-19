# -*- coding: utf-8 -*-
"""Деньги, опыт и промокоды от Тех специалистов (с разрешением владельца) и заморозка за частые выдачи."""
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    CHAT_OFFSET, DIRECT_GRANT_MAX, err_text, FREEZE_SECONDS, GRANT_BURST_COUNT,
    GRANT_BURST_SECONDS, MAX_EXP_GRANT, MAX_GRANT, MIN_LEVEL_TO_GIVE, MIN_LEVEL_TO_PROMO,
    OWNER_ID, PROMO_TTL, ROLES,
)
from database import (
    economy, exp_text, freeze_left, get_level, get_user, player_level, promo_expired, punish,
    save_economy, save_punish,
)
from helpers import (
    answer_event, deny, edit_message, fmt_num, get_names, HANDLERS, mention, no_target,
    parse_amount, parse_target, send,
)
from logs import log_action
from player import add_exp


# ---------- Промокоды ----------
def create_promo(peer_id, actor, name, amount, uses):
    key = name.lower()
    if key in economy["promos"] and not promo_expired(economy["promos"][key]):
        send(peer_id, f"⚠ Промокод «{name}» уже существует.")
        return
    economy["promos"][key] = {
        "name": name,
        "amount": amount,
        "uses": uses,
        "used_by": [],
        "by": actor,
        "t": int(time.time()),
        "exp": time.time() + PROMO_TTL,
    }
    save_economy()
    log_action(peer_id, actor, f"создал промокод {name}: {amount} x{uses}")
    send(peer_id, f"🎫 Промокод «{name}» создан.\n"
                  f"Награда: {fmt_num(amount)} 💰\n"
                  f"Использований: {uses}\n"
                  f"Действует: {PROMO_TTL // 3600} ч.\n\n"
                  f"Активировать: промокод {name}"
                  + ("\n\n⚠ Название совпадает с командой бота, поэтому просто словом он не сработает — "
                     "только «промокод " + name + "»."
                     if key.replace("ё", "е") in HANDLERS else f"\nили просто написать: {name}"))

def activate_promo(peer_id, uid, name, quiet=False):
    """quiet=True — человек написал просто слово без «промокод»: про «уже активировали» молчим, чтобы не спамить."""
    promo = economy["promos"].get(name.lower())
    if promo and promo_expired(promo):
        del economy["promos"][name.lower()]
        save_economy()
        promo = None
    if not promo:
        send(peer_id, "❌ Промокод не найден или уже истёк (промокоды действуют 24 часа).")
        return
    if uid in promo["used_by"]:
        if not quiet:
            send(peer_id, "⚠ Вы уже активировали этот промокод.")
        return
    if len(promo["used_by"]) >= promo["uses"]:
        if not quiet:
            send(peer_id, "❌ Этот промокод уже закончился.")
        return

    user = get_user(uid)
    user["money"] += promo["amount"]
    promo["used_by"].append(uid)
    save_economy()
    left = promo["uses"] - len(promo["used_by"])
    send(peer_id, f"🎫 Промокод «{promo['name']}» активирован!\n"
                  f"+{fmt_num(promo['amount'])} 💰\n"
                  f"💰 Баланс: {fmt_num(user['money'])}\n"
                  f"Осталось активаций: {left}")

def _promo_norm(s):
    return s.strip().lower().replace("ё", "е").strip(".,!?…:;()\"'«»-—_ ")

def try_plain_promo(msg, text):
    """Написали просто слово-промокод (без «промокод»): если такой промокод действует — активируем.
    Если слово не промокод, бот молчит — обычное общение не трогаем."""
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    if uid <= 0 or not economy["promos"]:
        return
    word = _promo_norm(text)
    promo = None
    for key, p in economy["promos"].items():            # без учёта регистра, «ё/е» и знаков вокруг слова
        if _promo_norm(key) == word and not promo_expired(p):
            promo = p
            break
    if not promo:
        return                                          # не промокод — молчим, это обычное сообщение
    if uid != OWNER_ID and freeze_left(uid) > 0:     # заморозка: команды недоступны
        return
    activate_promo(peer_id, uid, promo["name"], quiet=True)

def cmd_promo(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    args = rest.split()
    create_usage = ("ℹ️ Создание: промокод НАЗВАНИЕ СУММА ИСПОЛЬЗОВАНИЙ\n"
                    "Пример: промокод Борз 1кк 1\n\nАктивация: промокод НАЗВАНИЕ")

    if not args:
        send(peer_id, "ℹ️ Активировать промокод: промокод НАЗВАНИЕ")
    elif len(args) == 1:
        activate_promo(peer_id, uid, args[0])
    elif len(args) == 3:
        name, amount_text, uses_text = args
        amount = parse_amount(amount_text)
        if amount is None or not uses_text.isdigit() or int(uses_text) < 1 or len(name) > 32:
            if slash or get_level(peer_id, uid) >= MIN_LEVEL_TO_PROMO:
                send(peer_id, create_usage)
            return
        if get_level(peer_id, uid) < MIN_LEVEL_TO_PROMO:
            send(peer_id, f"⛔ Создавать промокоды могут {ROLES[MIN_LEVEL_TO_PROMO]} и выше.")
            return
        names = get_names([uid])
        submit_action(peer_id, uid, "promo", {"name": name, "amount": amount, "uses": int(uses_text)},
                      f"создать промокод «{name}»: {fmt_num(amount)} 💰 × {uses_text} использ.")
    elif slash or (len(args) == 2 and get_level(peer_id, uid) >= MIN_LEVEL_TO_PROMO):
        send(peer_id, create_usage)

# ---------- Выдача денег и опыта (Тех специалист) ----------
def cmd_give_money(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_GIVE:
        deny(msg, rest, slash, f"⛔ Выдавать деньги могут {ROLES[MIN_LEVEL_TO_GIVE]} и выше.")
        return

    usage = ("ℹ️ Использование: деньги СУММА — ответом на сообщение участника\n"
             "Или: деньги ID СУММА\nПример: деньги 5кк")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    amount = parse_amount(parts[0]) if parts else None
    if amount is None or target <= 0:
        send(peer_id, usage)
        return
    if amount > MAX_GRANT:
        send(peer_id, f"⚠ Максимум за раз: {fmt_num(MAX_GRANT)} 💰")
        return

    names = get_names([target])
    summary = f"выдать деньги: {fmt_num(amount)} 💰 → {mention(target, names)}"
    submit_action(peer_id, actor, "give", {"target": target, "amount": amount}, summary)

def cmd_give_exp(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_GIVE:
        deny(msg, rest, slash, f"⛔ Выдавать опыт могут {ROLES[MIN_LEVEL_TO_GIVE]} и выше.")
        return

    usage = ("ℹ️ Использование: опыт ЧИСЛО — ответом на сообщение участника\n"
             f"Или: опыт ID ЧИСЛО\nПример: опыт 50 (максимум за раз: {MAX_EXP_GRANT})")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    if not parts or not parts[0].isdigit() or not 0 < int(parts[0]) <= MAX_EXP_GRANT or target <= 0:
        send(peer_id, usage)
        return

    amount = int(parts[0])
    level_note = add_exp(target, amount)
    save_economy()
    log_action(peer_id, actor, f"выдал опыт {amount} → {target}")
    names = get_names([target])
    text = f"⭐ {mention(target, names)} получил {amount} exp\nОпыт: {exp_text(get_user(target)['exp'])}"
    if level_note:
        text += "\n\n" + level_note
    send(peer_id, text)

# ---------- Деньги от Тех специалистов: разрешение владельца ----------
def request_approval(peer_id, actor, kind, data, summary):
    """Тех специалист хочет выдать/забрать деньги или создать промокод: спрашиваем владельца в ЛС."""
    economy["seq"]["approval"] += 1
    aid = economy["seq"]["approval"]
    economy["approvals"][str(aid)] = {
        "id": aid, "kind": kind, "peer": peer_id, "actor": actor,
        "data": data, "summary": summary, "status": "pending", "t": int(time.time()),
    }
    save_economy()

    names = get_names([actor])
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Разрешить", VkKeyboardColor.POSITIVE, {"cmd": "appr", "a": "ok", "id": aid})
    kb.add_callback_button("⛔ Запретить", VkKeyboardColor.NEGATIVE, {"cmd": "appr", "a": "no", "id": aid})
    try:
        send(OWNER_ID,
             f"🔐 Запрос на действие\n"
             f"Тех: {mention(actor, names)} (id{actor})\n"
             f"Действие: {summary}\n"
             f"Беседа: #{peer_id - CHAT_OFFSET}",
             kb.get_keyboard())
    except Exception as e:
        print(f"Не удалось отправить запрос владельцу: {err_text(e)}")
        economy["approvals"][str(aid)]["status"] = "failed"
        save_economy()
        send(peer_id, "❌ Не удалось отправить запрос владельцу. "
                      "Владелец должен один раз написать боту в личные сообщения.")
        return
    send(peer_id, "⏳ Запрос отправлен владельцу на подтверждение. Действие выполнится после его «Разрешить».")

def do_give_money(peer_id, actor, target, amount):
    user = get_user(target)
    user["money"] += amount
    save_economy()
    log_action(peer_id, actor, f"выдал деньги {amount} → {target}")
    names = get_names([target])
    send(peer_id, f"💰 {mention(target, names)} получил {fmt_num(amount)} 💰\n"
                  f"Баланс: {fmt_num(user['money'])} 💰")

def do_take_money(peer_id, actor, target, amount):
    user = get_user(target)
    take = min(amount, user["money"])
    names = get_names([target])
    if take <= 0:
        send(peer_id, f"⚠ У {mention(target, names)} нет денег — забирать нечего.")
        return
    user["money"] -= take
    save_economy()
    log_action(peer_id, actor, f"забрал деньги {take} у {target}")
    send(peer_id, f"💸 У {mention(target, names)} забрано {fmt_num(take)} 💰\n"
                  f"Баланс: {fmt_num(user['money'])} 💰")

def approval_action(ev, p):
    appr = economy["approvals"].get(str(p.get("id")))
    if not appr:
        return "Запрос не найден."
    if appr["status"] != "pending":
        return "Запрос уже обработан."

    ok = p.get("a") == "ok"
    appr["status"] = "approved" if ok else "denied"
    save_economy()
    answer_event(ev)

    actor = appr["actor"]
    names = get_names([actor])
    edit_message(ev["peer_id"], ev["conversation_message_id"],
                 f"🔐 Запрос на действие\nТех: {mention(actor, names)} (id{actor})\n"
                 f"Действие: {appr['summary']}\n\n{'✅ Разрешено' if ok else '⛔ Запрещено'}")
    if ok:
        execute_action(appr["kind"], appr["peer"], actor, appr["data"])
    else:
        send(appr["peer"], f"⛔ Владелец запретил действие Теха {mention(actor, names)}: {appr['summary']}")
    return None

def handle_approval_callback(ev, p):
    note = None
    try:
        if ev["user_id"] != OWNER_ID:
            note = "Это действие доступно только владельцу."
        else:
            note = approval_action(ev, p)
    finally:
        answer_event(ev, note)

def cmd_take_money(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_GIVE:
        deny(msg, rest, slash, f"⛔ Забирать деньги могут {ROLES[MIN_LEVEL_TO_GIVE]} и выше.")
        return

    usage = ("ℹ️ Использование: забрать СУММА — ответом на сообщение участника\n"
             "Или: забрать ID СУММА / забрать @упоминание СУММА\nПример: забрать 5кк (или забрать все)")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    if target <= 0:
        send(peer_id, usage)
        return
    balance = get_user(target)["money"]
    parts = tail.split()
    amount = parse_amount(parts[0], balance) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    names = get_names([target])
    if amount > balance:
        send(peer_id, f"⚠ У {mention(target, names)} только {fmt_num(balance)} 💰")
        return
    summary = f"забрать деньги: {fmt_num(amount)} 💰 у {mention(target, names)}"
    submit_action(peer_id, actor, "take", {"target": target, "amount": amount}, summary)

# ---------- Заморозка Тех специалистов за частые выдачи ----------
def register_direct_grant(peer_id, actor):
    """Выдача до DIRECT_GRANT_MAX без разрешения. Слишком частые выдачи — заморозка всех команд."""
    now = time.time()
    recent = [t for t in punish["grant_log"].get(str(actor), []) if now - t < GRANT_BURST_SECONDS]
    if len(recent) + 1 >= GRANT_BURST_COUNT:
        punish["grant_log"][str(actor)] = []
        punish["freezes"][str(actor)] = now + FREEZE_SECONDS
        save_punish()
        log_action(peer_id, actor, f"заморожен на {FREEZE_SECONDS // 60} мин: частые выдачи денег")
        names = get_names([actor])
        send(peer_id, f"🧊 {mention(actor, names)} заморожен на {FREEZE_SECONDS // 60} мин: "
                      f"{GRANT_BURST_COUNT} выдачи денег за {GRANT_BURST_SECONDS} сек. Выдача отменена, "
                      "все команды недоступны.")
        try:
            send(OWNER_ID, f"🧊 Тех {mention(actor, names)} (id{actor}) заморожен на {FREEZE_SECONDS // 60} мин: "
                           f"{GRANT_BURST_COUNT} выдачи денег за {GRANT_BURST_SECONDS} сек. "
                           f"Беседа: #{peer_id - CHAT_OFFSET}")
        except Exception as e:
            print(f"Не удалось сообщить владельцу о заморозке: {err_text(e)}")
        return False
    recent.append(now)
    punish["grant_log"][str(actor)] = recent
    save_punish()
    return True

def submit_action(peer_id, actor, kind, data, summary):
    """Владелец действует сразу. Тех специалист: выдача денег до DIRECT_GRANT_MAX — сразу
    (с защитой от частых выдач), всё остальное и большие суммы — только с разрешения владельца."""
    if actor == OWNER_ID:
        execute_action(kind, peer_id, actor, data)
    elif kind == "give" and data["amount"] <= DIRECT_GRANT_MAX:
        if register_direct_grant(peer_id, actor):
            execute_action(kind, peer_id, actor, data)
    else:
        request_approval(peer_id, actor, kind, data, summary)

def do_take_exp(peer_id, actor, target, amount):
    user = get_user(target)
    old_level = player_level(user["exp"])[0]
    take = min(amount, user["exp"])
    names = get_names([target])
    if take <= 0:
        send(peer_id, f"⚠ У {mention(target, names)} нет опыта — забирать нечего.")
        return
    user["exp"] -= take
    save_economy()
    log_action(peer_id, actor, f"забрал опыт {take} у {target}")
    new_level, new_name, _, _ = player_level(user["exp"])
    text = f"⭐ У {mention(target, names)} забрано {take} exp\nОпыт: {exp_text(user['exp'])}"
    if new_level < old_level:
        text += f"\n⬇️ Уровень понижен: {new_level} — {new_name}"
    send(peer_id, text)

def execute_action(kind, peer_id, actor, d):
    if kind == "give":
        do_give_money(peer_id, actor, d["target"], d["amount"])
    elif kind == "take":
        do_take_money(peer_id, actor, d["target"], d["amount"])
    elif kind == "takeexp":
        do_take_exp(peer_id, actor, d["target"], d["amount"])
    elif kind == "promo":
        create_promo(peer_id, actor, d["name"], d["amount"], d["uses"])

def cmd_take_exp(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_GIVE:
        deny(msg, rest, slash, f"⛔ Забирать опыт могут {ROLES[MIN_LEVEL_TO_GIVE]} и выше.")
        return

    usage = ("ℹ️ Использование: забрать опыт ЧИСЛО — ответом на сообщение участника\n"
             "Или: забрать опыт ID ЧИСЛО\nПример: забрать опыт 50 (или забрать опыт все)")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    if target <= 0:
        send(peer_id, usage)
        return
    exp = get_user(target)["exp"]
    parts = tail.split()
    if parts and parts[0].lower() in ("все", "всё"):
        amount = exp
    elif parts and parts[0].isdigit():
        amount = int(parts[0])
    else:
        amount = None
    if not amount:
        send(peer_id, usage)
        return
    names = get_names([target])
    if amount > exp:
        send(peer_id, f"⚠ У {mention(target, names)} только {exp} exp")
        return
    summary = f"забрать опыт: {amount} exp у {mention(target, names)}"
    submit_action(peer_id, actor, "takeexp", {"target": target, "amount": amount}, summary)
