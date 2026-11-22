# -*- coding: utf-8 -*-
"""Донат: оплата через Сбер, проверка владельцем."""
import os
import re
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    CHAT_OFFSET, DONATE_BOT_LINK, DONATE_CARD, DONATE_CARD_BANK, DONATE_CREATE_COOLDOWN,
    DONATE_ITEMS, DONATE_MAX_RECEIPTS, DONATE_MAX_WAIT, DONATE_OPEN_TTL, DONATE_PREFIX_BANNED,
    DONATE_PET_ID, DONATE_PREFIX_MAX, DONATE_QR_FILE, err_text, fmt_pct, give_pet, HEAL_DAYS,
    has_pet, heal_left, OWNER_ID, PACK_KEYS, PACK_WORDS, PACKS, PERK_TITLES, PET_COOLDOWN, PETS,
    VAMPIRE_COOLDOWN, VAMPIRE_PERCENT, VAMPIRE_TITLE, VAMPIRE_TOP_PERCENT, VIP_DAYS, VIP_PREFIX, vk_upload,
)
from database import economy, get_user, save_economy, vip_active
from helpers import (
    active_dialog_of, edit_message, fmt_duration, fmt_num, fmt_time, get_names, mention,
    msg_photos, send, send_dm,
)
from logs import log_action
from player import add_exp, sanitize_prefix
from shop import SHOP_ITEMS


# ---------- Донат: оплата через Сбер, проверка владельцем ----------
# Схема: «донат» в беседе показывает привилегии → «Купить» → реквизиты приходят игроку в ЛС →
# игрок выбирает способ (QR или перевод на карту), платит и жмёт «Я оплатил» → владельцу в ЛС приходит
# карточка заказа (кто, что, сколько, какой номер, кто ещё ждёт) с кнопками «Подтвердить / Отказать» →
# после подтверждения награда выдаётся автоматически, строго один раз.
def donate_blocked(uid):
    return str(uid) in economy["donate_blocked"]

def find_order(oid):
    return economy["donate_orders"].get(str(oid))

def donate_title(order):
    return DONATE_ITEMS[order["item"]]["title"]

def donate_name(uid):
    return get_names([uid]).get(uid, f"id{uid}")

def dm_is_free(uid):
    """Игрок в ЛС не занят репортом (чтобы донат не мешал разговору с следящим)."""
    mode = economy["report_mode"].get(str(uid))
    if mode and mode.get("until", 0) > time.time():      # игрок пишет репорт — донат ему не мешает
        return False
    return (not active_dialog_of(uid)
            and not any(r.get("status") == "open" and r.get("staff") == uid for r in economy["reports"].values())
            and not (uid == OWNER_ID and economy.get("report_wait")))

def donate_qr_attachment():
    """Картинка вашего QR в VK (загружается один раз и запоминается). None — файла нет."""
    path = DONATE_QR_FILE
    if not os.path.exists(path):
        return None
    key = f"donate_qr_{int(os.path.getmtime(path))}"
    att = economy["media"].get(key)
    if att:
        return att
    photo = vk_upload.photo_messages(path)[0]
    att = f"photo{photo['owner_id']}_{photo['id']}"
    economy["media"][key] = att
    save_economy()
    return att

def donate_strip(order, note=""):
    """Убирает кнопки у последнего сообщения заказа в ЛС игрока."""
    if order.get("cmid"):
        try:
            edit_message(order["uid"], order["cmid"], (order.get("dm_text") or f"Заказ №{order['id']}") + (f"\n\n{note}" if note else ""))
        except Exception as e:
            print(f"Не удалось убрать кнопки у заказа №{order['id']}: {err_text(e)}")
        order["cmid"] = None

def donate_card(order, text, kb, attachment=None):
    """Новое сообщение заказа в ЛС игрока; у предыдущего кнопки убираются. Бросает ошибку, если ЛС закрыто."""
    old = (order.get("cmid"), order.get("dm_text"))
    cmid = send_dm(order["uid"], text, kb, attachment)
    if old[0]:
        try:
            edit_message(order["uid"], old[0], old[1] or f"Заказ №{order['id']}")
        except Exception as e:
            print(f"Не удалось убрать кнопки у прошлого сообщения заказа: {err_text(e)}")
    order["cmid"], order["dm_text"] = cmid, text
    save_economy()

DONATE_KEYS = ("vamp", "heal", "virt", "pref", "pet") + PACK_KEYS      # порядок привилегий в «донат»

def strike(text):
    """Зачёркнутый текст. VK не понимает разметку, поэтому после каждого символа ставится «перечёркивание»."""
    return "".join(ch + "\u0336" for ch in str(text))

