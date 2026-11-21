# -*- coding: utf-8 -*-
"""Питомцы: магазин в личных сообщениях (лента с фото), покупка и кража денег питомцем."""
import json
import os
import time

from vk_api.utils import get_random_id
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    best_pet, CHAT_OFFSET, DONATE_PET_ID, err_text, _find, fmt_pct, GROUP_ID, has_pet, give_pet,
    pet_money_text, pet_price_text, PET_COOLDOWN, PETS, pets_of, ROULETTE_CACHE_DIR, VAMPIRE_IMMUNE, vk,
)
from database import economy, get_user, save_economy, stats
from donate import donate_create
from helpers import edit_message, fmt_duration, fmt_num, get_names, mention, parse_target, send, send_get_cmid
from images import cached_photo
from logs import log_action


PET_STEAL_WORDS = ("украсть", "своровать", "стащить", "кража", "steal")   # «пит украсть @имя»
PET_W, PET_H = 1040, 640    # 13:8 — формат, который принимает лента VK


# ---------- Картинки ----------
def pet_image_path(pet_id):
    """Файл питомца. Готовые картинки (pet1.jpg…) уже в формате 13:8 и используются как есть.
    Если положить картинку другого размера — она обрезается по центру (без размытых полей), копия лежит в cache."""
    raw = _find(PETS[pet_id]["file"])
    if not os.path.exists(raw):
        return None
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(raw)).convert("RGB")
        if abs(im.width / im.height - 13 / 8) < 0.01:
            return raw
        out = os.path.join(ROULETTE_CACHE_DIR, f"pet_fit_{pet_id}_{int(os.path.getmtime(raw))}.jpg")
        if not os.path.exists(out):
            os.makedirs(ROULETTE_CACHE_DIR, exist_ok=True)
            ImageOps.fit(im, (PET_W, PET_H), Image.LANCZOS, centering=(0.5, 0.3)).save(out, quality=92)
        return out
    except Exception as e:
        print(f"Не удалось подогнать {raw} под 13:8 (pip install pillow): {err_text(e)}")
        return raw

def pet_photo(peer_id, pet_id):
    path = pet_image_path(pet_id)
    if not path:
        print(f"Нет файла питомца: {PETS[pet_id]['file']} (положите рядом с ботом)")
        return None
    return cached_photo(peer_id, path, f"pet_{pet_id}")


# ---------- Магазин питомцев ----------
def carousel_json(elements):
    return json.dumps({"type": "carousel", "elements": elements}, ensure_ascii=False)

def pets_text(uid):
    user = get_user(uid)
    mine = [PETS[p]["name"] for p in sorted(pets_of(user), key=lambda p: PETS[p]["level"])]
    lines = ["🐾 Питомцы", f"💰 Баланс: {fmt_num(user['money'])}", "",
             "Ваши питомцы: " + (", ".join(mine) if mine else "пока нет"), "",
             "Питомец крадёт часть денег у игрока: в беседе напишите «пит украсть @имя» (или ответом на сообщение).",
             f"Кд — раз в {PET_COOLDOWN // 3600} ч. Красть можно у игрока без питомца или со слабее питомцем. "
             "У Вампиров красть нельзя."]
    left = user.get("pet_steal_t", 0) + PET_COOLDOWN - time.time()
    if mine and left > 0:
        lines += ["", f"⏳ Следующая кража через {fmt_duration(left)}."]
    return "\n".join(lines)

def pet_button(uid, pet_id, kind):
    """(подпись, payload) кнопки под питомцем."""
    pet, user = PETS[pet_id], get_user(uid)
    if has_pet(user, pet_id):
        label, act = "✅ Куплено", "have"
    elif pet.get("donate"):
        label, act = f"Купить {pet_price_text(pet_id)}", "don"
    else:
        label, act = f"Купить {pet_money_text(pet['price'])}", "buy"
    return label, {"cmd": "pet", "a": act, "i": pet_id, "o": uid, "k": kind}

def pet_state(uid, pet_id):
    return "✅ Куплено" if has_pet(get_user(uid), pet_id) else pet_price_text(pet_id)

