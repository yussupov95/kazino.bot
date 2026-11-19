# -*- coding: utf-8 -*-
"""Игра «Краш»."""
import math
import random
import re
import time
from decimal import Decimal

from config import err_text, VIP_WIN_BONUS
from database import economy, get_user, save_economy
from helpers import (
    check_bet, edit_message, fmt_num, get_names, mention, parse_amount, send, send_get_cmid,
    with_retry,
)
from logs import log_action
from mines import prune_games
from player import win_mult


# ---------- Игра «Краш» ----------
CRASH_HOUSE_EDGE = 0.03         # комиссия казино 3% (как в «Минах»)
CRASH_CAP = 15.0                # потолок ракеты. Игрокам нигде не показывается
CRASH_RATE = 0.25               # скорость роста коэффициента: x(t) = e^(0.25·t)
CRASH_FRAME = 1.0               # кадр анимации раз в секунду
CRASH_LAUNCH_DELAY = 1.5        # пауза на «запуск»
CRASH_TRACK = 14                # длина трассы ракеты
CRASH_MIN_X100 = 101            # минимальный множитель x1.01

def crash_usage():
    return ("🚀 Краш\n"
            "Ракета взлетает, и чем дольше она в воздухе, тем выше коэффициент.\n"
            "Выберите множитель, до которого она должна долететь.\n"
            "\n"
            "Как играть: краш СУММА МНОЖИТЕЛЬ\n"
            "• краш 100к 1.5\n"
            "• краш 1кк 2\n"
            "• краш вб 1.3 (всё на кон)\n"
            "\n"
            "Результат:\n"
            "• Долетела: выигрыш = ставка × множитель\n"
            "• Разбилась раньше: ставка проиграна\n"
            "\n"
            f"✨ VIP: выигрыш ×{VIP_WIN_BONUS:g}")

def crash_roll():
    """Где разобьётся ракета, в сотых (150 = x1.50). Шанс долететь до x равен (1 − комиссия) / x."""
    u = random.random()
    raw = (1 - CRASH_HOUSE_EDGE) / (1 - u)
    return max(100, min(int(CRASH_CAP * 100), int(raw * 100)))

def crash_parse_x(word):
    """«1.5», «1,5», «x2», «2х» → множитель в сотых (150, 200). None — не число."""
    w = word.strip().lower().replace(",", ".").replace("х", "x").strip("x")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,2})?", w):
        return None
    return int((Decimal(w) * 100).to_integral_value())

def crash_active_of(uid):
    return next((g for g in economy["games"].values()
                 if g.get("crash") and g.get("owner") == uid and not g.get("done")), None)

def crash_track(game, m100, crashed=False):
    """Трасса: ракета едет к цели 🎯 (шкала логарифмическая — как растёт коэффициент)."""
    tx = game["tx"]
    frac = 0.0 if m100 <= 100 else min(1.0, math.log(m100 / 100) / math.log(tx / 100))
    pos = min(CRASH_TRACK - 1, int(frac * (CRASH_TRACK - 1)))
    return "▫" * pos + ("💥" if crashed else "🚀") + "▫" * (CRASH_TRACK - 1 - pos) + "🎯"

def crash_head(game):
    return (f"🚀 Краш · {game.get('who', '')}\n"
            f"💰 Ставка: {fmt_num(game['bet'])} · 🎯 Цель: x{game['tx'] / 100:.2f}")

def crash_text(game, m100, state):
    if state == "launch":
        return f"{crash_head(game)}\n\n🔥 Запуск ракеты…"
    return f"{crash_head(game)}\n\n{crash_track(game, m100)}\n📈 x{m100 / 100:.2f}"

def crash_result_text(game):
    bet, tx, cp = game["bet"], game["tx"], game["cp"]
    bal = f"💰 Баланс: {fmt_num(get_user(game['owner'])['money'])}"
    if game.get("win"):
        mult = game["payout"] / bet
        vip_note = f" (VIP ✨ x{mult:g})" if abs(mult - tx / 100) > 1e-9 else ""
        return (f"{crash_head(game)}\n\n{crash_track(game, tx)}\n"
                f"✅ Ракета долетела до x{tx / 100:.2f}!\n"
                f"Выигрыш x{tx / 100:.2f}{vip_note}: +{fmt_num(game['payout'])} 💰\n{bal}")
    if cp <= 100:
        crash_line = "💥 Ракета взорвалась на старте — x1.00!"
    else:
        crash_line = f"💥 Ракета разбилась на x{cp / 100:.2f}!"
    return (f"{crash_head(game)}\n\n{crash_track(game, cp, crashed=True)}\n"
            f"{crash_line}\nПроигрыш: −{fmt_num(bet)} 💰\n{bal}")

def crash_refund(game, text):
    if game.get("done") or game.get("paid"):
        return
    user = get_user(game["owner"])
    user["money"] += game["bet"]
    game["done"] = game["paid"] = True
    save_economy()
    msg_text = f"{text}\n💰 Баланс: {fmt_num(user['money'])}"
    try:
        if game.get("cmid"):
            edit_message(game["peer"], game["cmid"], msg_text)
        else:
            send(game["peer"], msg_text)
    except Exception:
        try:
            send(game["peer"], msg_text)
        except Exception as e:
            print(f"Не удалось сообщить о возврате ставки в «Краше»: {err_text(e)}")