def donate_price_text(item):
    """«49 ₽» или со скидкой: «4̶9̶9̶ ₽ → 299 ₽ 🔥 скидка»."""
    if item.get("old_price"):
        return f"{strike(item['old_price'])} ₽ → {item['price']} ₽ 🔥 скидка"
    return f"{item['price']} ₽"

def donate_details(key):
    """Характеристика привилегии: что это и для чего."""
    if key == "vamp":
        return [
            "Что это: должность с особой командой «укусить».",
            "Для чего: забирать деньги у других игроков.",
            "",
            "Как работает:",
            "• «укусить» ответом на сообщение игрока или «укусить @имя»",
            "• кусает только по команде: простое @упоминание не считается",
            f"• обычного игрока кусает на {fmt_pct(VAMPIRE_PERCENT)}% его баланса",
            f"• игрока на 1 месте в топе по балансу — только на {fmt_pct(VAMPIRE_TOP_PERCENT)}%",
            f"• кд: раз в {VAMPIRE_COOLDOWN // 3600} ч.",
            "• нельзя кусать других Вампиров",
            "• не сработает на игрока с зельем лечения",
            "• покупается один раз, без срока действия",
        ]
    if key in PACKS:
        return ["Что внутри:"] + ["• " + l for l in pack_lines(key)] + ["", "• всё выдаётся сразу после подтверждения оплаты",
                                                                      "• можно купить повторно"]
    if key == "heal":
        return [
            "Что это: зелье, которое лечит от укусов Вампиров.",
            "Для чего: защитить свои деньги — пока зелье действует, Вампир не сможет вас укусить.",
            "",
            f"• действует {DONATE_ITEMS['heal']['days']} дней с момента покупки",
            "• после окончания можно купить снова",
            "• Вампирам не нужно: другие Вампиры их и так не кусают",
        ]
    if key == "virt":
        return [
            "Что это: игровая валюта 💰, зачисляется на ваш баланс.",
            "Для чего: ставки в играх (мины, рулетка, дуэль), покупки в магазине, бизнесы.",
            "",
            f"• +{fmt_num(DONATE_ITEMS['virt']['money'])} 💰 за одну покупку",
            "• можно покупать сколько угодно раз",
        ]
    if key == "pet":
        pet = PETS[DONATE_PET_ID]
        return [
            f"Что это: питомец «{pet['name']}» — самый сильный из питомцев (уровень {pet['level']}).",
            "Для чего: красть деньги у других игроков.",
            "",
            "Как работает:",
            "• «пит украсть» ответом на сообщение игрока или «пит украсть @имя»",
            f"• забирает {fmt_pct(pet['percent'])}% баланса игрока",
            f"• кд: раз в {PET_COOLDOWN // 3600} ч.",
            "• красть можно у игрока без такого же питомца и без питомца сильнее",
            "• питомец может красть и у Вампиров",
            "• покупается один раз, без срока действия",
            "• посмотреть всех питомцев с фото: «питомцы»",
        ]
    return [
        "Что это: свой префикс — любой текст рядом с вашим ником.",
        "Для чего: выделиться в беседе.",
        "",
        f"• до {DONATE_PREFIX_MAX} символов",
        "• нельзя писать слова, похожие на должности персонала (владелец, админ, модератор, VIP и т.п.)",
        "• заказать: «донат префикс ТЕКСТ» или кнопка «Купить»",
    ]

