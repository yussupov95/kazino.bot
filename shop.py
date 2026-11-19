# -*- coding: utf-8 -*-
"""Магазин аксессуаров, персонажи и гардероб."""
import json
import math
import os
import random
import re

from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

from config import (
    CHAT_OFFSET, err_text, _find, GROUP_ID, OWNER_ID, ROULETTE_CACHE_DIR, vk, vk_upload,
)
from database import data, economy, get_user, save_economy
from helpers import answer_event, delete_message, edit_message, fmt_num, send, send_get_cmid
from images import cached_photo
from logs import log_action


# ---------- Персонажи для профиля ----------
KK = 1_000_000
ART_VERSION = 7   # версия рисунков: при изменении старые картинки (кэш и загрузки в VK) обновляются сами
SHOP_SLOTS = ("char",)
SHOP_TITLES = {"char": "🎭 Персонажи"}
# id: (раздел, название, цена в кк, описание). Число в id (char5 → 5) — «ID модели» для команды «продать перс»
SHOP_ITEMS = {
    # --- старые персонажи: из магазина УБРАНЫ (RETIRED_ITEMS). У тех, кто их купил, они остаются в «мои аксессуары»,
    #     цена нужна для границ на аукционе. Теперь их можно только купить у игрока на «аукцион». ---
    "char1": ("char", "Сакура", 500, "Серебряные волосы, сад сакуры"),
    "char2": ("char", "Готика", 500, "Тёмная кофта и черепа"),
    "char3": ("char", "Секретная", 1000, "Тот самый секретный персонаж"),     # СЕКРЕТНЫЙ: пока не куплен — «???»
    "char4": ("char", "Живой персонаж", 2000, "🎞 Анимированный, в профиле двигается"),
    # --- в магазине сейчас ---
    "char5": ("char", "Девушка", 500, "Фиолетовый неон и острая улыбка"),
    "char6": ("char", "Белые волосы", 2500, "Снежные волосы и голубые глаза"),
    "char7": ("char", "Чёрные волосы", 5000, "Тёмные волосы, расслабленный вид"),
    # ГИФКА: в магазине показывается первый кадр, в профиле у купившего — анимация
    "char8": ("char", "Гифка", 10000, "🎞 Анимированный, в профиле двигается"),
}
# файлы картинок лежат рядом с ботом. Любой размер: бот сам приведёт к 13:8, как требует лента VK
CHAR_FILES = {"char1": "char1.jpg", "char2": "char2.jpg", "char3": "char3.jpg", "char4": "char4.gif",
              "char5": "char5.jpg", "char6": "char6.jpg", "char7": "char7.jpg", "char8": "char8.gif"}
# секретные персонажи: пока не куплен, в списках «???»
SECRET_ITEMS = {"char3"}
# гифки: в профиле уходят как документ (анимация), в ленте магазина показывается первый кадр
GIF_ITEMS = {"char4", "char8"}
# убранные из магазина: не продаются, но у купивших остаются и ходят по аукциону
RETIRED_ITEMS = {"char1", "char2", "char3", "char4"}
# товары, которые продаются, только когда их файл лежит рядом с ботом
FILE_REQUIRED = SECRET_ITEMS | GIF_ITEMS | {"char5", "char6", "char7"}

def item_price(item_id):
    return SHOP_ITEMS[item_id][2] * KK

def owned(user, item_id):
    return item_id in user.get("items", [])

def equipped(user, item_id):
    slot = SHOP_ITEMS[item_id][0]
    cur = user.get("equip", {}).get(slot)
    return cur == item_id

def _art_stamp():
    """Дата файлов персонажей: заменили картинку — рисунки в магазине обновятся сами после перезапуска."""
    times = [int(os.path.getmtime(_find(f))) for f in CHAR_FILES.values() if os.path.exists(_find(f))]
    return max(times) if times else 0

ART_SIG = f"{ART_VERSION}_{_art_stamp()}"   # версия рисунков + дата файлов персонажей (в именах кэша картинок)

