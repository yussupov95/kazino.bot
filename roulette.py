# -*- coding: utf-8 -*-
"""Рулетка: картинка стола, ставки, результат."""
import os
import random
import threading
import time
from decimal import Decimal

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    _asset, err_text, MIN_BET, ROULETTE_BAR, ROULETTE_BAR_COLORS, ROULETTE_CACHE_DIR,
    ROULETTE_DELAY, ROULETTE_DELIVER_TRIES, ROULETTE_IMG_V, ROULETTE_MULT, ROULETTE_NUM_CENTER,
    ROULETTE_NUM_HEIGHT, ROULETTE_NUMBER_MULT, ROULETTE_RED, ROULETTE_SHOW_TIMEOUT,
    ROULETTE_TITLES, VIP_WIN_BONUS, vk_upload,
)
from database import economy, get_user, save_economy
from helpers import (
    answer_event, check_bet, edit_message, fmt_num, get_names, LOCK, mention, parse_amount,
    roulette_bet_type, send, send_get_cmid, with_retry,
)
from logs import log_action
from player import win_mult


# ---------- Рулетка (картинка стола с цифрами) ----------
def _roulette_template():
    """Стол рулетки с цифрами (картинка assets/roulette_table.jpg)."""
    from PIL import Image
    return Image.open(_asset("roulette_table.jpg")).convert("RGB")

def _roulette_font(size):
    """Тонкий шрифт только с цифрами 0–9 и «?» (assets/roulette_font.ttf) — цифры одинаковые на любом хостинге."""
    from PIL import ImageFont
    return ImageFont.truetype(_asset("roulette_font.ttf"), size)

def make_roulette_image(n):
    """Стол из шаблона (assets/roulette_table.jpg): нижняя полоса заливается цветом выпавшего числа (красное / чёрное / зелёное 0)
    и на ней пишется число. n=None — полоса «?» (пока рулетка крутится). Готовая картинка кэшируется в cache."""
    name = "q" if n is None else str(n)
    path = os.path.join(ROULETTE_CACHE_DIR, f"table_{name}_v{ROULETTE_IMG_V}.jpg")
    if os.path.exists(path):
        return path
    try:
        from PIL import ImageDraw
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        img = _roulette_template()
        W, H = img.size
        d = ImageDraw.Draw(img)
        if n is None:
            color = ROULETTE_BAR_COLORS["wait"]
        elif n == 0:
            color = ROULETTE_BAR_COLORS["green"]
        else:
            color = ROULETTE_BAR_COLORS["red" if n in ROULETTE_RED else "black"]
        d.rectangle((0, int(H * ROULETTE_BAR[0]), W, int(H * ROULETTE_BAR[1]) - 1), fill=color)
        # число: тонкое, белое, высота как на вашем столе
        text = "?" if n is None else str(n)
        target_h = H * ROULETTE_NUM_HEIGHT
        probe = _roulette_font(100)
        pb = d.textbbox((0, 0), "0", font=probe)
        font = _roulette_font(max(10, round(100 * target_h / (pb[3] - pb[1]))))
        box = d.textbbox((0, 0), text, font=font)
        cx, cy = W * ROULETTE_NUM_CENTER[0], H * ROULETTE_NUM_CENTER[1]
        d.text((cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2), text, font=font, fill=(255, 255, 255))
        img.save(path, quality=92)
        return path
    except Exception as e:
        print(f"Не удалось нарисовать стол рулетки (нужен pip install pillow): {err_text(e)}")
        return None

def roulette_photo(n):
    """Картинка стола в VK (n=None — «?»). Рисуется и загружается один раз на каждое число, дальше берётся из памяти.
    Загрузка повторяется при сбое. Вызывается из потока рулетки — без блокировки бота."""
    key = f"roulette_table_v{ROULETTE_IMG_V}_{'q' if n is None else n}"
    with LOCK:
        att = economy["media"].get(key)
    if att:
        return att
    path = make_roulette_image(n)
    if not path:
        return None
    for attempt in range(4):
        try:
            photo = vk_upload.photo_messages(path)[0]
            att = f"photo{photo['owner_id']}_{photo['id']}"
            break
        except Exception as e:
            print(f"Не удалось загрузить картинку рулетки (попытка {attempt + 1}; у токена должно быть право «Фотографии»): {err_text(e)}")
            time.sleep(1 + attempt)
    else:
        return None
    with LOCK:
        economy["media"][key] = att
        save_economy()
    return att