def build_donate_page(peer_id, page, opener_id):
    """Страница 0 — все привилегии списком, страницы 1–3 — по одной привилегии: характеристика и кнопка покупки."""
    user = get_user(opener_id)
    if page == 0:
        lines = ["💎 Донат — привилегии", ""]
        for key in DONATE_KEYS:
            item = DONATE_ITEMS[key]
            lines.append(f"{item['title']} — {donate_price_text(item)}")
        lines += ["", "Нажмите на привилегию, чтобы узнать, что это и для чего. Листать можно кнопками ◀ ▶.",
                  "",
                  "Как купить: на странице привилегии нажмите «Купить» — реквизиты придут вам в личные сообщения. "
                  "Оплата через Сбер: по QR-коду или переводом на карту. Награда выдаётся после проверки оплаты.",
                  "Для ЛС бот должен уметь вам писать: если не приходит — напишите ему первым в личку."]
        kb = VkKeyboard(inline=True)
        for i, key in enumerate(DONATE_KEYS, 1):
            if i > 1 and (i - 1) % 2 == 0:
                kb.add_line()
            kb.add_callback_button(DONATE_ITEMS[key]["title"][:40], VkKeyboardColor.PRIMARY,
                                   {"cmd": "dpg", "p": i, "o": opener_id})
        return "\n".join(lines), kb.get_keyboard()

    key = DONATE_KEYS[page - 1]
    item = DONATE_ITEMS[key]
    lines = [f"💎 Донат — {page}/{len(DONATE_KEYS)}", "", item["title"], f"Цена: {donate_price_text(item)}", ""]
    lines += donate_details(key)
    prev_page = page - 1 if page > 1 else len(DONATE_KEYS)
    next_page = page + 1 if page < len(DONATE_KEYS) else 1
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("◀ Назад", VkKeyboardColor.SECONDARY, {"cmd": "dpg", "p": prev_page, "o": opener_id})
    kb.add_callback_button("☰ Меню", VkKeyboardColor.PRIMARY, {"cmd": "dpg", "p": 0, "o": opener_id})
    kb.add_callback_button("Вперед ▶", VkKeyboardColor.SECONDARY, {"cmd": "dpg", "p": next_page, "o": opener_id})
    kb.add_line()
    if key == "vamp" and user.get("vampire"):
        kb.add_callback_button("🧛 Вампир — уже у вас", VkKeyboardColor.SECONDARY, {"cmd": "don", "act": "have", "k": "vamp", "o": opener_id})
    elif key == "pet" and has_pet(user, DONATE_PET_ID):
        kb.add_callback_button("🐶 Питомец — уже у вас", VkKeyboardColor.SECONDARY, {"cmd": "don", "act": "have", "k": "pet", "o": opener_id})
    else:
        kb.add_callback_button(f"🛒 Купить · {item['price']} ₽", VkKeyboardColor.POSITIVE,
                               {"cmd": "don", "act": "buy", "k": key, "o": opener_id})
    return "\n".join(lines), kb.get_keyboard()

def donate_menu(uid):
    return build_donate_page(0, 0, uid)

def donate_dm_closed(peer_id, uid):
    """ЛС игроку не доставилось: объясняем в беседе, что сделать."""
    text = (f"⚠ Не могу написать вам в личные сообщения. Откройте диалог с ботом: {DONATE_BOT_LINK} — "
            "напишите ему любое сообщение и повторите покупку.")
    if peer_id >= CHAT_OFFSET:
        donate_notify(peer_id, text)
    return "Не могу написать вам в ЛС — откройте диалог с ботом (ссылка в беседе)."

def donate_notify(peer_id, text):
    try:
        send(peer_id, text)
    except Exception as e:
        print(f"Не удалось отправить сообщение про донат: {err_text(e)}")

def donate_create(uid, item_key, data="", chat_peer=None):
    """Создаёт заказ и присылает игроку в ЛС выбор способа оплаты. Возвращает короткий ответ для игрока."""
    item = DONATE_ITEMS[item_key]
    where = chat_peer or uid
    if donate_blocked(uid):
        return "🚫 Вам закрыт доступ к донату за попытку обмана."
    user = get_user(uid)
    if item_key == "vamp" and user.get("vampire"):
        return f"🧛 Вы уже {VAMPIRE_TITLE}."
    if item_key == "pet" and has_pet(user, DONATE_PET_ID):
        return f"🐶 Питомец «{PETS[DONATE_PET_ID]['name']}» у вас уже есть."
    if item_key == "heal":
        if user.get("vampire"):
            return f"🧛 {VAMPIRE_TITLE}ов другие вампиры не кусают — зелье вам не нужно."
        if heal_left(user) > 0:
            return f"🧪 Зелье уже действует, осталось {fmt_duration(heal_left(user))}. Купить новое можно после окончания."
    now = time.time()
    wait = user.get("last_order", 0) + DONATE_CREATE_COOLDOWN - now
    if wait > 0:
        return f"⏳ Подождите {int(wait) + 1} сек."
    waiting = [o for o in economy["donate_orders"].values() if o.get("uid") == uid and o.get("status") == "wait"]
    if len(waiting) >= DONATE_MAX_WAIT:
        return "⏳ Ваши оплаты уже проверяются. Дождитесь решения владельца."
    old_new = [o for o in economy["donate_orders"].values() if o.get("uid") == uid and o.get("status") == "new"]

    economy["seq"]["donate"] += 1
    order = {"id": economy["seq"]["donate"], "uid": uid, "item": item_key, "price": item["price"],
             "status": "new", "t": now, "peer": chat_peer, "data": data}
    lines = [f"🧾 Заказ №{order['id']}", item["title"] + (f"\nПрефикс: {data}" if item_key == "pref" else ""),
             f"К оплате: {item['price']} ₽", "", "Выберите способ оплаты:"]
    kb = VkKeyboard(inline=True)
    if os.path.exists(DONATE_QR_FILE):
        kb.add_callback_button("📷 Оплата по QR-коду", VkKeyboardColor.PRIMARY, {"cmd": "don", "act": "qr", "id": order["id"]})
        kb.add_line()
    kb.add_callback_button(f"💳 Перевод на карту ({DONATE_CARD_BANK})", VkKeyboardColor.PRIMARY, {"cmd": "don", "act": "card", "id": order["id"]})
    kb.add_line()
    kb.add_callback_button("❌ Отмена", VkKeyboardColor.NEGATIVE, {"cmd": "don", "act": "cx", "id": order["id"]})
    economy["donate_orders"][str(order["id"])] = order
    try:
        donate_card(order, "\n".join(lines), kb.get_keyboard())
    except Exception as e:
        print(f"Не удалось написать игроку {uid} в ЛС: {err_text(e)}")
        economy["donate_orders"].pop(str(order["id"]), None)
        economy["seq"]["donate"] -= 1
        return donate_dm_closed(where, uid)
    for o in old_new:          # актуален только последний неоплаченный заказ
        o["status"] = "cancelled"
        donate_strip(o, "↪ Заменён новым заказом.")
    user["last_order"] = now
    save_economy()
    log_action(where, uid, f"донат: заказ №{order['id']} {item_key} {item['price']}₽")
    return "📩 Реквизиты отправил вам в личные сообщения."

