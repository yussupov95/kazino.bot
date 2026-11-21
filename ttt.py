# -*- coding: utf-8 -*-
"""Крестики-нолики."""
import random
import re
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import err_text, MIN_BET, MINES_KEYCAPS
from crash import check_crash_games
from database import economy, get_user, save_economy
from helpers import (
    answer_event, drone_active, edit_message, fmt_num, get_names, mention, no_target,
    parse_amount, parse_target, send, send_get_cmid, with_retry,
)
from logs import log_action
from mines import check_idle_mines, prune_games
from wipe import note_surrender


# ---------- Крестики-нолики ----------
TTT_PENDING_SECONDS = 60        # на принятие вызова
TTT_MOVE_SECONDS = 120          # на ход
TTT_GRACE_SECONDS = 60          # предупреждение перед поражением за время (вдруг не работают кнопки)
TTT_IDLE_REFUND = 1800          # игра стоит так долго — ставки возвращаются обоим
TTT_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
TTT_MARK = {0: "⬜", 1: "❌", 2: "⭕"}
TTT_WIN_MARK = {1: "❎", 2: "🟢"}
TTT_KEYCAPS = MINES_KEYCAPS[:9]

def ttt_usage():
    return ("❌⭕ Крестики-нолики\n"
            "Игра с участником беседы на деньги.\n"
            "• Победитель забирает банк\n"
            "• Ничья: ставки возвращаются\n"
            "\n"
            "Как играть:\n"
            "• крно СУММА (ответом на сообщение соперника)\n"
            "• крно @соперник СУММА\n"
            "\n"
            "Пример: крно 1кк")

def ttt_winner(board):
    for line in TTT_LINES:
        a, b, c = line
        if board[a] and board[a] == board[b] == board[c]:
            return board[a], line
    return None, None

def ttt_board_text(g, line=None):
    cells = []
    for i, v in enumerate(g["board"]):
        if v == 0:
            cells.append(TTT_KEYCAPS[i])
        elif line and i in line:
            cells.append(TTT_WIN_MARK[v])
        else:
            cells.append(TTT_MARK[v])
    return "\n".join(" ".join(cells[r:r + 3]) for r in range(0, 9, 3))

def ttt_head_lines(g, names):
    return ["❌⭕ Крестики-нолики",
            f"{TTT_MARK[1]} {mention(g['px'], names)}  ⚔  {TTT_MARK[2]} {mention(g['po'], names)}",
            f"💰 Ставка: {fmt_num(g['bet'])} с каждого · Банк: {fmt_num(g['bet'] * 2)}"]

def ttt_page(g, note="", names=None):
    names = names or get_names([g["px"], g["po"]])
    lines = ttt_head_lines(g, names) + ["", ttt_board_text(g), ""]
    if note:
        lines += [note, ""]
    turn_mark = TTT_MARK[1 if g["turn"] == g["px"] else 2]
    lines += [f"▶ Ход: {turn_mark} {mention(g['turn'], names)}  (⏱ {TTT_MOVE_SECONDS} сек.)",
              "⌨ Не работают кнопки? Напишите: ход 5 (номер клетки)"]
    kb = VkKeyboard(inline=True)
    for i, v in enumerate(g["board"]):
        if i and i % 3 == 0:
            kb.add_line()
        if v == 0:
            label, color = str(i + 1), VkKeyboardColor.SECONDARY
        elif v == 1:
            label, color = TTT_MARK[1], VkKeyboardColor.NEGATIVE
        else:
            label, color = TTT_MARK[2], VkKeyboardColor.PRIMARY
        kb.add_callback_button(label, color, {"cmd": "ttt", "a": "mv", "g": g["gid"], "c": i})
    kb.add_line()
    kb.add_callback_button("🏳 Сдаться", VkKeyboardColor.SECONDARY, {"cmd": "ttt", "a": "sur", "g": g["gid"]})
    return "\n".join(lines), kb.get_keyboard()

def ttt_edit_or_send(g, text, kb=None):
    try:
        if g.get("cmid"):
            edit_message(g["peer"], g["cmid"], text, kb)
        else:
            send(g["peer"], text, kb)
    except Exception as e:
        print(f"Не удалось обновить сообщение «Крестиков-ноликов»: {err_text(e)}")
        if kb is None:
            try:
                send(g["peer"], text)
            except Exception:
                pass