def crash_finish(game):
    """Итог полёта. Деньги считаются ровно один раз (флаг paid), доставка сообщения повторяется при сбое."""
    if not game.get("paid"):
        uid, bet = game["owner"], game["bet"]
        win = game["cp"] >= game["tx"]
        payout = 0
        if win:
            payout = int(Decimal(bet) * Decimal(game["tx"]) / Decimal(100) * Decimal(str(win_mult(uid))))
            get_user(uid)["money"] += payout
            log_action(game["peer"], uid, f"краш: x{game['tx'] / 100:.2f}, выигрыш {payout}")
        else:
            log_action(game["peer"], uid, f"краш: разбилась на x{game['cp'] / 100:.2f}, проигрыш {bet}")
        game.update(paid=True, win=win, payout=payout)
        save_economy()
    text = crash_result_text(game)
    try:
        if game.get("cmid"):
            edit_message(game["peer"], game["cmid"], text)
        else:
            send(game["peer"], text)
        game["done"] = True
    except Exception as e:
        game["tries"] = game.get("tries", 0) + 1
        game["retry_at"] = time.time() + min(30, 2 ** game["tries"])
        if game["tries"] >= 20:           # деньги уже посчитаны, сообщение доставить не вышло
            game["done"] = True
        print(f"Не удалось показать итог «Краша» (попытка {game['tries']}): {err_text(e)}")
    save_economy()

def check_crash_games():
    """Раз в секунду: кадры полёта и итог. Состояние лежит в базе, поэтому перезапуск бота ничего не ломает."""
    now = time.time()
    for game in list(economy["games"].values()):
        if not game.get("crash") or game.get("done"):
            continue
        if not game.get("shown", True):            # ракета не взлетела (сбой VK) — ставку возвращаем
            if now - game.get("t", now) > 30:
                crash_refund(game, "↩ Ракета не взлетела из-за сбоя связи — ставка возвращена.")
            continue
        t0 = game.get("t0") or game.get("t", now)
        if now < t0 or game.get("retry_at", 0) > now:
            continue
        el = now - t0
        stop_el = math.log(min(game["tx"], game["cp"]) / 100) / CRASH_RATE
        if el >= stop_el:
            crash_finish(game)
            continue
        frame = int(el / CRASH_FRAME)
        if frame > game.get("fr", -1):
            game["fr"] = frame
            m100 = int(math.exp(CRASH_RATE * el) * 100)
            try:
                edit_message(game["peer"], game["cmid"], crash_text(game, m100, "fly"))
            except Exception as e:
                print(f"Не удалось показать кадр «Краша»: {err_text(e)}")

def cmd_crash(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if uid <= 0:
        return
    parts = rest.split()
    if not parts:
        send(peer_id, crash_usage())
        return
    user = get_user(uid)
    balance = user["money"]
    a_word, x_word = parts[0], (parts[1] if len(parts) > 1 else "")
    if x_word and (re.search(r"[xх]", a_word, re.I)
                   or (re.fullmatch(r"\d+[.,]\d+", a_word) and not re.fullmatch(r"\d+[.,]\d+", x_word))):
        a_word, x_word = x_word, a_word            # «краш 1.5 100к» — порядок не важен
    bet = parse_amount(a_word, balance)
    if bet is None:
        if slash:
            send(peer_id, crash_usage())
        return                                      # «краш на неё» — обычная фраза
    if not x_word:
        send(peer_id, crash_usage())
        return
    tx = crash_parse_x(x_word)
    if tx is None or tx < CRASH_MIN_X100:
        send(peer_id, "⚠ Укажите множитель числом больше 1, например: краш 100к 1.5")
        return
    if tx > int(CRASH_CAP * 100):
        send(peer_id, "⚠ Такой множитель недоступен — выберите поменьше.")
        return
    err = check_bet(bet, balance)
    if err:
        send(peer_id, err)
        return
    if crash_active_of(uid):
        send(peer_id, "🚀 Ваша ракета ещё в полёте — дождитесь результата.")
        return

    names = get_names([uid])
    user["money"] -= bet
    economy["seq"]["crash"] = economy["seq"].get("crash", 0) + 1
    prune_games()
    game = economy["games"][f"crash:{economy['seq']['crash']}"] = {
        "crash": True, "owner": uid, "bet": bet, "tx": tx, "cp": crash_roll(), "done": False,
        "t": int(time.time()), "peer": peer_id, "cmid": None, "shown": False, "fr": -1,
        "who": mention(uid, names),
    }
    save_economy()          # ставка списана и записана вместе с игрой: при сбое её вернёт проверка
    try:
        game["cmid"] = with_retry(lambda: send_get_cmid(peer_id, crash_text(game, 100, "launch")))
        game["shown"] = True
        game["t0"] = time.time() + CRASH_LAUNCH_DELAY
        save_economy()
    except Exception as e:
        print(f"Не удалось запустить «Краш»: {err_text(e)}")
        crash_refund(game, "↩ Ракета не взлетела (нет связи с VK) — ставка возвращена.")