# ---------- Магазин аксессуаров и гардероб ----------
CAROUSEL_OK = {"ok": True}   # станет False, если VK не принял карусель в беседе — тогда включится листалка кнопками
_shop_sessions = {}          # (беседа, игрок) → сообщение с последней лентой (чтобы убрать, когда откроется новая)

def char_path(item_id):
    """Файл персонажа в формате 13:8 (лента VK другой формат не принимает).
    Картинка другого размера целиком ставится по центру на размытый фон — один раз, копия лежит в cache.
    Для гифки это превью из первого кадра (сама гифка уходит только в профиль)."""
    raw = _find(CHAR_FILES[item_id])
    if not os.path.exists(raw):
        return raw
    try:
        from PIL import Image, ImageFilter, ImageOps
        im = ImageOps.exif_transpose(Image.open(raw)).convert("RGB")   # у гифки — первый кадр
        w, h = im.size
        if item_id not in GIF_ITEMS and abs(w / h - 13 / 8) < 0.01:
            return raw
        out = os.path.join(ROULETTE_CACHE_DIR, f"fit_{item_id}_{int(os.path.getmtime(raw))}.jpg")
        if not os.path.exists(out):
            os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
            W, H = 1040, 640
            canvas = im.resize((W, H)).filter(ImageFilter.GaussianBlur(28))
            k = min(W / w, H / h)
            fg = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
            canvas.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
            canvas.save(out, quality=92)
        return out
    except Exception as e:
        print(f"Не удалось подогнать {raw} под 13:8 (pip install pillow): {err_text(e)}")
        return raw

def is_secret_hidden(user, item_id):
    """Секретный персонаж, которого у игрока ещё нет: его название и картинка скрыты."""
    return item_id in SECRET_ITEMS and not owned(user, item_id)

def item_view(user, item_id):
    """(название, описание) для показа игроку: пока секретный не куплен — «???»."""
    _, name, _, desc = SHOP_ITEMS[item_id]
    if is_secret_hidden(user, item_id):
        return "???", "Секретный персонаж. Что внутри — узнаете после покупки"
    return name, desc

def char_ready(item_id):
    """Секретного персонажа и гифку можно продавать, только если их файл на месте."""
    return item_id not in FILE_REQUIRED or os.path.exists(_find(CHAR_FILES[item_id]))

def secret_image_path():
    """Картинка-загадка «?» для карточки секретного персонажа. Рисуется один раз, лежит в cache."""
    path = os.path.join(ROULETTE_CACHE_DIR, "secret_q.jpg")
    if os.path.exists(path):
        return path
    try:
        from PIL import Image, ImageDraw, ImageFilter
        os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
        W, H = 1040, 640
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        for y in range(H):                                   # тёмный фиолетовый фон
            t = y / H
            d.line([(0, y), (W, y)], fill=(int(30 + 26 * t), int(14 + 12 * t), int(56 + 44 * t)))
        rnd = random.Random(13)
        for _ in range(70):                                  # звёздочки
            x, y, r = rnd.randint(0, W), rnd.randint(0, H), rnd.choice((1, 2, 2, 3))
            d.ellipse((x - r, y - r, x + r, y + r), fill=(190, 170, 255))
        glow = Image.new("RGB", (W, H), (0, 0, 0))           # мягкое свечение за знаком вопроса
        g = ImageDraw.Draw(glow)
        cx = W // 2
        g.ellipse((cx - 230, 70, cx + 230, 570), fill=(70, 40, 140))
        glow = glow.filter(ImageFilter.GaussianBlur(70))
        img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.8)
        d = ImageDraw.Draw(img)
        col, wd = (238, 228, 255), 44
        r = wd // 2
        cy, R = 210, 98                                                     # центр дуги и радиус по центру линии
        ex, ey = cx + int(R * math.cos(math.radians(45))), cy + int(R * math.sin(math.radians(45)))
        d.arc((cx - R - r, cy - R - r, cx + R + r, cy + R + r), 180, 45, fill=col, width=wd)   # крючок
        d.line([(ex, ey), (cx, 345), (cx, 405)], fill=col, width=wd, joint="curve")             # изгиб и ножка
        for px, py in ((cx - R, cy), (ex, ey), (cx, 345), (cx, 405)):                          # скруглённые концы и стыки
            d.ellipse((px - r, py - r, px + r, py + r), fill=col)
        d.ellipse((cx - 30, 456, cx + 30, 516), fill=col)                                      # точка
        img.save(path, quality=90)
        return path
    except Exception as e:
        print(f"Не удалось нарисовать картинку-загадку (pip install pillow): {err_text(e)}")
        return None