def ttt_render(g, note=""):
    """Показать поле. Ошибка VK не отменяет ход: игра остаётся в базе, следующее нажатие обновит сообщение."""
    text, kb = ttt_page(g, note)
    try:
        edit_message(g["peer"], g["cmid"], text, kb)
    except Exception as e:
        print(f"Не удалось показать поле «Крестиков-ноликов»: {err_text(e)}")

def ttt_refund(g, text):
    if g.get("done"):
        return
    get_user(g["px"])["money"] += g["bet"]
    get_user(g["po"])["money"] += g["bet"]
    g["done"], g["st"] = True, "end"
    save_economy()
    ttt_edit_or_send(g, text)

def ttt_finish(g, winner=None, how="line", loser=None):
    """Итог партии: победитель забирает банк, ничья — ставки возвращаются."""
    if g.get("done"):
        return
    bet, pot = g["bet"], g["bet"] * 2
    g["done"], g["st"] = True, "end"
    names = get_names([g["px"], g["po"]])
    line = None
    if winner:
        get_user(winner)["money"] += pot
        mark = 1 if winner == g["px"] else 2
        win_mark, found = ttt_winner(g["board"])
        if win_mark == mark:
            line = found
        reason = {"surrender": f"🏳 {mention(loser, names)} сдался.\n",
                  "timeout": f"⌛ {mention(loser, names)} не сделал ход вовремя.\n"}.get(how, "")
        tail = (f"{reason}🏆 Победитель: {TTT_MARK[mark]} {mention(winner, names)}\n"
                f"💰 Выигрыш: +{fmt_num(pot)} 💰")
        log_action(g["peer"], winner, f"крестики-нолики: выигрыш {pot}")
    else:
        get_user(g["px"])["money"] += bet
        get_user(g["po"])["money"] += bet
        tail = "🤝 Ничья! Ставки возвращены обоим игрокам."
    save_economy()
    text = "\n".join(ttt_head_lines(g, names) + ["", ttt_board_text(g, line), "", tail])
    ttt_edit_or_send(g, text)
    if winner and how == "surrender" and loser:      # два «сдался» подряд одному сопернику — владельцу уведомление
        try:
            note_surrender(g, loser, winner)
        except Exception as e:
            print(f"Ошибка слежки за сдачами: {err_text(e)}")

def ttt_move(g, uid, cell, ev=None):
    """Ход игрока (кнопкой или командой «ход N»). Возвращает подсказку для игрока или None."""
    if g.get("st") != "play" or g.get("done"):
        return "Игра уже завершена."
    if uid not in (g["px"], g["po"]):
        return "Вы не участвуете в этой игре."
    if g["turn"] != uid:
        return "Сейчас ход соперника."
    if not 0 <= cell < 9:
        return "Неверная клетка."
    if g["board"][cell]:
        ttt_render(g)                       # на случай, если прошлое сообщение не обновилось
        return "Эта клетка уже занята."
    now = time.time()
    g["board"][cell] = 1 if uid == g["px"] else 2
    g["ta"] = int(now)
    g.pop("sur_u", None)
    g.pop("warned", None)
    if ev is not None:
        answer_event(ev)                    # кнопка сразу перестаёт «крутиться»
    win_mark, _ = ttt_winner(g["board"])
    if win_mark:
        ttt_finish(g, winner=uid)
    elif all(g["board"]):
        ttt_finish(g, winner=None)
    else:
        g["turn"] = g["po"] if uid == g["px"] else g["px"]
        g["dl"] = now + TTT_MOVE_SECONDS
        save_economy()
        ttt_render(g)
    return None

def ttt_surrender(g, uid):
    if uid not in (g["px"], g["po"]):
        return "Вы не участвуете в этой игре."
    now = time.time()
    if g.get("sur_u") == uid and now - g.get("sur_t", 0) <= 10:      # второе нажатие подряд = подтверждение
        ttt_finish(g, winner=g["po"] if uid == g["px"] else g["px"], how="surrender", loser=uid)
        return None
    g["sur_u"], g["sur_t"] = uid, now
    return "Нажмите «Сдаться» ещё раз, чтобы подтвердить."

