# -*- coding: utf-8 -*-
"""Бизнесы игроков: покупка, доход, карточки."""
import json
import os
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id

from config import (
    BIZ_MAX_HOURS, BIZ_PERIOD, BUSINESSES, CHAT_OFFSET, err_text, _find, GROUP_ID, _n,
    ROULETTE_CACHE_DIR, vk,
)
from database import get_user, save_economy
from helpers import answer_event, delete_message, edit_message, fmt_num, send, send_get_cmid
from images import cached_photo
from logs import log_action
from shop import carousel_json, CAROUSEL_OK, in_auction


# ---------- Бизнес ----------
# Купил бизнес — он сам копит доход (сумма «за 12 часов» копится по секундам). Забрать всё разом: команда «доход».
# У игрока: user["biz"] = {ключ бизнеса: время последнего сбора}. Лента с фото — как в магазине (в ЛС).
_biz_sessions = {}      # (чат, игрок) → сообщение с последней лентой (убираем, когда открывается новая)

def kk_text(n):
    """500000000 → «500кк», 2000000000 → «2ккк», 2500000000 → «2,5ккк», 150000000 → «150кк»."""
    if n >= 10 ** 9 and n % 10 ** 8 == 0:
        return f"{n / 10 ** 9:g}".replace(".", ",") + "ккк"
    if n >= 10 ** 6 and n % 10 ** 6 == 0:
        return f"{n // 10 ** 6}кк"
    return _n(n)

def biz_owned(user):
    return user.get("biz") or {}

def biz_accrued(user, key, now):
    """Сколько бизнес накопил с последнего сбора."""
    elapsed = max(0, int(now - biz_owned(user)[key]))
    if BIZ_MAX_HOURS > 0:
        elapsed = min(elapsed, BIZ_MAX_HOURS * 3600)
    return BUSINESSES[key]["income"] * elapsed // BIZ_PERIOD

def biz_image_path(key):
    """Файл бизнеса в формате 13:8 (как у персонажей в магазине): чужой размер ставится по центру на размытый фон."""
    raw = _find(BUSINESSES[key]["file"])
    if not os.path.exists(raw):
        return None
    try:
        from PIL import Image, ImageFilter, ImageOps
        im = ImageOps.exif_transpose(Image.open(raw)).convert("RGB")
        w, h = im.size
        if abs(w / h - 13 / 8) < 0.01:
            return raw
        out = os.path.join(ROULETTE_CACHE_DIR, f"fit_biz_{key}_{int(os.path.getmtime(raw))}.jpg")
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

def biz_preview(peer_id, key):
    path = biz_image_path(key)
    return cached_photo(peer_id, path, f"biz_{key}") if path else None

def biz_button(uid, key, kind, idx=0):
    """(подпись, payload) кнопки под бизнесом."""
    if key in biz_owned(get_user(uid)):
        label, act = "✅ Куплено", "have"
    else:
        label, act = f"Купить {kk_text(BUSINESSES[key]['price'])}", "buy"
    return label, {"cmd": "biz", "a": act, "i": key, "o": uid, "k": kind, "x": idx}

def biz_head(uid):
    return (f"💼 Бизнесы — листайте вправо ➡\n💰 Баланс: {fmt_num(get_user(uid)['money'])}\n"
            "Копившийся доход забирает команда «доход».")

def biz_elements(peer_id, uid):
    user = get_user(uid)
    elements = []
    for key, b in BUSINESSES.items():
        tail = "✅ Куплено" if key in biz_owned(user) else f"Цена {kk_text(b['price'])}"
        label, payload = biz_button(uid, key, "c")
        el = {
            "title": f"{b['emoji']} {b['name']}"[:80],
            "description": f"Доход {kk_text(b['income'])}/12ч · {tail}"[:80],
            "buttons": [{"action": {"type": "callback", "label": label[:36],
                                    "payload": json.dumps(payload, ensure_ascii=False)}}],
        }
        att = biz_preview(peer_id, key)
        if att:
            el["photo_id"] = att[len("photo"):]
            el["action"] = {"type": "open_photo"}
        elements.append(el)
    return elements

def biz_card(peer_id, uid, idx):
    """Запасной вариант без карусели: одна карточка с листалкой кнопками."""
    keys = list(BUSINESSES)
    idx %= len(keys)
    key = keys[idx]
    b = BUSINESSES[key]
    user = get_user(uid)
    state = "✅ Куплено" if key in biz_owned(user) else f"Цена: {fmt_num(b['price'])} 💰 ({kk_text(b['price'])})"
    text = (f"{b['emoji']} {b['name']} ({idx + 1}/{len(keys)})\n\n{b['desc']}\n"
            f"Доход: {fmt_num(b['income'])} 💰 за 12 ч. ({kk_text(b['income'])})\n{state}\n"
            f"💰 Баланс: {fmt_num(user['money'])}")
    kb = VkKeyboard(inline=True)
    base = {"cmd": "biz", "o": uid, "k": "f"}
    kb.add_callback_button("◀ Назад", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx - 1))
    kb.add_callback_button(f"{idx + 1}/{len(keys)}", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx))
    kb.add_callback_button("Вперед ▶", VkKeyboardColor.SECONDARY, dict(base, a="pg", x=idx + 1))
    kb.add_line()
    label, payload = biz_button(uid, key, "f", idx)
    kb.add_callback_button(label, VkKeyboardColor.POSITIVE, payload)
    kb.add_line()
    kb.add_callback_button("✖ Закрыть", VkKeyboardColor.NEGATIVE, dict(base, a="close"))
    return text, kb.get_keyboard(), biz_preview(peer_id, key)