def item_preview(peer_id, item_id, hidden=False):
    """Картинка карточки в магазине: сам персонаж (у секретного, пока не куплен, — «?»). Загружается в VK один раз."""
    if hidden:
        path = secret_image_path()
        return cached_photo(peer_id, path, f"item_secret_v{ART_VERSION}") if path else None
    path = char_path(item_id)
    if not os.path.exists(path):
        print(f"Нет файла персонажа: {path}")
        return None
    return cached_photo(peer_id, path, f"item_{item_id}_v{ART_SIG}")

def ensure_art_version():
    """Рисунок одежды обновился — забываем старые картинки: и файлы кэша, и загрузки в VK."""
    if economy["media"].get("_art") == str(ART_SIG):
        return
    for k in [k for k in economy["media"] if k.startswith(("item_", "avatar_"))]:
        del economy["media"][k]
    economy["media"]["_art"] = str(ART_SIG)
    save_economy()
    if os.path.isdir(ROULETTE_CACHE_DIR):
        for f in os.listdir(ROULETTE_CACHE_DIR):
            if f.startswith(("item_", "avatar_")) and f"_v{ART_SIG}." not in f:
                try:
                    os.remove(os.path.join(ROULETTE_CACHE_DIR, f))
                except OSError:
                    pass

REFUND_REMOVED = True   # True — за убранные из магазина вещи вернуть деньги; False — не возвращать (вещи просто снимаются)
REMOVED_ITEMS = {"cap1": 100, "cap2": 250, "cap3": 200, "cap4": 200,
                 "tee1": 200, "tee2": 500, "tee3": 500, "tee4": 300,
                 "pants1": 500, "pants2": 300, "pants3": 200, "pants4": 100,
                 "field_jupiter": 400, "house1": 600,
                 "tee5": 400, "shoes1": 500, "shoes2": 500, "shoes3": 100, "shoes4": 250}   # id: цена в кк

def cleanup_removed_items():
    """Один раз при запуске: убранные из магазина вещи (кепки, штаны, футболки, обувь, поля, дом)
    снимаются с игроков, а деньги за купленное возвращаются (если REFUND_REMOVED = True)."""
    if economy["media"].get("_removed_refund2") == "1":
        return
    for rec in economy["users"].values():
        items = rec.get("items", [])
        if REFUND_REMOVED:
            for pid, price in REMOVED_ITEMS.items():
                while pid in items:
                    items.remove(pid)
                    rec["money"] = rec.get("money", 0) + price * KK
        eq = rec.get("equip", {})
        for slot in [s for s in eq if s not in SHOP_SLOTS or eq[s] in REMOVED_ITEMS]:
            eq.pop(slot, None)
    economy["media"]["_removed_refund2"] = "1"
    save_economy()

def reset_staff_looks():
    """Один раз: у всех модераторов (роли 1–4, кроме владельца) сбрасывается надетое —
    вид как у обычных игроков, дальше сами покупают и надевают. Купленное остаётся."""
    if economy["media"].get("_staff_reset") == "1":
        return
    staff = {int(uid) for chat in data.values() for uid, lvl in chat.items() if lvl in (1, 2, 3, 4)}
    staff.discard(OWNER_ID)
    for uid in staff:
        rec = economy["users"].get(str(uid))
        if rec and rec.get("equip"):
            rec["equip"] = {}
    economy["media"]["_staff_reset"] = "1"
    save_economy()