def ttt_pending_action(ev, g, act):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    a_id, b_id, bet = g["owner"], g["opp"], g["bet"]
    if time.time() - g["t"] > TTT_PENDING_SECONDS:
        g["done"], g["st"] = True, "end"
        save_economy()
        ttt_edit_or_send(g, "⌛ Вызов в крестики-нолики истёк: соперник не ответил.")
        return None
    if act == "dec":
        if uid not in (a_id, b_id):
            return "Это не ваша игра."
        g["done"], g["st"] = True, "end"
        save_economy()
        names = get_names([uid])
        word = "отозвал вызов" if uid == a_id else "отклонил вызов"
        ttt_edit_or_send(g, f"❌⭕ Игра отменена: {mention(uid, names)} {word}.")
        return None
    if act != "acc":
        return None
    if uid != b_id:
        return "Принять вызов может только соперник."
    a, b = get_user(a_id), get_user(b_id)
    if a["money"] < bet or b["money"] < bet:
        g["done"], g["st"] = True, "end"
        save_economy()
        ttt_edit_or_send(g, "❌⭕ Игра отменена: у одного из игроков не хватает денег на ставку.")
        return None
    a["money"] -= bet
    b["money"] -= bet
    px, po = random.sample([a_id, b_id], 2)
    now = time.time()
    g.update(st="play", board=[0] * 9, px=px, po=po, turn=px, dl=now + TTT_MOVE_SECONDS,
             ta=int(now), acc_t=now, shown=False, peer=peer_id, cmid=cmid)
    save_economy()
    answer_event(ev)
    names = get_names([px, po])
    text, kb = ttt_page(g, f"🎲 Жребий: первым ходит {TTT_MARK[1]} {mention(px, names)}", names)
    try:
        with_retry(lambda: edit_message(peer_id, cmid, text, kb))
        g["shown"] = True
        g["dl"] = time.time() + TTT_MOVE_SECONDS      # отсчёт — с момента, когда игроки увидели поле
        save_economy()
    except Exception as e:                            # поле не показалось — через 20 сек. ставки вернутся
        print(f"Не удалось показать поле «Крестиков-ноликов»: {err_text(e)}")
    return None

def ttt_action(ev, p):
    uid = ev["user_id"]
    g = economy["games"].get(f"ttt:{p.get('g')}")
    if not g or not g.get("ttt"):
        return "Игра не найдена."
    if g.get("done"):
        return "Игра уже завершена."
    act = p.get("a")
    if g.get("st") == "pending":
        return ttt_pending_action(ev, g, act)
    g["peer"], g["cmid"] = ev["peer_id"], ev["conversation_message_id"]
    if act == "mv":
        try:
            cell = int(p.get("c", -1))
        except (TypeError, ValueError):
            cell = -1
        return ttt_move(g, uid, cell, ev)
    if act == "sur":
        return ttt_surrender(g, uid)
    return None

def ttt_text_move(msg, rest):
    """«ход 5» — ход без кнопок (если кнопки не работают). True — сообщение разобрано как ход."""
    m = re.fullmatch(r"([1-9])", rest.strip())
    if not m:
        return False
    uid, peer_id = msg["from_id"], msg["peer_id"]
    game = next((g for g in economy["games"].values()
                 if g.get("ttt") and g.get("st") == "play" and not g.get("done") and g.get("peer") == peer_id
                 and uid in (g.get("px"), g.get("po"))), None)
    if not game:
        return False
    note = ttt_move(game, uid, int(m.group(1)) - 1)
    if note:
        send(peer_id, f"⚠ {note}")
    return True

