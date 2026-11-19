# -*- coding: utf-8 -*-
"""Игра «Мины» и закрытие брошенных игр (деньги не пропадают)."""
import random
import time
from decimal import Decimal

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    err_text, MIN_BET, MINES_CELLS, MINES_COEF_BONUS, MINES_HOUSE_EDGE, MINES_IDLE_SETTLE,
    MINES_KEYCAPS, MINES_MAX, MINES_MIN, MINES_ROW, MINES_VERSION, VIP_WIN_BONUS,
)
from database import economy, get_user, save_economy, vip_active
from helpers import (
    answer_event, check_bet, edit_message, fmt_num, parse_amount, send, with_retry,
)


# ---------- Игра «Мины» ----------
def mines_coef(mines, opened, vip=False):
    """Коэффициент после `opened` открытых алмазов: 1/вероятность × (1 − комиссия). VIP — ещё ×VIP_WIN_BONUS."""
    if opened <= 0:
        return 1.0
    p = 1.0
    for i in range(opened):
        p *= (MINES_CELLS - mines - i) / (MINES_CELLS - i)
    coef = (1 - MINES_HOUSE_EDGE) * MINES_COEF_BONUS / p
    if vip:
        coef *= VIP_WIN_BONUS
    return round(coef, 2)
def mines_vip(game):
    return vip_active(get_user(game["owner"]))

def mines_payout(game):
    """Выплата = ставка × коэффициент (без ошибок округления float)."""
    coef = mines_coef(game["m"], len(game["opened"]), mines_vip(game))
    return int(Decimal(game["bet"]) * Decimal(str(coef)))

def mines_grid(game, reveal=False, hit=None):
    cells = []
    for i in range(MINES_CELLS):
        if i in game["opened"]:
            cells.append("💎")
        elif reveal and i in game["mines"]:
            cells.append("💥" if i == hit else "💣")
        elif reveal:
            cells.append("⬜")
        else:
            cells.append(MINES_KEYCAPS[i])
    return "\n".join(" ".join(cells[r:r + MINES_ROW]) for r in range(0, MINES_CELLS, MINES_ROW))

def mines_bet_page(uid):
    text = ("💣 Мины\n"
            "Выберите ставку (в процентах от баланса) 👇\n"
            "\n"
            "Или сразу напишите:\n"
            "• мины 100к\n"
            "• мины 1кк\n"
            "• мины вб (всё на кон)")
    kb = VkKeyboard(inline=True)
    for pct, label in ((10, "10%"), (25, "25%"), (50, "50%"), (100, "Всё")):
        kb.add_callback_button(label, VkKeyboardColor.SECONDARY,
                               payload={"cmd": "mines", "act": "bet", "p": pct, "o": uid})
    return text, kb.get_keyboard()

def mines_pick_page(bet, uid):
    text = (f"💣 Мины\n"
            f"💰 Ставка: {fmt_num(bet)}\n"
            "\n"
            f"Выберите количество мин ({MINES_MIN}–{MINES_MAX}). Всего клеток: {MINES_CELLS}.\n"
            "Чем больше мин и открытых алмазов 💎, тем выше коэффициент.")
    kb = VkKeyboard(inline=True)
    for i, m in enumerate(range(MINES_MIN, MINES_MAX + 1)):
        if i and i % MINES_ROW == 0:
            kb.add_line()
        kb.add_callback_button(f"{m} 💣", VkKeyboardColor.SECONDARY,
                               payload={"cmd": "mines", "act": "start", "b": bet, "m": m, "o": uid})
    return text, kb.get_keyboard()
def mines_final_text(game, user, head, hit=None, win=0):
    vip = mines_vip(game)
    coef = mines_coef(game["m"], len(game["opened"]), vip)
    lines = ["💣 Мины" + (" ✨ VIP" if vip else ""), head, "", mines_grid(game, reveal=True, hit=hit), ""]
    if win:
        lines += [f"📈 Коэффициент: x{coef:.2f}", f"✅ Выигрыш: +{fmt_num(win)} 💰"]
    else:
        lines.append(f"❌ Проигрыш: −{fmt_num(game['bet'])} 💰")
    lines.append(f"💰 Баланс: {fmt_num(user['money'])}")
    return "\n".join(lines)

def prune_games():
    """Удаляет игры старше суток (сообщения старше 24 ч всё равно нельзя редактировать)."""
    now = time.time()
    old = [k for k, g in economy["games"].items() if now - g.get("t", 0) > 86400]
    for k in old:
        settle_abandoned_game(economy["games"][k])      # деньги, лежащие в брошенной игре, не пропадают
        del economy["games"][k]