def cached_doc(peer_id, path, name, title):
    """Загружает гифку в VK один раз (как документ, чтобы она двигалась) и запоминает attachment."""
    key = f"{name}_{int(os.path.getmtime(path))}"
    cached = economy["media"].get(key)
    if cached:
        return cached
    try:
        res = vk_upload.document_message(path, title=title, peer_id=peer_id)
        doc = res.get("doc", res)
        att = f"doc{doc['owner_id']}_{doc['id']}"
        for old in [k for k in economy["media"] if k.startswith(name + "_")]:
            del economy["media"][old]
        economy["media"][key] = att
        save_economy()
        return att
    except Exception as e:
        print(f"Не удалось загрузить гифку «{name}» (у токена должно быть право «Документы»): {err_text(e)}")
        return None

def avatar_attachment(peer_id, uid):
    """Картинка профиля: купленный персонаж (гифка — анимацией). Нет персонажа — профиль без картинки."""
    cur = get_user(uid).get("equip", {}).get("char")
    if cur in GIF_ITEMS and cur in CHAR_FILES and os.path.exists(_find(CHAR_FILES[cur])):
        return cached_doc(peer_id, _find(CHAR_FILES[cur]), f"avatar_{cur}_v{ART_SIG}", "Персонаж")
    if cur in CHAR_FILES and os.path.exists(char_path(cur)):
        return cached_photo(peer_id, char_path(cur), f"avatar_{cur}_v{ART_SIG}")
    return None

def shop_buy(peer_id, uid, item_id):
    slot, name, _, _ = SHOP_ITEMS[item_id]
    user = get_user(uid)
    if owned(user, item_id):
        return f"Уже куплено: {name}"
    if item_id in RETIRED_ITEMS:
        return "Этого персонажа больше нет в магазине — ищите в «аукцион»."
    if not char_ready(item_id):
        return "Пока недоступно."
    if in_auction(uid, "char", item_id):
        return "Этот персонаж у вас на аукционе — снимите лот."
    price = item_price(item_id)
    if user["money"] < price:
        return f"Не хватает {fmt_num(price - user['money'])} 💰"
    user["money"] -= price
    user.setdefault("items", []).append(item_id)
    user.setdefault("equip", {})[slot] = item_id  # купленное сразу надевается
    save_economy()
    log_action(peer_id, uid, f"купил «{'секретного персонажа' if item_id in SECRET_ITEMS else name}» за {price}")
    if item_id in SECRET_ITEMS:
        return f"🎉 Секрет открыт! Куплено и надето: {name}"[:90]
    return f"✅ Куплено и надето: {name}"[:90]

def shop_wear(uid, item_id):
    slot, name, _, _ = SHOP_ITEMS[item_id]
    user = get_user(uid)
    if not owned(user, item_id):
        return "Сначала купите эту вещь."
    eq = user.setdefault("equip", {})
    if equipped(user, item_id):
        eq.pop(slot, None)
        note = f"Снято: {name}"
    else:
        eq[slot] = item_id
        note = f"Надето: {name}"
    save_economy()
    return note[:90]

def shop_items(uid, slot, mode):
    user = get_user(uid)
    if mode == "mine":
        return [i for i, v in SHOP_ITEMS.items() if v[0] == slot and owned(user, i)]
    return [i for i, v in SHOP_ITEMS.items()
            if v[0] == slot and i not in RETIRED_ITEMS and (owned(user, i) or char_ready(i))]

def shop_button(uid, item_id, slot, mode, kind, idx=0):
    """(подпись, payload) кнопки под товаром."""
    user = get_user(uid)
    own, on = owned(user, item_id), equipped(user, item_id)
    if mode == "shop" and not own:
        label, act = f"Купить {fmt_num(item_price(item_id))}", "buy"
    elif mode == "shop" and on:
        label, act = "✔ Надето", "wear"
    elif on:
        label, act = "Снять", "wear"
    else:
        label, act = "Надеть", "wear"
    payload = {"cmd": "shop", "a": act, "i": item_id, "m": mode, "c": slot, "o": uid, "k": kind, "x": idx}
    return label, payload

