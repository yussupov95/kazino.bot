# -*- coding: utf-8 -*-
"""Рыбалка."""
import os
import random
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    err_text, FISH_CELLS, FISH_COMMON, FISH_COOLDOWN, FISH_IMAGE, FISH_MEDIUM_CHANCE,
    FISH_MEDIUM_RANGE, FISH_NAMES, FISH_RARE_CHANCE, FISH_RARE_RANGE, ROULETTE_CACHE_DIR,
)
from database import get_user, save_economy
from helpers import answer_event, edit_message, fmt_duration, fmt_num, send
from images import cached_photo, drop_photo_cache, _font


# ---------- Рыбалка ----------
def make_fishing_image():
    """Рисует одну картинку: человек рыбачит с причала на озере (без анимации)."""
    path = os.path.join(ROULETTE_CACHE_DIR, "fishing.png")
    if os.path.exists(path):
        return path
    try:
        from PIL import Image, ImageDraw
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        S = 2
        W, H = 800 * S, 450 * S
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)

        def lerp(a, b, t):
            return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

        horizon = int(H * 0.56)
        for y in range(horizon):                         # небо
            d.line([(0, y), (W, y)], fill=lerp((86, 160, 225), (255, 206, 150), y / horizon))
        for y in range(horizon, H):                      # озеро
            d.line([(0, y), (W, y)], fill=lerp((90, 160, 205), (14, 58, 98), (y - horizon) / (H - horizon)))

        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # солнце с ореолом
        gd = ImageDraw.Draw(glow)
        sx, sy = int(W * 0.74), int(H * 0.42)
        for r, a in ((190, 30), (140, 45), (100, 70)):
            gd.ellipse((sx - r * S, sy - r * S, sx + r * S, sy + r * S), fill=(255, 235, 170, a))
        gd.ellipse((sx - 62 * S, sy - 62 * S, sx + 62 * S, sy + 62 * S), fill=(255, 244, 205, 255))
        img = Image.alpha_composite(img.convert("RGBA"), glow)
        d = ImageDraw.Draw(img)

        d.polygon([(0, horizon), (0, horizon - 60 * S), (120 * S, horizon - 95 * S), (260 * S, horizon - 40 * S),
                   (380 * S, horizon - 80 * S), (520 * S, horizon - 30 * S), (640 * S, horizon - 70 * S),
                   (W, horizon - 25 * S), (W, horizon)], fill=(52, 96, 92))
        for i in range(9):                               # блики солнца на воде
            y = horizon + (10 + i * 16) * S
            half = (60 - i * 4) * S
            d.rounded_rectangle((sx - half, y, sx + half, y + 5 * S), radius=3 * S, fill=(255, 226, 160))
        for cx, cy, r in ((120, 70, 34), (170, 62, 26), (95, 78, 22), (560, 54, 28), (610, 62, 20)):   # облака
            d.ellipse(((cx - r) * S, (cy - r // 2) * S, (cx + r) * S, (cy + r // 2) * S), fill=(255, 255, 255, 235))

        deck = int(H * 0.70)                             # причал
        d.rectangle((0, deck, int(W * 0.44), deck + 22 * S), fill=(140, 94, 52))
        for x in range(0, int(W * 0.44), 46 * S):
            d.line([(x, deck), (x, deck + 22 * S)], fill=(96, 62, 32), width=2 * S)
        for x in (30 * S, 190 * S, 340 * S):
            d.rectangle((x, deck + 22 * S, x + 14 * S, H), fill=(88, 58, 30))

        fx, fy = int(W * 0.27), deck                     # рыбак
        u = S
        d.rounded_rectangle((fx - 62 * u, fy - 18 * u, fx - 8 * u, fy + 62 * u), radius=8 * u, fill=(46, 66, 120))
        d.rounded_rectangle((fx - 8 * u, fy - 18 * u, fx + 46 * u, fy + 62 * u), radius=8 * u, fill=(46, 66, 120))
        d.rectangle((fx - 66 * u, fy + 56 * u, fx - 2 * u, fy + 72 * u), fill=(30, 30, 30))
        d.rectangle((fx - 4 * u, fy + 56 * u, fx + 50 * u, fy + 72 * u), fill=(30, 30, 30))
        d.rounded_rectangle((fx - 40 * u, fy - 112 * u, fx + 38 * u, fy + 4 * u), radius=18 * u, fill=(200, 64, 52))
        d.line([(fx + 22 * u, fy - 84 * u), (fx + 96 * u, fy - 70 * u)], fill=(200, 64, 52), width=20 * u)
        d.ellipse((fx + 88 * u, fy - 80 * u, fx + 108 * u, fy - 60 * u), fill=(236, 196, 156))
        d.ellipse((fx - 22 * u, fy - 156 * u, fx + 24 * u, fy - 108 * u), fill=(236, 196, 156))
        d.ellipse((fx - 46 * u, fy - 168 * u, fx + 48 * u, fy - 140 * u), fill=(232, 196, 92))
        d.pieslice((fx - 26 * u, fy - 190 * u, fx + 28 * u, fy - 142 * u), 180, 360, fill=(232, 196, 92))
        d.ellipse((fx + 6 * u, fy - 136 * u, fx + 12 * u, fy - 130 * u), fill=(40, 30, 20))

        tip = (int(W * 0.64), int(H * 0.27))             # удочка, леска и поплавок
        hand = (fx + 98 * u, fy - 70 * u)
        d.line([hand, tip], fill=(96, 62, 30), width=6 * u)
        d.line([(hand[0] + 60 * u, hand[1] - 38 * u), tip], fill=(96, 62, 30), width=3 * u)
        bx, by = int(W * 0.67), int(H * 0.83)
        pts = []
        for k in range(31):
            t = k / 30
            pts.append((tip[0] + (bx - tip[0]) * t, tip[1] + (by - tip[1]) * t + 18 * u * (1 - (2 * t - 1) ** 2)))
        d.line(pts, fill=(240, 240, 240), width=2 * u)
        for r, a in ((34, 120), (22, 190)):
            d.ellipse((bx - r * u, by - r * u // 3 + 4 * u, bx + r * u, by + r * u // 3 + 4 * u),
                      outline=(235, 245, 255), width=2 * u)
        d.pieslice((bx - 10 * u, by - 10 * u, bx + 10 * u, by + 10 * u), 180, 360, fill=(220, 40, 40))
        d.pieslice((bx - 10 * u, by - 10 * u, bx + 10 * u, by + 10 * u), 0, 180, fill=(250, 250, 250))

        for fxx, fyy, ang in ((int(W * 0.86), int(H * 0.70), 0), (int(W * 0.52), int(H * 0.66), 1)):   # прыгающие рыбы
            d.ellipse((fxx - 22 * u, fyy - 9 * u, fxx + 22 * u, fyy + 9 * u), fill=(255, 150, 60))
            d.polygon([(fxx - 20 * u, fyy), (fxx - 40 * u, fyy - 12 * u), (fxx - 40 * u, fyy + 12 * u)], fill=(255, 130, 40))
            d.ellipse((fxx + 10 * u, fyy - 4 * u, fxx + 15 * u, fyy + 1 * u), fill=(30, 30, 30))
            d.arc((fxx - 40 * u, fyy + 10 * u, fxx + 40 * u, fyy + 40 * u), 200, 340, fill=(235, 245, 255), width=2 * u)
        for bx2, by2 in ((330, 60), (372, 82), (420, 48)):   # птицы
            d.arc(((bx2 - 14) * S, by2 * S, bx2 * S, (by2 + 14) * S), 190, 350, fill=(40, 50, 70), width=2 * S)
            d.arc((bx2 * S, by2 * S, (bx2 + 14) * S, (by2 + 14) * S), 190, 350, fill=(40, 50, 70), width=2 * S)

        font = _font(54 * S)
        d.text((26 * S + 3 * S, H - 80 * S + 3 * S), "РЫБАЛКА", font=font, fill=(10, 30, 50))
        d.text((26 * S, H - 80 * S), "РЫБАЛКА", font=font, fill=(255, 245, 210))
        img.convert("RGB").resize((800, 450), Image.LANCZOS).save(path)
        return path
    except Exception as e:
        print(f"Не удалось нарисовать картинку рыбалки (pip install pillow) — будет без картинки: {err_text(e)}")
        return None

def roll_fish():
    r = random.random()
    if r < FISH_RARE_CHANCE:
        tier, price = "rare", random.randrange(FISH_RARE_RANGE[0], FISH_RARE_RANGE[1] + 1, 500_000)
    elif r < FISH_RARE_CHANCE + FISH_MEDIUM_CHANCE:
        tier, price = "medium", random.randrange(FISH_MEDIUM_RANGE[0], FISH_MEDIUM_RANGE[1] + 1, 100_000)
    else:
        tier, price = "common", FISH_COMMON
    name, emoji = random.choice(FISH_NAMES[tier])
    return {"tier": tier, "name": name, "emoji": emoji, "price": price}

def fishing_page(user, uid, cell=None, fish=None):
    per_row = FISH_CELLS // 2
    cells = ["🌊"] * FISH_CELLS
    if fish is not None and cell is not None:
        cells[cell] = fish["emoji"]
    grid = "\n".join(" ".join(cells[r:r + per_row]) for r in range(0, FISH_CELLS, per_row))
    lines = ["🎣 Рыбалка", "", grid, ""]
    if fish:
        note = {"common": "", "medium": " — хороший улов!", "rare": " — РЕДКАЯ рыба! 🎉"}[fish["tier"]]
        lines.append(f"{fish['emoji']} Поймана рыба: {fish['name']} — +{fmt_num(fish['price'])} 💰{note}")
    else:
        lines.append("Выберите клетку, куда забросить удочку.")
    lines += [
        "",
        f"🐟 Поймано рыб: {user.get('fish_n', 0)}",
        f"💵 Заработано: {fmt_num(user.get('fish_sum', 0))} 💰",
        f"💰 Баланс: {fmt_num(user['money'])}",
        "",
        f"⏱️ Удочку можно забрасывать раз в {fmt_duration(FISH_COOLDOWN)}.",
        "",
        "Улов:",
        f"• Чаще всего: {fmt_num(FISH_COMMON)} 💰",
        f"• Иногда: {fmt_num(FISH_MEDIUM_RANGE[0])}–{fmt_num(FISH_MEDIUM_RANGE[1])} 💰",
        f"• С шансом {int(FISH_RARE_CHANCE * 100)}%: {fmt_num(FISH_RARE_RANGE[0])}–{fmt_num(FISH_RARE_RANGE[1])} 💰",
    ]
    kb = VkKeyboard(inline=True)
    for i in range(FISH_CELLS):
        if i and i % per_row == 0:
            kb.add_line()
        kb.add_callback_button(f"🌊 {i + 1}", VkKeyboardColor.PRIMARY, {"cmd": "fish", "c": i, "o": uid})
    return "\n".join(lines), kb.get_keyboard()

def cmd_fishing(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    text, kb = fishing_page(get_user(uid), uid)
    att = fishing_attachment(peer_id)
    try:
        send(peer_id, text, kb, attachment=att)
    except Exception as e:
        if not att:
            raise
        print(f"Не удалось отправить картинку рыбалки, шлю без неё: {err_text(e)}")
        drop_photo_cache("fishing")
        send(peer_id, text, kb)

def fish_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это чужая удочка. Напишите «рыбалка» сами."
    user = get_user(uid)
    now = time.time()
    left = user.get("last_fish", 0) + FISH_COOLDOWN - now
    if left > 0:
        return f"🎣 Рыба ещё не клюёт. Подождите {fmt_duration(left)}."

    cell = max(0, min(int(p.get("c", 0)), FISH_CELLS - 1))
    fish = roll_fish()
    user["money"] += fish["price"]
    user["last_fish"] = now
    user["fish_n"] = user.get("fish_n", 0) + 1
    user["fish_sum"] = user.get("fish_sum", 0) + fish["price"]
    save_economy()
    answer_event(ev)  # кнопка сразу перестаёт «крутиться»

    text, kb = fishing_page(user, uid, cell, fish)
    att = fishing_attachment(peer_id)
    try:
        edit_message(peer_id, cmid, text, kb, attachment=att)
    except Exception as e:
        print(f"Не удалось обновить рыбалку с картинкой, пробую без неё: {err_text(e)}")
        edit_message(peer_id, cmid, text, kb)
    return None

# ---------- Картинки: общий кэш загрузки фото в VK ----------
def fishing_attachment(peer_id):
    """Картинка рыбалки: свой файл fishing.jpg рядом с ботом или нарисованная."""
    path = FISH_IMAGE if os.path.exists(FISH_IMAGE) else make_fishing_image()
    return cached_photo(peer_id, path, "fishing") if path else None