def cmd_mines(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    balance = get_user(uid)["money"]
    rest = rest.strip()

    if rest:
        bet = parse_amount(rest.split()[0], balance)
        if bet is None:
            if slash:
                send(peer_id, "ℹ️ Использование: мины СТАВКА (например: мины 100к, мины 1кк, мины все или мины вб)")
            return  # «мины на дороге» — обычная фраза
        err = check_bet(bet, balance)
        if err:
            send(peer_id, err)
            return
        text, kb = mines_pick_page(bet, uid)
    else:
        if balance < MIN_BET:
            send(peer_id, "⚠ У вас недостаточно денег для игры. Получите «бонус».")
            return
        text, kb = mines_bet_page(uid)
    send(peer_id, text, kb)

# ---------- Надёжность: повторы, возврат ставок, один экземпляр ----------
def check_stuck_games():
    """Игра, у которой не получилось показать поле (сбой VK/сети), не должна «съедать» ставку."""
    now = time.time()
    for g in list(economy["games"].values()):
        if "mines" in g and not g.get("done") and not g.get("shown", True) and now - g["t"] > 20:
            refund_mines(g, "↩ Игра «Мины» не запустилась — ставка возвращена.")

# ---------- Мины: квадрат 3×3 одним сообщением ----------
# В inline-клавиатуре VK максимум 10 кнопок: 9 клеток (3×3) + кнопка «Забрать» = ровно 10.
def mines_game_page(game):
    vip = mines_vip(game)
    opened = len(game["opened"])
    coef = mines_coef(game["m"], opened, vip)
    lines = [
        "💣 Мины" + (" ✨ VIP" if vip else ""),
        f"💰 Ставка: {fmt_num(game['bet'])}",
        f"💣 Мин: {game['m']} из {MINES_CELLS} клеток",
        "",
        f"💎 Открыто алмазов: {opened}",
        f"📈 Коэффициент: x{coef:.2f}",
    ]
    if opened:
        lines.append(f"💵 Выигрыш сейчас: {fmt_num(mines_payout(game))} 💰")
    lines.append(f"➡️ Следующий алмаз: x{mines_coef(game['m'], opened + 1, vip):.2f}")

    kb = VkKeyboard(inline=True)
    for i in range(MINES_CELLS):
        if i and i % MINES_ROW == 0:
            kb.add_line()
        is_open = i in game["opened"]
        kb.add_callback_button("💎" if is_open else str(i + 1),
                               VkKeyboardColor.POSITIVE if is_open else VkKeyboardColor.SECONDARY,
                               {"cmd": "mines", "act": "open", "c": i, "o": game["owner"]})
    kb.add_line()
    kb.add_callback_button("💰 Забрать", VkKeyboardColor.POSITIVE,
                           {"cmd": "mines", "act": "cash", "o": game["owner"]})
    return "\n".join(lines), kb.get_keyboard()

def mines_render(game):
    text, kb = mines_game_page(game)
    with_retry(lambda: edit_message(game["peer"], game["cmid"], text, kb))

def mines_finish(game, user, head, hit=None, win=0):
    """Конец игры: сообщение показывает итог без кнопок."""
    text = mines_final_text(game, user, head, hit=hit, win=win)
    with_retry(lambda: edit_message(game["peer"], game["cmid"], text))
def refund_mines(game, text):
    user = get_user(game["owner"])
    user["money"] += game["bet"]
    game["done"] = True
    save_economy()
    msg_text = f"{text}\nБаланс: {fmt_num(user['money'])} 💰"
    try:
        edit_message(game["peer"], game["cmid"], msg_text)
    except Exception:
        try:
            send(game["peer"], msg_text)
        except Exception as e:
            print(f"Не удалось сообщить о возврате ставки: {err_text(e)}")

def migrate_legacy_mines():
    """Незавершённые игры «Мин» старых версий (другое поле) — возвращаем ставки, ничего не теряется."""
    for g in economy["games"].values():
        if "mines" in g and not g.get("done") and g.get("v") != MINES_VERSION:
            get_user(g["owner"])["money"] += g["bet"]
            g["done"] = True
    save_economy()

def mines_action(ev, p):
    """Обрабатывает нажатия кнопок «Мин». Возвращает короткую подсказку для игрока или None."""
    peer_id = ev["peer_id"]
    uid = ev["user_id"]
    cmid = ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это чужая игра. Напишите «мины» сами."

    act = p.get("act")
    key = f"{peer_id}:{cmid}"
    games = economy["games"]
    user = get_user(uid)

    # Шаг 1: выбрана ставка в процентах → выбор числа мин
    if act == "bet":
        pct = int(p.get("p", 0))
        if pct not in (10, 25, 50, 100):
            return "Неверная ставка."
        bet = user["money"] * pct // 100
        if bet < MIN_BET:
            return "Недостаточно денег. Получите «бонус»."
        answer_event(ev)  # кнопка сразу перестаёт «крутиться»
        text, kb = mines_pick_page(bet, uid)
        edit_message(peer_id, cmid, text, kb)
        return None

    # Шаг 2: выбрано число мин → начало игры, ставка списывается
    if act == "start":
        if key in games:
            return "Эта игра уже начата."
        bet, mines_count = int(p.get("b", 0)), int(p.get("m", 0))
        if not MINES_MIN <= mines_count <= MINES_MAX:
            return "Неверное число мин."
        err = check_bet(bet, user["money"])
        if err:
            return "Недостаточно денег для этой ставки."
        user["money"] -= bet
        prune_games()
        game = games[key] = {
            "v": MINES_VERSION,
            "owner": uid,
            "bet": bet,
            "m": mines_count,
            "mines": random.sample(range(MINES_CELLS), mines_count),
            "opened": [],
            "done": False,
            "t": int(time.time()),
            "peer": peer_id,
            "cmid": cmid,
            "shown": False,
            "ta": int(time.time()),
        }
        save_economy()
        answer_event(ev)  # кнопка сразу перестаёт «крутиться»
        try:
            mines_render(game)
            game["shown"] = True
            save_economy()
        except Exception as e:  # поле не показалось — ставка не должна пропасть
            print(f"Не удалось показать поле «Мин»: {err_text(e)}")
            refund_mines(game, "↩ Игру не удалось запустить — ставка возвращена.")
        return None

    game = games.get(key)
    if not game or game.get("v") != MINES_VERSION:
        return "Игра не найдена."
    if game["done"]:
        return "Игра уже завершена."

    if act == "open":
        cell = int(p.get("c", -1))
        if not 0 <= cell < MINES_CELLS or cell in game["opened"]:
            return "Эта клетка уже открыта."

        if cell in game["mines"]:  # проигрыш
            game["done"] = True
            save_economy()
            answer_event(ev)
            mines_finish(game, user, "💥 Вы попали на мину!", hit=cell)
            return None

        game["opened"].append(cell)
        game["ta"] = int(time.time())
        if len(game["opened"]) == MINES_CELLS - game["m"]:  # открыты все алмазы
            win = mines_payout(game)
            user["money"] += win
            game["done"] = True
            save_economy()
            answer_event(ev)
            mines_finish(game, user, "🏆 Вы открыли все алмазы!", win=win)
            return None

        save_economy()
        answer_event(ev)
        mines_render(game)
        return None

    if act == "cash":
        if not game["opened"]:
            return "Сначала откройте хотя бы один алмаз."
        win = mines_payout(game)
        user["money"] += win
        game["done"] = True
        save_economy()
        answer_event(ev)
        mines_finish(game, user, "✅ Вы забрали выигрыш!", win=win)
        return None

    return None

# ---------- Деньги не пропадают: брошенные игры закрываются сами ----------
def settle_abandoned_game(g):
    """Игра брошена и уходит в архив: деньги, лежащие в ней, возвращаются игрокам (молча ничего не пропадает)."""
    try:
        if g.get("done"):
            return
        if "mines" in g:
            get_user(g["owner"])["money"] += mines_payout(g) if g.get("opened") else g["bet"]
        elif g.get("ttt") and g.get("st") == "play":
            get_user(g["px"])["money"] += g["bet"]
            get_user(g["po"])["money"] += g["bet"]
        elif g.get("crash") and not g.get("paid"):
            get_user(g["owner"])["money"] += g["bet"]
        g["done"] = True
    except Exception as e:
        print(f"Не удалось закрыть брошенную игру: {err_text(e)}")

def check_idle_mines():
    """«Мины», в которых давно не нажимали кнопки (кнопки не работали, игрок ушёл): алмазы открыты —
    выигрыш выплачивается, нет — ставка возвращается."""
    now = time.time()
    for g in list(economy["games"].values()):
        if "mines" not in g or g.get("done") or g.get("v") != MINES_VERSION or not g.get("shown", True):
            continue
        if now - g.get("ta", g.get("t", now)) < MINES_IDLE_SETTLE:
            continue
        if not g.get("opened"):
            refund_mines(g, "↩ Игра «Мины» не продолжилась — ставка возвращена.")
            continue
        user = get_user(g["owner"])
        win = mines_payout(g)
        user["money"] += win
        g["done"] = True
        save_economy()
        text = mines_final_text(g, user, "⏱ Давно не было ходов — выигрыш выплачен автоматически.", win=win)
        try:
            edit_message(g["peer"], g["cmid"], text)
        except Exception as e:
            print(f"Не удалось обновить «Мины» после авто-выплаты: {err_text(e)}")
            try:
                send(g["peer"], text)
            except Exception:
                pass