def shop_elements(peer_id, uid, slot, mode):
    user = get_user(uid)
    elements = []
    for item_id in shop_items(uid, slot, mode):
        name, desc = item_view(user, item_id)
        own = owned(user, item_id)
        tail = "✅ Куплено" if own else f"{fmt_num(item_price(item_id))} 💰"
        label, payload = shop_button(uid, item_id, slot, mode, "c")
        el = {
            "title": (f"{name} · ID {item_num(item_id)}" if mode == "mine" else name)[:80],
            "description": f"{desc}. {tail}"[:80],
            "buttons": [{"action": {"type": "callback", "label": label[:36],
                                    "payload": json.dumps(payload, ensure_ascii=False)}}],
        }
        att = item_preview(peer_id, item_id, hidden=is_secret_hidden(user, item_id))
        if att:
            el["photo_id"] = att[len("photo"):]
            el["action"] = {"type": "open_photo"}
        elements.append(el)
    return elements

def carousel_json(elements):
    return json.dumps({"type": "carousel", "elements": elements}, ensure_ascii=False)

def shop_menu_page(uid, mode):
    user = get_user(uid)
    if mode == "shop":
        head = "🛍️ Магазин персонажей"
        sub = "Выберите раздел — откроется лента товаров. Листайте её пальцем вправо ➡"
    else:
        head = "🎒 Мои персонажи"
        sub = ("Выберите раздел и нажмите «Надеть» или «Снять» на нужной вещи.\n"
               "Продать другому игроку: «продать перс ID СУММА» (ID — на карточке). Все лоты — «аукцион».")
    kb = VkKeyboard(inline=True)
    for i, slot in enumerate(SHOP_SLOTS):
        if i and i % 2 == 0:
            kb.add_line()
        kb.add_callback_button(SHOP_TITLES[slot], VkKeyboardColor.PRIMARY,
                               {"cmd": "shop", "a": "cat", "c": slot, "m": mode, "o": uid})
    kb.add_line()
    other = "mine" if mode == "shop" else "shop"
    kb.add_callback_button("🎒 Мои персонажи" if mode == "shop" else "🛍️ Магазин", VkKeyboardColor.POSITIVE,
                           {"cmd": "shop", "a": "mode", "m": other, "o": uid})
    return f"{head}\n💰 Баланс: {fmt_num(user['money'])}\n\n{sub}", kb.get_keyboard()

def shop_card(peer_id, uid, slot, mode, idx):
    """Запасной вариант без карусели: одна карточка с листалкой кнопками."""
    ids = shop_items(uid, slot, mode)
    idx %= len(ids)
    item_id = ids[idx]
    user = get_user(uid)
    name, desc = item_view(user, item_id)
    state = "✅ Куплено" if owned(user, item_id) else f"Цена: {fmt_num(item_price(item_id))} 💰"
    if mode == "mine":
        name = f"{name} (ID {item_num(item_id)})"
    text = (f"{SHOP_TITLES[slot]} ({idx + 1}/{len(ids)})\n\n{name}\n{desc}\n{state}\n"
            f"💰 Баланс: {fmt_num(user['money'])}")
    kb = VkKeyboard(inline=True)
    base = {"cmd": "shop", "c": slot, "m": mode, "o": uid, "k": "f"}
    kb.add_callback_button("◀ Назад", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx - 1))
    kb.add_callback_button(f"{idx + 1}/{len(ids)}", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx))
    kb.add_callback_button("Вперед ▶", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx + 1))
    kb.add_line()
    label, payload = shop_button(uid, item_id, slot, mode, "f", idx)
    kb.add_callback_button(label, VkKeyboardColor.POSITIVE, payload)
    kb.add_line()
    kb.add_callback_button("✖ Закрыть", VkKeyboardColor.NEGATIVE, dict(base, a="close"))
    return text, kb.get_keyboard(), item_preview(peer_id, item_id, hidden=is_secret_hidden(user, item_id))