def pet_elements(peer_id, uid):
    elements, atts = [], []
    for pet_id, pet in PETS.items():
        label, payload = pet_button(uid, pet_id, "c")
        elements.append({
            "title": f"{pet['name']} · ур. {pet['level']}"[:80],
            "description": f"{pet['kind']}: крадёт {fmt_pct(pet['percent'])}% · кд {PET_COOLDOWN // 3600} ч · {pet_state(uid, pet_id)}"[:80],
            "buttons": [{"action": {"type": "callback", "label": label[:36],
                                    "payload": json.dumps(payload, ensure_ascii=False)}}],
        })
        atts.append(pet_photo(peer_id, pet_id))
    if all(atts):                       # фото ставим только если они есть у всех карточек
        for el, att in zip(elements, atts):
            el["photo_id"] = att[len("photo"):]
            el["action"] = {"type": "open_photo"}
    return elements

def pet_card(peer_id, uid, pet_id):
    """Запасной вариант без ленты: одна карточка питомца. Возвращает (текст, клавиатура, фото)."""
    pet = PETS[pet_id]
    text = (f"🐾 {pet['name']} · ур. {pet['level']}\n{pet['kind']}\n"
            f"Крадёт {fmt_pct(pet['percent'])}% баланса, кд {PET_COOLDOWN // 3600} ч\n{pet_state(uid, pet_id)}")
    label, payload = pet_button(uid, pet_id, "f")
    kb = VkKeyboard(inline=True)
    kb.add_callback_button(label[:40], VkKeyboardColor.POSITIVE, payload)
    return text, kb.get_keyboard(), pet_photo(peer_id, pet_id)

def pets_send(peer_id, uid):
    """Присылает ленту питомцев в peer_id (ЛС игрока). Бросает ошибку, если написать не получилось."""
    try:
        vk.messages.send(peer_ids=peer_id, message=pets_text(uid), template=carousel_json(pet_elements(peer_id, uid)),
                         random_id=get_random_id(), disable_mentions=1)
        return
    except Exception as e:
        if getattr(e, "code", None) in (7, 901, 902):     # ЛС закрыты — карточками тоже не получится
            raise
        print(f"Лента питомцев не принята ({err_text(e)}) — отправляю карточками")
    send(peer_id, pets_text(uid))
    for pet_id in PETS:
        text, kb, att = pet_card(peer_id, uid, pet_id)
        send_get_cmid(peer_id, text, kb, attachment=att)

def pet_refresh(peer_id, uid, cmid, p):
    """Обновляет сообщение, на котором нажали кнопку (подписи «Купить» → «Куплено»)."""
    try:
        if p.get("k") == "f":
            text, kb, att = pet_card(peer_id, uid, p.get("i"))
            edit_message(peer_id, cmid, text, kb, attachment=att)
        else:
            vk.messages.edit(peer_id=peer_id, conversation_message_id=cmid, message=pets_text(uid),
                             template=carousel_json(pet_elements(peer_id, uid)), disable_mentions=1)
    except Exception as e:
        print(f"Не удалось обновить сообщение с питомцами: {err_text(e)}")

def pet_buy(peer_id, uid, pet_id):
    pet = PETS.get(pet_id)
    if not pet:
        return "Такого питомца нет."
    user = get_user(uid)
    if has_pet(user, pet_id):
        return f"Питомец уже у вас: {pet['name']}"
    if pet.get("donate"):
        return "Этого питомца можно получить только через «донат»."
    if user["money"] < pet["price"]:
        return f"Не хватает {fmt_num(pet['price'] - user['money'])} 💰"
    user["money"] -= pet["price"]
    give_pet(user, pet_id)
    save_economy()
    log_action(peer_id, uid, f"купил питомца «{pet['name']}» за {pet['price']}")
    return f"✅ Куплено: {pet['name']}"[:90]

def pet_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это не ваш магазин питомцев. Напишите «питомцы» сами."
    act, pet_id = p.get("a"), p.get("i")
    if pet_id not in PETS:
        return "Кнопка устарела. Напишите «питомцы» заново."
    if act == "have":
        return f"Питомец «{PETS[pet_id]['name']}» уже у вас 🐾"
    if act == "don":                                    # донатный питомец: оформляем заказ, реквизиты придут в ЛС
        if not PETS[pet_id].get("donate"):
            return "Кнопка устарела. Напишите «питомцы» заново."
        return donate_create(uid, "pet", chat_peer=None)[:90]
    if act == "buy":
        note = pet_buy(peer_id, uid, pet_id)
        pet_refresh(peer_id, uid, cmid, p)
        return note
    return "Кнопка устарела. Напишите «питомцы» заново."