def roulette_images(peer_id, n):
    """(картинка, пока рулетка крутится; картинка итога). Всегда стол с цифрами — никаких гифок и карточек."""
    return roulette_photo(None), roulette_photo(n)

def roulette_warmup():
    """При запуске в фоне готовит и грузит в VK картинки «?» и 0–36, чтобы во время игры они уже лежали в кэше."""
    try:
        for n in [None] + list(range(37)):
            if not roulette_photo(n):
                print("Рулетка: не удалось подготовить картинки заранее — попробую во время игры")
                return
            time.sleep(0.3)
        print("Рулетка: все картинки стола готовы")
    except Exception as e:
        print(f"Рулетка: ошибка подготовки картинок: {err_text(e)}")

def roulette_mult(bet_type):
    return ROULETTE_NUMBER_MULT if bet_type.startswith("n") else ROULETTE_MULT[bet_type]

def roulette_title(bet_type):
    if bet_type.startswith("n") and bet_type[1:].isdigit():
        return f"{roulette_emoji(int(bet_type[1:]))} число {bet_type[1:]}"
    return ROULETTE_TITLES.get(bet_type)

def roulette_wins(bet_type, n):
    if bet_type.startswith("n"):                       # число (в том числе 0)
        return n == int(bet_type[1:])
    if n == 0:                                         # на 0 проигрывают все ставки, кроме числа
        return False
    if bet_type == "red":
        return n in ROULETTE_RED
    if bet_type == "black":
        return n not in ROULETTE_RED
    if bet_type == "even":
        return n % 2 == 0
    if bet_type == "odd":
        return n % 2 == 1
    if bet_type == "low":
        return n <= 18
    if bet_type == "high":
        return n >= 19
    if bet_type in ("d1", "d2", "d3"):                 # 1-12, 13-24, 25-36
        return (n - 1) // 12 == int(bet_type[1]) - 1
    if bet_type in ("r1", "r2", "r3"):                 # ряд1: 1,4,7… · ряд2: 2,5,8… · ряд3: 3,6,9… (как на столе)
        return n % 3 == int(bet_type[1]) % 3
    return False

def roulette_emoji(n):
    return "🟢" if n == 0 else "🔴" if n in ROULETTE_RED else "⚫"

def prune_roulette():
    now = time.time()
    for k in [k for k, r in economy["roulette"].items() if r["done"] and now - r.get("ts", 0) > 86400]:
        del economy["roulette"][k]

def roulette_usage():
    return ("🎰 Рулетка\n"
            "Выпадает число от 0 до 36.\n"
            "\n"
            "Как играть: рулетка НА_ЧТО СУММА\n"
            "\n"
            "• Конкретное число (0–36): x36\n"
            "• Чёт, нечёт, красное, чёрное, 1-18, 19-36: x2\n"
            "• 1-12, 13-24, 25-36, ряд1, ряд2, ряд3: x3\n"
            "\n"
            "Пример: рулетка чет 1кк (или 1мм)\n"
            "Всё на кон: «вб»\n"
            "\n"
            f"✨ VIP: выигрыш ×{VIP_WIN_BONUS:g}\n"
            "⚠️ Выпал 0: проигрывают все ставки, кроме числа 0.")