def check_ttt_games():
    now = time.time()
    for g in list(economy["games"].values()):
        if not g.get("ttt") or g.get("done"):
            continue
        st = g.get("st")
        if st == "pending":
            if now - g.get("t", now) > TTT_PENDING_SECONDS:
                g["done"], g["st"] = True, "end"
                save_economy()
                names = get_names([g["opp"]])
                ttt_edit_or_send(g, f"⌛ Вызов в крестики-нолики истёк: {mention(g['opp'], names)} "
                                    f"не ответил за {TTT_PENDING_SECONDS} сек.")
        elif st == "play":
            if not g.get("shown", True):
                if now - g.get("acc_t", now) > 20:
                    ttt_refund(g, "↩ Игра не запустилась из-за сбоя — ставки возвращены.")
            elif now - g.get("ta", g.get("t", now)) > TTT_IDLE_REFUND:
                ttt_refund(g, "↩ Игра зависла — ставки возвращены обоим игрокам.")
            elif now > g.get("dl", now + 1):
                if drone_active():                      # кнопки не работают у всех — время не списываем
                    g["dl"] = now + 60
                    save_economy()
                elif not g.get("warned"):               # сперва предупреждение: вдруг кнопки не нажимаются
                    g["warned"] = True
                    g["dl"] = now + TTT_GRACE_SECONDS
                    save_economy()
                    names = get_names([g["turn"]])
                    try:
                        send(g["peer"], f"⏳ {mention(g['turn'], names)}, ваш ход в крестики-нолики! "
                                        f"У вас {TTT_GRACE_SECONDS} сек., иначе засчитается поражение.\n"
                                        "Не работают кнопки? Напишите: ход 5 (номер клетки)")
                    except Exception as e:
                        print(f"Не удалось напомнить о ходе: {err_text(e)}")
                else:
                    loser = g["turn"]
                    ttt_finish(g, winner=g["po"] if loser == g["px"] else g["px"], how="timeout", loser=loser)

def ttt_active_of(uid):
    return next((g for g in economy["games"].values()
                 if g.get("ttt") and not g.get("done")
                 and (g.get("owner") == uid or (g.get("st") == "play" and uid in (g.get("px"), g.get("po"))))), None)

def cmd_ttt(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if uid <= 0:
        return
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, ttt_usage())
        return
    balance = get_user(uid)["money"]
    parts = tail.split()
    amount = parse_amount(parts[0], balance) if parts else None
    if amount is None:
        send(peer_id, ttt_usage())
        return
    if target <= 0 or target == uid:
        send(peer_id, "⛔ Выберите в соперники другого участника беседы.")
        return
    if amount < MIN_BET:
        send(peer_id, f"⚠ Минимальная ставка: {fmt_num(MIN_BET)} 💰")
        return
    if balance < amount:
        send(peer_id, f"⚠ У вас недостаточно денег. Баланс: {fmt_num(balance)} 💰")
        return
    if get_user(target)["money"] < amount:
        send(peer_id, "⚠ У соперника недостаточно денег для такой ставки.")
        return
    if ttt_active_of(uid):
        send(peer_id, "⚠ У вас уже есть незавершённая игра в крестики-нолики.")
        return

    prune_games()
    economy["seq"]["ttt"] = economy["seq"].get("ttt", 0) + 1
    gid = economy["seq"]["ttt"]
    game = economy["games"][f"ttt:{gid}"] = {
        "ttt": True, "st": "pending", "gid": gid, "owner": uid, "opp": target, "bet": amount,
        "done": False, "t": int(time.time()), "peer": peer_id, "cmid": None,
    }
    names = get_names([uid, target])
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Принять", VkKeyboardColor.POSITIVE, {"cmd": "ttt", "a": "acc", "g": gid})
    kb.add_callback_button("❌ Отклонить", VkKeyboardColor.NEGATIVE, {"cmd": "ttt", "a": "dec", "g": gid})
    try:
        game["cmid"] = send_get_cmid(
            peer_id,
            f"❌⭕ Крестики-нолики!\n{mention(uid, names)} вызывает {mention(target, names)} на партию.\n"
            f"💰 Ставка: {fmt_num(amount)} с каждого · Банк: {fmt_num(amount * 2)}\n\n"
            f"{mention(target, names)}, у вас {TTT_PENDING_SECONDS} сек., чтобы принять вызов.\n"
            "Победитель забирает банк, при ничьей ставки возвращаются.",
            kb.get_keyboard())
    except Exception as e:                      # деньги ещё не списаны — просто отменяем игру
        print(f"Не удалось отправить вызов в крестики-нолики: {err_text(e)}")
        del economy["games"][f"ttt:{gid}"]
        return
    save_economy()

def check_new_games():
    """Раз в секунду (из tick_loop): краш, крестики-нолики, зависшие «Мины»."""
    for fn in (check_crash_games, check_ttt_games, check_idle_mines):
        try:
            fn()
        except Exception as e:
            print(f"Ошибка таймера ({fn.__name__}): {err_text(e)}")