def donate_steps(order, method):
    """Шаги оплаты выбранным способом."""
    n, price, uid = order["id"], order["price"], order["uid"]
    nick = donate_name(uid)
    comment = f"№{n} и ваш ник ({nick})"
    if method == "qr":
        steps = [f"📷 Оплата по QR-коду · заказ №{n}", "",
                 "1. Откройте приложение Сбербанка и отсканируйте QR-код на картинке выше. "
                 "С телефона: сохраните картинку и выберите её из галереи в сканере.",
                 f"2. Проверьте получателя и введите сумму ровно {price} ₽.",
                 f"3. В комментарии к платежу напишите: {comment}.",
                 "4. Оплатите и нажмите «✅ Я оплатил(а)».", ]
    else:
        steps = [f"💳 Перевод на карту · заказ №{n}", "",
                 f"1. Откройте приложение банка → Переводы → По номеру карты.",
                 f"2. Номер карты ({DONATE_CARD_BANK}): {DONATE_CARD}",
                 f"3. Сумма: ровно {price} ₽.",
                 f"4. В описании (сообщении получателю) напишите: {comment}.",
                 "5. Оплатите и нажмите «✅ Я оплатил(а)».", ]
    steps += ["", "⚠ Нажимайте «Я оплатил(а)» только после оплаты. За попытку обмана вы получите блокировку."]
    return "\n".join(steps)

def donate_owner_text(order):
    uid = order["uid"]
    others = [o for o in economy["donate_orders"].values() if o.get("status") == "wait" and o["id"] != order["id"]]
    names = get_names([uid] + [o["uid"] for o in others[:5]])
    lines = [f"💰 Оплата на проверку — заказ №{order['id']}",
             f"👤 {names.get(uid, 'id' + str(uid))} — vk.com/id{uid}",
             f"🛒 {donate_title(order)} — {order['price']} ₽"]
    if order["item"] == "pref":
        lines.append(f"🏷 Префикс: {order.get('data')}")
    lines += [f"💳 Способ: {'QR-код' if order.get('method') == 'qr' else 'перевод на карту'}",
              f"🕒 Заказ создан {fmt_time(order['t'])}, «оплатил» нажато {fmt_time(order.get('mark_t', time.time()))}",
              f"🔎 В банке ищите: {order['price']} ₽, в комментарии «№{order['id']}» и ник"]
    if others:
        lines += ["", "⚠ Одновременно ждут проверки (сверяйте по номеру в комментарии):"]
        lines += [f"• №{o['id']} — {names.get(o['uid'], 'id' + str(o['uid']))} — {o['price']} ₽ ({DONATE_ITEMS[o['item']]['title']})"
                  for o in others[:5]]
    return "\n".join(lines)

def donate_owner_keyboard(oid):
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Подтвердить", VkKeyboardColor.POSITIVE, {"cmd": "don", "act": "ok", "id": oid})
    kb.add_callback_button("❌ Отказать", VkKeyboardColor.NEGATIVE, {"cmd": "don", "act": "no", "id": oid})
    kb.add_line()
    kb.add_callback_button("🚫 Отказать и заблокировать", VkKeyboardColor.NEGATIVE, {"cmd": "don", "act": "ban", "id": oid})
    return kb.get_keyboard()

def donate_owner_update(order, line):
    if order.get("owner_cmid"):
        try:
            edit_message(OWNER_ID, order["owner_cmid"], f"{order.get('owner_text', '')}\n\n{line}")
        except Exception as e:
            print(f"Не удалось обновить карточку заказа №{order['id']}: {err_text(e)}")
        order["owner_cmid"] = None