def shop_open_category(peer_id, uid, slot, mode):
    old = _shop_sessions.pop((peer_id, uid), None)
    if old:
        delete_message(peer_id, old)
    if not shop_items(uid, slot, mode):
        send(peer_id, f"{SHOP_TITLES[slot]}: у вас пока нет вещей в этом разделе — загляните в «магазин».")
        return
    if CAROUSEL_OK["ok"]:
        try:
            text = f"{SHOP_TITLES[slot]} — листайте вправо ➡\n💰 Баланс: {fmt_num(get_user(uid)['money'])}"
            res = vk.messages.send(peer_ids=peer_id, message=text,
                                   template=carousel_json(shop_elements(peer_id, uid, slot, mode)),
                                   random_id=get_random_id(), disable_mentions=1)
            _shop_sessions[(peer_id, uid)] = res[0].get("conversation_message_id")
            return
        except Exception as e:  # беседа не принимает карусель — переходим на листалку кнопками
            print(f"Карусель не принята ({err_text(e)}) — магазин переключён на листалку кнопками")
            CAROUSEL_OK["ok"] = False
    text, kb, att = shop_card(peer_id, uid, slot, mode, 0)
    cmid = send_get_cmid(peer_id, text, kb, attachment=att)
    _shop_sessions[(peer_id, uid)] = cmid

def shop_refresh(peer_id, uid, cmid, p):
    """Обновляет сообщение, на котором нажали кнопку (подписи «Купить / Надеть / Снять»)."""
    slot, mode = p.get("c"), p.get("m", "shop")
    if p.get("k") == "f":
        text, kb, att = shop_card(peer_id, uid, slot, mode, int(p.get("x", 0)))
        edit_message(peer_id, cmid, text, kb, attachment=att)
        return
    text = f"{SHOP_TITLES[slot]} — листайте вправо ➡\n💰 Баланс: {fmt_num(get_user(uid)['money'])}"
    vk.messages.edit(peer_id=peer_id, conversation_message_id=cmid, message=text,
                     template=carousel_json(shop_elements(peer_id, uid, slot, mode)), disable_mentions=1)

def shop_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это не ваш магазин. Напишите «магазин» сами."
    act, mode, slot = p.get("a"), p.get("m", "shop"), p.get("c")

    if act == "mode":                       # магазин ↔ мои аксессуары
        answer_event(ev)
        text, kb = shop_menu_page(uid, mode)
        edit_message(peer_id, cmid, text, kb)
        return None
    if act == "cat" and slot in SHOP_TITLES:
        answer_event(ev)
        shop_open_category(peer_id, uid, slot, mode)
        return None
    if act == "close":
        answer_event(ev)
        delete_message(peer_id, cmid)
        _shop_sessions.pop((peer_id, uid), None)
        return None
    if act == "pg":
        answer_event(ev)
        shop_refresh(peer_id, uid, cmid, p)
        return None
    if act in ("buy", "wear"):
        item_id = p.get("i")
        if item_id not in SHOP_ITEMS:
            return "Такого товара нет."
        note = shop_buy(peer_id, uid, item_id) if act == "buy" else shop_wear(uid, item_id)
        answer_event(ev, note)              # подсказка игроку, кнопка не «крутится»
        shop_refresh(peer_id, uid, cmid, p)
        return None
    return None

def cmd_shop(msg, rest, slash):
    """Магазин присылается в личные сообщения — в беседе ленты товаров только мешают."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    text, kb = shop_menu_page(uid, "shop")
    if peer_id < CHAT_OFFSET:                  # написали прямо в ЛС боту
        send(peer_id, text, kb)
        return
    try:
        send(uid, text, kb)
    except Exception as e:                     # игрок ещё не открывал диалог с ботом
        print(f"Не удалось отправить магазин игроку {uid} в ЛС: {err_text(e)}")
        send(peer_id, "📬 Не могу написать вам в личные сообщения. Откройте диалог с ботом и отправьте туда "
                      f"любое сообщение: https://vk.me/club{GROUP_ID}\nПотом снова напишите «магазин».")
        return
    send(peer_id, "📬 Магазин отправлен вам в личные сообщения.")

def cmd_wardrobe(msg, rest, slash):
    text, kb = shop_menu_page(msg["from_id"], "mine")
    send(msg["peer_id"], text, kb)

# ---------- Аукцион (продажа персонажей и бизнесов между игроками) ----------
def item_num(item_id):
    """char5 → 5 (ID персонажа, который видит игрок)."""
    digits = re.sub(r"\D", "", item_id)
    return int(digits) if digits else 0

def in_auction(uid, kind, item):
    return any(l["seller"] == uid and l["kind"] == kind and l["item"] == item for l in economy["auction"].values())