def cmd_roulette(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    parts = rest.split()
    if not parts:
        send(peer_id, roulette_usage())
        return

    balance = get_user(uid)["money"]
    first = parts[0].lower().replace("ё", "е")
    if first in ("ряд", "row") and len(parts) > 1 and parts[1] in ("1", "2", "3"):   # «ряд 2» → «ряд2»
        parts = [first + parts[1]] + parts[2:]

    if len(parts) >= 2:                          # рулетка чет 1кк / рулетка 17 500к / рулетка ряд2 вб
        kind, amount_word = roulette_bet_type(parts[0]), parts[1]
        if kind is None and roulette_bet_type(parts[1]):    # перепутали порядок: «рулетка 1кк чет»
            kind, amount_word = roulette_bet_type(parts[1]), parts[0]
        bet = parse_amount(amount_word, balance)
        if kind is None or bet is None:
            if slash or bet is not None or kind is not None:
                send(peer_id, roulette_usage())
            return
        err = check_bet(bet, balance)
        if err:
            send(peer_id, err)
            return
        roulette_spin(peer_id, uid, kind, bet)
        return

    bet = parse_amount(parts[0], balance)        # рулетка 1кк → кнопки с четырьмя ставками
    if bet is None or bet < MIN_BET:             # «рулетка чет» без суммы, «рулетка 17» — показываем правила
        if bet is not None or slash or roulette_bet_type(parts[0]):
            send(peer_id, roulette_usage())
        return
    err = check_bet(bet, balance)
    if err:
        send(peer_id, err)
        return
    kb = VkKeyboard(inline=True)
    for i, (t, label, color) in enumerate((
            ("red", "🔴 Красный", VkKeyboardColor.NEGATIVE),
            ("black", "⚫ Чёрный", VkKeyboardColor.SECONDARY),
            ("even", "✅ Чётный", VkKeyboardColor.POSITIVE),
            ("odd", "❌ Нечётный", VkKeyboardColor.PRIMARY))):
        if i == 2:
            kb.add_line()
        kb.add_callback_button(label, color, {"cmd": "roul", "t": t, "b": bet, "o": uid})
    send(peer_id,
         f"🎰 Рулетка\nСтавка: {fmt_num(bet)} 💰\n\n"
         f"На что ставите? Красное, чёрное, чёт, нечёт — x2 (VIP — x{2 * VIP_WIN_BONUS:g}).\n"
         "Число, 1-12, 13-24, 25-36, ряды и другое — командой, например: рулетка 17 1кк",
         kb.get_keyboard())

def roulette_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это чужая ставка. Напишите «рулетка» сами."
    kind = p.get("t")
    if not kind or not roulette_title(kind):
        return "Неверная ставка."
    if any(r["peer"] == peer_id and r.get("cmid") == cmid for r in economy["roulette"].values()):
        return "Рулетка уже запущена."
    bet = int(p.get("b", 0))
    err = check_bet(bet, get_user(uid)["money"])
    if err:
        return "Недостаточно денег для этой ставки."
    answer_event(ev)
    roulette_spin(peer_id, uid, kind, bet, cmid=cmid)
    return None

# ---------- Рулетка: ставка не пропадает при сбое связи с VK ----------
def refund_roulette(rec, text):
    if rec.get("done") or rec.get("paid"):
        return
    user = get_user(rec["uid"])
    user["money"] += rec["bet"]
    rec["done"] = True
    rec["paid"] = True
    save_economy()
    names = get_names([rec["uid"]])
    try:
        send(rec["peer"], f"{mention(rec['uid'], names)} {text}\n💰 Баланс: {fmt_num(user['money'])}")
    except Exception as e:
        print(f"Не удалось сообщить о возврате ставки в рулетке: {err_text(e)}")

def roulette_spin(peer_id, uid, bet_type, bet, cmid=None):
    """Списывает ставку и выбирает число. Гифку делает и грузит отдельный поток, чтобы бот не «зависал»."""
    user = get_user(uid)
    user["money"] -= bet
    n = random.randint(0, 36)
    economy["seq"]["roulette"] += 1
    rid = str(economy["seq"]["roulette"])
    economy["roulette"][rid] = {
        "peer": peer_id, "cmid": cmid, "uid": uid, "bet": bet, "t": bet_type, "n": n,
        "att": None, "reveal_at": time.time() + 90, "done": False, "ts": int(time.time()),
        "shown": False, "paid": False, "tries": 0,
    }
    save_economy()  # ставка списана и записана вместе с записью о рулетке: при сбое её вернёт проверка
    threading.Thread(target=roulette_present, args=(rid,), daemon=True).start()

def roulette_present(rid):
    rec = economy["roulette"].get(rid)
    if not rec:
        return
    peer_id, uid, bet, bet_type, n = rec["peer"], rec["uid"], rec["bet"], rec["t"], rec["n"]
    att_wait, att_result = roulette_images(peer_id, n)   # долго — без блокировки бота
    with LOCK:
        if rec.get("done"):
            return
        names = get_names([uid])
        text = (f"🎰 Рулетка крутится…\n"
                f"{mention(uid, names)} ставит {fmt_num(bet)} 💰 на {roulette_title(bet_type)}\n\n"
                f"Удачи! 🍀")
        try:
            if rec.get("cmid"):
                with_retry(lambda: edit_message(peer_id, rec["cmid"], text, None, attachment=att_wait))
            else:
                rec["cmid"] = with_retry(lambda: send_get_cmid(peer_id, text, attachment=att_wait))
        except Exception as e:  # VK недоступен: рулетка не началась — ставку возвращаем
            print(f"Не удалось запустить рулетку: {err_text(e)}")
            refund_roulette(rec, "↩ Рулетка не запустилась (нет связи с VK) — ставка возвращена.")
            return
        rec["att"] = att_result                          # картинка с выпавшим числом покажется при итоге
        rec["shown"] = True
        rec["reveal_at"] = time.time() + (ROULETTE_DELAY if att_wait else 2.5)
        save_economy()

def roulette_result_text(rec):
    uid, bet, n = rec["uid"], rec["bet"], rec["n"]
    names = get_names([uid])
    kind = "нулевое" if n == 0 else ("красное" if n in ROULETTE_RED else "чёрное")
    parity = "" if n == 0 else (", чётное" if n % 2 == 0 else ", нечётное")
    lines = [f"🎰 Выпало: {n} {roulette_emoji(n)} ({kind}{parity})",
             f"{mention(uid, names)} — ставка {fmt_num(bet)} 💰 на {roulette_title(rec['t'])}", ""]
    if rec.get("win"):
        base_mult = roulette_mult(rec["t"])
        mult = rec["payout"] / bet
        vip_note = f" (VIP ✨ x{mult:g})" if abs(mult - base_mult) > 1e-9 else ""
        lines.append(f"✅ Выигрыш x{base_mult}{vip_note}: +{fmt_num(rec['payout'])} 💰")
    else:
        lines.append(f"❌ Проигрыш: −{fmt_num(bet)} 💰")
    lines.append(f"💰 Баланс: {fmt_num(get_user(uid)['money'])}")
    return "\n".join(lines)

def check_roulette_reveals():
    now = time.time()
    for rec in list(economy["roulette"].values()):
        if rec["done"]:
            continue
        if not rec.get("shown", True):  # рулетку не удалось показать — возвращаем ставку
            if now - rec.get("ts", now) > ROULETTE_SHOW_TIMEOUT:
                refund_roulette(rec, "↩ Рулетка не запустилась из-за сбоя связи — ставка возвращена.")
            continue
        if rec["reveal_at"] > now or rec.get("retry_at", 0) > now:
            continue

        if not rec.get("paid"):  # итог ставки применяется ровно один раз
            uid, bet = rec["uid"], rec["bet"]
            win = roulette_wins(rec["t"], rec["n"])
            payout = int(Decimal(bet) * Decimal(roulette_mult(rec["t"])) * Decimal(str(win_mult(uid)))) if win else 0
            if win:
                get_user(uid)["money"] += payout
                log_action(rec["peer"], uid, f"рулетка: выигрыш {payout}")
            rec.update(paid=True, win=win, payout=payout)
            save_economy()

        text = roulette_result_text(rec)  # доставка повторяется, пока VK недоступен
        try:
            if rec.get("cmid"):
                edit_message(rec["peer"], rec["cmid"], text, None, attachment=rec.get("att"))
            else:
                send(rec["peer"], text)
            rec["done"] = True
        except Exception as e:
            rec["tries"] = rec.get("tries", 0) + 1
            rec["retry_at"] = now + min(60, 2 ** rec["tries"])
            if rec["tries"] >= 3 and rec.get("att"):     # VK не принимает смену картинки — пусть хотя бы итог придёт текстом
                rec["att"] = None
            print(f"Не удалось показать итог рулетки (попытка {rec['tries']}): {err_text(e)}")
            if rec["tries"] >= ROULETTE_DELIVER_TRIES:  # деньги уже начислены, сообщение доставить не вышло
                rec["done"] = True
        save_economy()