def donate_mark_paid(order):
    """Игрок нажал «Я оплатил»: карточка владельцу в ЛС. Возвращает текст ошибки или None."""
    order["status"], order["mark_t"] = "wait", time.time()
    text = donate_owner_text(order)
    try:
        cmid = send_dm(OWNER_ID, text, donate_owner_keyboard(order["id"]))
    except Exception as e:
        print(f"Не удалось отправить карточку заказа владельцу: {err_text(e)}")
        order["status"] = "new"
        return "Не удалось отправить оплату на проверку. Попробуйте ещё раз чуть позже."
    order["owner_cmid"], order["owner_text"] = cmid, text
    donate_strip(order, "⏳ Оплата отправлена на проверку.")
    save_economy()
    try:
        donate_card(order, f"⏳ Ожидайте принятия!\n\nЗаказ №{order['id']} ({donate_title(order)}, {order['price']} ₽) отправлен владельцу на проверку. "
                           "Награда придёт автоматически, как только оплату подтвердят.\n\n"
                           "🧾 Чтобы ускорить проверку, пришлите сюда скриншот чека (картинкой).\n"
                           "⚠ За попытку обмана вы получите блокировку.", None)
    except Exception as e:
        print(f"Не удалось написать игроку: {err_text(e)}")
    log_action(order.get("peer") or order["uid"], order["uid"], f"донат: оплата заказа №{order['id']} на проверке")
    return None

def pack_lines(key):
    """Что входит в набор — списком строк (для витрины и для сообщения о награде)."""
    from config import BUSINESSES
    pk = PACKS[key]
    lines = [f"💰 {fmt_num(pk['money'])} игровых денег"]
    if pk.get("exp"):
        lines.append(f"⭐ {pk['exp']} exp")
    lines.append(f"🎭 Персонаж для профиля: {SHOP_ITEMS[pk['char']][1]}")
    if pk.get("pets"):
        lines.append("🐾 Питомцы: " + ", ".join(PETS[p]["name"] for p in pk["pets"]))
    if pk.get("biz"):
        lines.append("🏢 Бизнесы: " + ", ".join(BUSINESSES[b]["name"] for b in pk["biz"]))
    if pk.get("perks"):
        lines.append("🔓 Доступ: " + ", ".join(PERK_TITLES[x] for x in pk["perks"]))
    if pk.get("vip"):
        lines.append(f"✨ VIP на {VIP_DAYS} дней")
    if pk.get("vamp_cd"):
        lines.append(f"🧛 Кд укуса вампира: {fmt_duration(pk['vamp_cd'])}")
    if pk.get("pet_cd"):
        lines.append(f"🐾 Кд кражи питомца: {fmt_duration(pk['pet_cd'])}")
    return lines

def give_pack(uid, key):
    """Выдаёт содержимое набора игроку. Можно вызывать и из команды владельца."""
    pk = PACKS[key]
    user = get_user(uid)
    user["money"] += pk["money"]
    if pk.get("exp"):
        add_exp(uid, pk["exp"])
    items = user.setdefault("items", [])
    if pk["char"] not in items:
        items.append(pk["char"])
    user.setdefault("equip", {})["char"] = pk["char"]
    for pet_id in pk.get("pets", []):
        give_pet(user, pet_id)
    for biz in pk.get("biz", []):
        user.setdefault("biz", {}).setdefault(biz, time.time())
    if pk.get("perks"):
        user["perks"] = sorted(set(user.get("perks") or []) | set(pk["perks"]))
    if pk.get("vip"):
        now = time.time()
        base = user["vip_until"] if vip_active(user) else now
        user["vip"] = True
        user["vip_until"] = base + VIP_DAYS * 86400
        if user.get("prefix", "") in ("", "VIP✨", VIP_PREFIX):
            user["prefix"] = VIP_PREFIX
    if pk.get("vamp_cd"):
        user["vamp_cd"] = pk["vamp_cd"]
    if pk.get("pet_cd"):
        user["pet_cd"] = pk["pet_cd"]
    return user