def biz_open(peer_id, uid):
    """Присылает ленту бизнесов (карусель с фото) в peer_id."""
    old = _biz_sessions.pop((peer_id, uid), None)
    if old:
        delete_message(peer_id, old)
    if CAROUSEL_OK["ok"]:
        try:
            res = vk.messages.send(peer_ids=peer_id, message=biz_head(uid),
                                   template=carousel_json(biz_elements(peer_id, uid)),
                                   random_id=get_random_id(), disable_mentions=1)
            _biz_sessions[(peer_id, uid)] = res[0].get("conversation_message_id")
            return
        except Exception as e:
            if getattr(e, "code", None) in (901, 902, 917):      # ЛС закрыты — карусель тут ни при чём
                raise
            print(f"Карусель не принята ({err_text(e)}) — ленты переключены на листалку кнопками")
            CAROUSEL_OK["ok"] = False
    text, kb, att = biz_card(peer_id, uid, 0)
    _biz_sessions[(peer_id, uid)] = send_get_cmid(peer_id, text, kb, attachment=att)

def biz_refresh(peer_id, uid, cmid, p):
    """Обновляет сообщение, на котором нажали кнопку («Купить» → «✅ Куплено»)."""
    if p.get("k") == "f":
        text, kb, att = biz_card(peer_id, uid, int(p.get("x", 0)))
        edit_message(peer_id, cmid, text, kb, attachment=att)
        return
    vk.messages.edit(peer_id=peer_id, conversation_message_id=cmid, message=biz_head(uid),
                     template=carousel_json(biz_elements(peer_id, uid)), disable_mentions=1)

def biz_buy(peer_id, uid, key):
    b = BUSINESSES[key]
    user = get_user(uid)
    if key in biz_owned(user):
        return f"Уже куплено: {b['name']}"
    if in_auction(uid, "biz", key):
        return "Этот бизнес у вас на аукционе — снимите лот."
    if user["money"] < b["price"]:
        return f"Не хватает {fmt_num(b['price'] - user['money'])} 💰"
    user["money"] -= b["price"]
    user.setdefault("biz", {})[key] = time.time()
    save_economy()
    log_action(peer_id, uid, f"купил бизнес «{b['name']}» за {b['price']}")
    return f"✅ Куплено: {b['name']}. Доход — команда «доход»"[:90]

def biz_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это не ваш список. Напишите «бизнес» сами."
    act = p.get("a")
    if act == "close":
        answer_event(ev)
        delete_message(peer_id, cmid)
        _biz_sessions.pop((peer_id, uid), None)
        return None
    if act == "pg":
        answer_event(ev)
        biz_refresh(peer_id, uid, cmid, p)
        return None
    if act == "have":
        return "Уже куплено. Забрать доход — команда «доход»."
    if act == "buy":
        key = p.get("i")
        if key not in BUSINESSES:
            return "Такого бизнеса нет."
        note = biz_buy(peer_id, uid, key)
        answer_event(ev, note)              # подсказка игроку, кнопка не «крутится»
        biz_refresh(peer_id, uid, cmid, p)
        return None
    return None

def cmd_biz(msg, rest, slash):
    """«бизнес»: лента бизнесов с фото. Как и магазин, приходит в личные сообщения."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if peer_id < CHAT_OFFSET:                  # написали прямо в ЛС боту
        biz_open(peer_id, uid)
        return
    try:
        biz_open(uid, uid)
    except Exception as e:                     # игрок ещё не открывал диалог с ботом
        print(f"Не удалось отправить бизнесы игроку {uid} в ЛС: {err_text(e)}")
        send(peer_id, "📬 Не могу написать вам в личные сообщения. Откройте диалог с ботом и отправьте туда "
                      f"любое сообщение: https://vk.me/club{GROUP_ID}\nПотом снова напишите «бизнес».")
        return
    send(peer_id, "📬 Бизнесы отправлены вам в личные сообщения.")

def cmd_income(msg, rest, slash):
    """«доход»: забрать деньги, накопленные всеми бизнесами."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    user = get_user(uid)
    owned_now = [k for k in BUSINESSES if k in biz_owned(user)]
    if not owned_now:
        send(peer_id, "💼 У вас пока нет бизнеса. Посмотреть и купить: «бизнес»")
        return
    now = time.time()
    got = {k: biz_accrued(user, k, now) for k in owned_now}
    total = sum(got.values())
    if total < 1:
        send(peer_id, "💼 Доход ещё не накопился. Ваши бизнесы приносят "
                      f"{kk_text(sum(BUSINESSES[k]['income'] for k in owned_now))} 💰 за 12 ч.")
        return
    user["money"] += total
    for k in owned_now:
        user["biz"][k] = now
    save_economy()
    log_action(peer_id, uid, f"забрал доход с бизнеса: {total}")
    lines = [f"💵 Доход собран: +{fmt_num(total)} 💰", ""]
    lines += [f"{BUSINESSES[k]['emoji']} {BUSINESSES[k]['name']}: +{fmt_num(v)}" for k, v in got.items()]
    lines += ["", f"💰 Баланс: {fmt_num(user['money'])}"]
    send(peer_id, "\n".join(lines))