# ---------- Кража питомцем ----------
def pet_steal(msg, victim):
    """Питомец крадёт у игрока PETS[..]["percent"]% его баланса. Только по команде, кд PET_COOLDOWN."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    user = get_user(uid)
    pet_id = best_pet(user)
    if not pet_id:
        send(peer_id, "🐾 У вас нет питомца. Магазин питомцев — «питомцы».")
        return
    pet = PETS[pet_id]
    if peer_id < CHAT_OFFSET:
        send(peer_id, "🐾 Питомец ворует только в беседе: напишите «пит украсть @имя» там.")
        return
    if victim is None or victim <= 0:
        send(peer_id, "ℹ️ Использование: пит украсть — ответом на сообщение игрока, или «пит украсть @имя».")
        return
    if victim == uid:
        send(peer_id, "🐾 Свои деньги красть бессмысленно.")
        return
    if victim in VAMPIRE_IMMUNE:
        send(peer_id, "🛡 У этого игрока иммунитет.")
        return
    left = user.get("pet_steal_t", 0) + PET_COOLDOWN - time.time()
    if left > 0:
        send(peer_id, f"🐾 Питомец ещё отдыхает. Следующая кража через {fmt_duration(left)}.")
        return
    target = economy["users"].get(str(victim))
    if not target or str(victim) not in stats.get(str(peer_id), {}):
        send(peer_id, "🐾 Не нашёл такого игрока в этой беседе.")
        return
    if target.get("vampire"):
        send(peer_id, "🧛 У Вампиров красть нельзя.")
        return
    victim_pet_id = best_pet(target)
    if victim_pet_id and PETS[victim_pet_id]["level"] >= pet["level"]:
        victim_pet = PETS[victim_pet_id]
        send(peer_id, f"🛡 У игрока есть питомец «{victim_pet['name']}» — он не слабее вашего «{pet['name']}» и защищает хозяина.\n"
                      "Красть можно у игроков без питомца или со слабее питомцем.")
        return
    percent = pet["percent"]
    amount = int(target.get("money", 0)) * int(round(percent * 10)) // 1000
    if amount <= 0:
        send(peer_id, "🐾 У жертвы нечего брать.")
        return
    target["money"] -= amount
    user["money"] += amount
    user["pet_steal_t"] = time.time()
    save_economy()
    log_action(peer_id, uid, f"питомец «{pet['name']}» украл {amount} у {victim} ({fmt_pct(percent)}%)")
    names = get_names([uid, victim])
    send(peer_id, f"🐾 Питомец «{pet['name']}» игрока {mention(uid, names)} стащил у {mention(victim, names)} "
                  f"{fmt_num(amount)} 💰 ({fmt_pct(percent)}% баланса).\n"
                  f"Следующая кража — через {PET_COOLDOWN // 3600} ч.")

def cmd_pets(msg, rest, slash):
    """«питомцы» / «питомец» / «пит»: магазин и ваши питомцы (присылается в ЛС).
    «пит украсть @имя»: питомец крадёт деньги."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    word, _, tail = rest.strip().partition(" ")
    word = word.lower().replace("ё", "е")
    if word in PET_STEAL_WORDS:
        victim, _ = parse_target(msg, tail)
        pet_steal(msg, victim)
        return
    if word and not slash:          # «пит привет» и т.п. — обычный разговор, не реагируем
        return
    if peer_id < CHAT_OFFSET:       # написали прямо в ЛС боту
        try:
            pets_send(peer_id, uid)
        except Exception as e:
            print(f"Не удалось отправить питомцев игроку {uid}: {err_text(e)}")
        return
    try:
        pets_send(uid, uid)
    except Exception as e:          # игрок ещё не открывал диалог с ботом
        print(f"Не удалось отправить питомцев игроку {uid} в ЛС: {err_text(e)}")
        send(peer_id, "📬 Не могу написать вам в личные сообщения. Откройте диалог с ботом и отправьте туда "
                      f"любое сообщение: https://vk.me/club{GROUP_ID}\nПотом снова напишите «питомцы».")
        return
    send(peer_id, "📬 Питомцы отправлены вам в личные сообщения.")