def donate_finish(order):
    """Оплата подтверждена: выдаёт награду (строго один раз) и сообщает игроку и в беседу."""
    if order.get("status") == "paid":
        return
    uid, key = order["uid"], order["item"]
    user = get_user(uid)
    duplicate = False
    dup_label = f"должность «{VAMPIRE_TITLE}»"
    if key == "pet":
        pet = PETS[DONATE_PET_ID]
        duplicate = has_pet(user, DONATE_PET_ID)
        dup_label = f"питомец «{pet['name']}»"
        give_pet(user, DONATE_PET_ID)
        reward = (f"🐶 Теперь у вас питомец «{pet['name']}»! Раз в {PET_COOLDOWN // 3600} ч. он может украсть {fmt_pct(pet['percent'])}% баланса игрока.\n"
                  "Команда: «пит украсть» (ответом на сообщение игрока) или «пит украсть @имя». Все питомцы: «питомцы».")
    elif key in PACKS:
        give_pack(uid, key)
        reward = f"{PACKS[key]['title']} получен! Вам выдано:\n" + "\n".join("• " + l for l in pack_lines(key)) + \
                 "\nПерсонаж уже надет — посмотреть: «профиль»."
    elif key == "vamp":
        duplicate = bool(user.get("vampire"))
        user["vampire"] = True
        user.setdefault("vampire_since", time.time())
        reward = (f"🧛 Вы стали {VAMPIRE_TITLE}! Раз в {VAMPIRE_COOLDOWN // 3600} ч. можно укусить игрока и забрать {fmt_pct(VAMPIRE_PERCENT)}% его денег "
                  f"(лидера топа по балансу — {fmt_pct(VAMPIRE_TOP_PERCENT)}%).\n"
                  "Команда: «укусить» (ответом на сообщение игрока) или «укусить @имя».")
    elif key == "heal":
        user["heal_until"] = max(time.time(), float(user.get("heal_until", 0) or 0)) + HEAL_DAYS * 86400
        reward = (f"🧪 Зелье лечения выпито! {HEAL_DAYS} дней Вампиры не смогут вас укусить.\n"
                  f"Действует до {fmt_time(user['heal_until'])}.")
    elif key == "virt":
        user["money"] += DONATE_ITEMS["virt"]["money"]
        reward = f"💎 +{fmt_num(DONATE_ITEMS['virt']['money'])} 💰. Баланс: {fmt_num(user['money'])} 💰"
    else:
        user["prefix"] = order.get("data") or user.get("prefix", "")
        reward = f"🏷 Ваш префикс: {user.get('prefix') or 'нет'}"
    order["status"], order["paid_t"] = "paid", time.time()
    save_economy()          # статус «оплачено» и награда сохраняются одной транзакцией
    donate_strip(order, "✅ Оплата принята.")
    donate_owner_update(order, f"✅ Подтверждено {fmt_time(time.time())}")
    save_economy()
    log_action(order.get("peer") or uid, uid, f"донат: принят заказ №{order['id']} ({key}, {order['price']}₽)")
    if duplicate:
        donate_notify(uid, f"✅ Оплата заказа №{order['id']} принята, но {dup_label} у вас уже есть. Владелец свяжется с вами.")
        donate_notify(OWNER_ID, f"⚠ Заказ №{order['id']}: у игрока id{uid} уже есть {dup_label}, оплата повторная — нужен возврат или другая награда.")
        return
    donate_notify(uid, f"✅ Оплата принята! Заказ №{order['id']}\n\n{reward}\n\nСпасибо за поддержку! 💛")
    peer = order.get("peer")
    if peer and peer >= CHAT_OFFSET:
        names = get_names([uid])
        donate_notify(peer, f"💎 {mention(uid, names)} поддержал(а) беседу: {donate_title(order)}. Спасибо!")

def donate_reject(order, block=False):
    uid = order["uid"]
    order["status"] = "rejected"
    if block:
        economy["donate_blocked"][str(uid)] = True
    save_economy()
    donate_strip(order)
    donate_owner_update(order, f"{'🚫 Отказано и заблокирован' if block else '❌ Отказано'} {fmt_time(time.time())}")
    save_economy()
    log_action(order.get("peer") or uid, uid, f"донат: отказ по заказу №{order['id']}" + (", блокировка" if block else ""))
    if block:
        donate_notify(uid, f"🚫 Заказ №{order['id']} отклонён: оплата не найдена. Доступ к донату закрыт за попытку обмана.")
    else:
        donate_notify(uid, f"❌ Заказ №{order['id']} не подтверждён: оплата не найдена.\n"
                           "Если вы уверены, что оплатили, — напишите «репорт» и приложите чек.\n"
                           "⚠ За попытку обмана вы получите блокировку.")

def donate_prune():
    """Раз в минуту закрывает старые неоплаченные заказы (кнопки у них пропадают)."""
    now = time.time()
    if now - economy.setdefault("donate_pruned", {}).get("t", 0) < 60:
        return
    economy["donate_pruned"]["t"] = now
    changed = False
    for o in economy["donate_orders"].values():
        if o.get("status") == "new" and now - o.get("t", now) > DONATE_OPEN_TTL:
            o["status"] = "closed"
            donate_strip(o, "⌛ Заказ закрыт: срок вышел. Новый заказ: «донат».")
            changed = True
    if changed:
        save_economy()

def donate_action(ev, p):
    uid, peer_id = ev["user_id"], ev["peer_id"]
    act = p.get("act")
    if act in ("ok", "no", "ban"):                 # кнопки владельца
        if uid != OWNER_ID:
            return "Это действие доступно только владельцу."
        o = find_order(p.get("id"))
        if not o:
            return "Заказ не найден."
        if o.get("status") != "wait":
            return f"Заказ №{o['id']} уже обработан ({o.get('status')})."
        if act == "ok":
            donate_finish(o)
            return f"Заказ №{o['id']} подтверждён ✅"
        donate_reject(o, block=(act == "ban"))
        return f"Заказ №{o['id']} отклонён" + (", игрок заблокирован" if act == "ban" else "")
    if act in ("buy", "have"):                     # витрина
        if uid != p.get("o"):
            return "Это окно открыл другой участник."
        if act == "have":
            return "Этот питомец уже у вас 🐶" if p.get("k") == "pet" else f"Вы уже {VAMPIRE_TITLE} 🧛"
        if p.get("k") == "pref":
            if donate_blocked(uid):
                return "🚫 Вам закрыт доступ к донату."
            try:
                send_dm(uid, f"{DONATE_ITEMS['pref']['title']} — {DONATE_ITEMS['pref']['price']} ₽\n\n"
                             f"Напишите мне сюда: донат префикс ВАШ_ТЕКСТ (до {DONATE_PREFIX_MAX} символов)\n"
                             "Пример: донат префикс Король чата")
            except Exception as e:
                print(f"Не удалось написать игроку {uid} в ЛС: {err_text(e)}")
                return donate_dm_closed(peer_id, uid)
            return "📩 Инструкция в личных сообщениях."
        if p.get("k") not in ("vamp", "heal", "virt", "pet") + PACK_KEYS:
            return "Кнопка устарела. Напишите «донат» заново."
        return donate_create(uid, p["k"], chat_peer=peer_id if peer_id >= CHAT_OFFSET else None)
    o = find_order(p.get("id"))                     # кнопки игрока под заказом
    if not o or o.get("uid") != uid:
        return "Это не ваш заказ."
    if o["status"] == "paid":
        return "Заказ уже оплачен ✅"
    if o["status"] == "wait":
        return "Оплата уже проверяется — ожидайте принятия."
    if o["status"] != "new":
        return "Заказ уже закрыт. Создайте новый: «донат»."
    if act == "cx":
        o["status"] = "cancelled"
        donate_strip(o, "❌ Заказ отменён.")
        save_economy()
        return "Заказ отменён."
    if act in ("qr", "card"):
        o["method"] = act
        kb = VkKeyboard(inline=True)
        kb.add_callback_button("✅ Я оплатил(а)", VkKeyboardColor.POSITIVE, {"cmd": "don", "act": "paid", "id": o["id"]})
        kb.add_line()
        other = "card" if act == "qr" else "qr"
        if other == "card" or os.path.exists(DONATE_QR_FILE):
            kb.add_callback_button("💳 Оплатить картой" if other == "card" else "📷 Оплатить по QR", VkKeyboardColor.SECONDARY,
                                   {"cmd": "don", "act": other, "id": o["id"]})
        kb.add_callback_button("❌ Отмена", VkKeyboardColor.NEGATIVE, {"cmd": "don", "act": "cx", "id": o["id"]})
        att = None
        if act == "qr":
            try:
                att = donate_qr_attachment()
            except Exception as e:
                print(f"Не удалось загрузить QR (у токена должно быть право «Фотографии»): {err_text(e)}")
        try:
            donate_card(o, donate_steps(o, act), kb.get_keyboard(), att)
        except Exception as e:
            print(f"Не удалось отправить шаги оплаты: {err_text(e)}")
            return "Не удалось отправить реквизиты. Попробуйте ещё раз."
        return None
    if act == "paid":
        if not o.get("method"):
            return "Сначала выберите способ оплаты."
        return donate_mark_paid(o)
    return "Кнопка устарела. Напишите «донат» заново."

def donate_receipt(msg):
    """Фото в ЛС от игрока с оплатой на проверке — это чек: пересылаем владельцу. True — сообщение обработано."""
    uid = msg["from_id"]
    photos = msg_photos(msg)
    waits = [o for o in economy["donate_orders"].values() if o.get("uid") == uid and o.get("status") == "wait"]
    if not photos or not waits:
        return False
    o = max(waits, key=lambda x: x.get("mark_t", 0))
    if o.get("receipts", 0) >= DONATE_MAX_RECEIPTS:
        send(uid, "🧾 Чеки по этому заказу уже получены. Ожидайте принятия.")
        return True
    try:
        send_dm(OWNER_ID, f"🧾 Чек к заказу №{o['id']} · {donate_name(uid)} (vk.com/id{uid}) · {o['price']} ₽", attachment=photos)
    except Exception as e:
        print(f"Не удалось переслать чек владельцу: {err_text(e)}")
        send(uid, "Не удалось передать чек. Попробуйте ещё раз чуть позже.")
        return True
    o["receipts"] = o.get("receipts", 0) + 1
    save_economy()
    send(uid, f"🧾 Чек к заказу №{o['id']} передан владельцу. Ожидайте принятия!")
    return True

def donate_prefix_check(text):
    """Возвращает (префикс, ошибка)."""
    new = sanitize_prefix(text)[:DONATE_PREFIX_MAX].strip()
    if not new:
        return None, f"ℹ️ Использование: донат префикс ВАШ_ТЕКСТ (до {DONATE_PREFIX_MAX} символов)"
    low = new.lower().replace("ё", "е")
    if any(b in low for b in DONATE_PREFIX_BANNED):
        return None, "⛔ Такой префикс нельзя: он похож на роль персонала или VIP. Придумайте другой."
    return new, None

def donate_owner_command(msg, word, tail):
    """Команды владельца. Возвращает True, если это была команда владельца."""
    peer_id = msg["peer_id"]
    if word in ("подтвердить", "confirm", "отказать", "reject"):
        o = find_order(tail.strip())
        if not o:
            send(peer_id, f"ℹ️ Использование: донат {word} НОМЕР_ЗАКАЗА")
        elif o.get("status") == "paid":
            send(peer_id, f"Заказ №{o['id']} уже оплачен.")
        elif word in ("подтвердить", "confirm"):
            donate_finish(o)
            send(peer_id, f"✅ Заказ №{o['id']} подтверждён, награда выдана.")
        else:
            donate_reject(o)
            send(peer_id, f"❌ Заказ №{o['id']} отклонён.")
        return True
    if word in ("блок", "разблок", "block", "unblock"):
        m = re.search(r"\d+", tail)
        if not m:
            send(peer_id, f"ℹ️ Использование: донат {word} ID")
            return True
        target = m.group(0)
        if word in ("блок", "block"):
            economy["donate_blocked"][target] = True
        else:
            economy["donate_blocked"].pop(target, None)
        save_economy()
        send(peer_id, f"{'🚫 Заблокирован' if word in ('блок', 'block') else '✅ Разблокирован'} id{target} в донате.")
        return True
    if word in ("список", "list"):
        waits = sorted((o for o in economy["donate_orders"].values() if o.get("status") == "wait"), key=lambda x: x.get("mark_t", 0))
        if not waits:
            send(peer_id, "Нет оплат, ожидающих проверки.")
            return True
        names = get_names(list({o["uid"] for o in waits[:15]}))
        lines = ["💰 Ждут проверки:"] + [f"• №{o['id']} — {names.get(o['uid'], 'id' + str(o['uid']))} (id{o['uid']}) — "
                                         f"{DONATE_ITEMS[o['item']]['title']}, {o['price']} ₽, с {fmt_time(o.get('mark_t', o['t']))}" for o in waits[:15]]
        lines.append("Подтвердить: «донат подтвердить НОМЕР», отказать: «донат отказать НОМЕР».")
        send(peer_id, "\n".join(lines))
        return True
    return False

def cmd_donate(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    chat_peer = peer_id if peer_id >= CHAT_OFFSET else None
    word, _, tail = rest.strip().partition(" ")
    word = word.lower().replace("ё", "е")
    if uid == OWNER_ID and donate_owner_command(msg, word, tail):
        return
    if word in ("префикс", "prefix"):
        new, err = donate_prefix_check(tail)
        send(peer_id, err or donate_create(uid, "pref", new, chat_peer))
        return
    donate_words = {"вампир": "vamp", "vampire": "vamp", "зелье": "heal", "heal": "heal", "вирты": "virt", "virt": "virt",
                    "питомец": "pet", "pet": "pet"}
    if word in ("набор", "наборы", "pack", "packs"):
        key = PACK_WORDS.get(tail.strip().lower().replace("ё", "е").replace("набор ", ""))
        if key:
            send(peer_id, donate_create(uid, key, chat_peer=chat_peer))
        else:
            send(peer_id, "ℹ️ Наборы: донат набор новичка (50 ₽) · вип (100 ₽) · ультра (150 ₽) · премиум (200 ₽)\n"
                          "Подробности — в меню «донат».")
        return
    if word in donate_words:
        send(peer_id, donate_create(uid, donate_words[word], chat_peer=chat_peer))
        return
    if word and not slash:      # «донат когда будет» и т.п. — обычный разговор, не реагируем
        return
    text, kb = donate_menu(uid)
    send(peer_id, text, kb)
