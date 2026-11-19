# -*- coding: utf-8 -*-
"""Аукцион: продажа персонажей и бизнесов между игроками."""
import math
import re
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from business import biz_accrued, biz_owned, biz_preview, kk_text
from config import (
    AUCTION_MAX_LOTS, AUCTION_MAX_PERCENT, AUCTION_MIN_PERCENT, AUCTION_PAGE, AUCTION_TTL,
    BUSINESSES, err_text, OWNER_ID,
)
from database import economy, get_user, save_economy
from helpers import (
    answer_event, edit_message, fmt_duration, fmt_num, get_names, mention, parse_amount, send,
)
from logs import log_action
from shop import in_auction, item_preview, KK, owned, SECRET_ITEMS, SHOP_ITEMS


# ---------- Аукцион (продажа персонажей и бизнесов между игроками) ----------
# «продать перс ID СУММА» / «продать бизнес НАЗВАНИЕ СУММА» — вещь уходит на аукцион (хранится у аукциона, пока лот висит),
# «аук» — все лоты, купить можно кнопкой или «аук купить №». Деньги сразу идут продавцу, вещь — покупателю.
# Защита экономики: цена лота — от AUCTION_MIN_PERCENT% до AUCTION_MAX_PERCENT% от цены в магазине.
AUC_CHAR_WORDS = ("перс", "персонаж", "персонажа", "персонажей", "персы", "character", "char")
AUC_BIZ_WORDS = ("бизнес", "бизнеса", "business")

def _norm(text):
    return text.lower().replace("ё", "е").strip()

def lot_base_price(kind, item):
    """Цена вещи в магазине — от неё считаются границы цены лота."""
    return SHOP_ITEMS[item][2] * KK if kind == "char" else BUSINESSES[item]["price"]

def lot_price_range(kind, item):
    base = lot_base_price(kind, item)
    low = base * AUCTION_MIN_PERCENT // 100
    high = base * AUCTION_MAX_PERCENT // 100 if AUCTION_MAX_PERCENT else None
    return low, high

def lot_hidden(lot, viewer):
    """Секретный персонаж скрыт от всех, кроме продавца и тех, у кого он уже есть."""
    return (lot["kind"] == "char" and lot["item"] in SECRET_ITEMS and viewer != lot["seller"]
            and not owned(get_user(viewer), lot["item"]))

def lot_name(lot, viewer):
    if lot["kind"] == "biz":
        b = BUSINESSES[lot["item"]]
        return f"{b['emoji']} {b['name']}"
    return "🎭 ??? (секретный персонаж)" if lot_hidden(lot, viewer) else f"🎭 {SHOP_ITEMS[lot['item']][1]}"

def lots_of(uid):
    return [l for l in economy["auction"].values() if l["seller"] == uid]

def find_char_id(ident):
    """Персонаж игрока по ID («5», «char5») или названию («Девушка», «белые волосы»). None — не найден."""
    ident = _norm(ident)
    if ident.isdigit():
        item = f"char{int(ident)}"
    elif re.fullmatch(r"char\d+", ident):
        item = f"char{int(ident[4:])}"
    else:
        item = next((i for i, v in SHOP_ITEMS.items() if _norm(v[1]) == ident), None)
    return item if item in SHOP_ITEMS else None

def find_biz(ident):
    ident = _norm(ident)
    return next((k for k, b in BUSINESSES.items() if k == ident or _norm(b["name"]) == ident), None)

def lot_give(user, kind, item, equip):
    """Вещь из лота — игроку. Купленный персонаж сразу надевается (как в магазине)."""
    if kind == "char":
        user.setdefault("items", []).append(item)
        if equip:
            user.setdefault("equip", {})[SHOP_ITEMS[item][0]] = item
    else:
        user.setdefault("biz", {})[item] = time.time()

def auction_return(lot):
    """Лот снят или не продался — вещь возвращается продавцу (если вдруг такая уже есть — деньги по цене магазина)."""
    user = get_user(lot["seller"])
    kind, item = lot["kind"], lot["item"]
    have = owned(user, item) if kind == "char" else item in biz_owned(user)
    if have:
        user["money"] += lot_base_price(kind, item)
    else:
        lot_give(user, kind, item, equip=False)

def auction_sell(msg, kind, args):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if kind == "char":
        usage = ("ℹ️ Продать персонажа другому игроку: продать перс ID СУММА\n"
                 "Пример: продать перс 5 600кк\n"
                 "ID вашего персонажа — в «мои аксессуары». Можно и названием: продать перс Девушка 600кк")
    else:
        usage = ("ℹ️ Продать бизнес другому игроку: продать бизнес НАЗВАНИЕ СУММА\n"
                 "Пример: продать бизнес Пекарня 1,2ккк\n"
                 "Накопленный доход бизнеса выплачивается вам сразу при выставлении.")
    price = parse_amount(args[-1]) if len(args) >= 2 else None
    if price is None:
        send(peer_id, usage)
        return
    ident = " ".join(args[:-1])
    user = get_user(uid)

    if kind == "char":
        item = find_char_id(ident)
        if item is None:
            send(peer_id, "❌ Такого персонажа нет. ID смотрите в «мои аксессуары».")
            return
        if not owned(user, item):
            send(peer_id, "❌ У вас нет этого персонажа. ID ваших персонажей — в «мои аксессуары».")
            return
        title = SHOP_ITEMS[item][1]
    else:
        item = find_biz(ident)
        if item is None:
            send(peer_id, "❌ Такого бизнеса нет. Доступны: " + ", ".join(b["name"] for b in BUSINESSES.values()) + ".")
            return
        if item not in biz_owned(user):
            send(peer_id, f"❌ У вас нет бизнеса «{BUSINESSES[item]['name']}».")
            return
        title = f"{BUSINESSES[item]['emoji']} {BUSINESSES[item]['name']}"

    if len(lots_of(uid)) >= AUCTION_MAX_LOTS:
        send(peer_id, f"⛔ У вас уже {AUCTION_MAX_LOTS} лотов — это максимум. Снять лот: аук снять №")
        return
    low, high = lot_price_range(kind, item)
    base = lot_base_price(kind, item)
    if price < low:
        send(peer_id, f"⛔ Слишком дёшево. Цена в магазине — {kk_text(base)}, дешевле {AUCTION_MIN_PERCENT}% "
                      f"({fmt_num(low)} 💰) ставить нельзя — это защита экономики.")
        return
    if high and price > high:
        send(peer_id, f"⛔ Слишком дорого. Цена в магазине — {kk_text(base)}, дороже {AUCTION_MAX_PERCENT}% "
                      f"({fmt_num(high)} 💰) ставить нельзя.")
        return

    extra = ""
    if kind == "char":                           # вещь уходит на хранение аукциону; если надета — снимается
        user["items"].remove(item)
        eq = user.get("equip", {})
        if eq.get(SHOP_ITEMS[item][0]) == item:
            eq.pop(SHOP_ITEMS[item][0], None)
    else:                                        # доход, накопленный до продажи, остаётся продавцу
        paid = biz_accrued(user, item, time.time())
        user["money"] += paid
        del user["biz"][item]
        if paid:
            extra = f"\n💵 Накопленный доход выплачен вам: +{fmt_num(paid)} 💰"
    economy["seq"]["auction"] += 1
    lid = economy["seq"]["auction"]
    economy["auction"][str(lid)] = {"id": lid, "kind": kind, "item": item, "seller": uid,
                                    "price": price, "t": time.time()}
    save_economy()
    log_action(peer_id, uid, f"аукцион: выставил лот №{lid} ({kind} {item}) за {price}")
    send(peer_id, f"🏛 Лот №{lid} выставлен на аукцион\n{title} — {fmt_num(price)} 💰\n"
                  f"(в магазине {kk_text(base)}){extra}\n\n"
                  f"Лот висит {AUCTION_TTL // 86400} дн., потом вещь вернётся к вам. Снять раньше: аук снять {lid}")

def auction_buy(peer_id, uid, lot_id):
    """Покупка лота. Возвращает (успех, короткий текст). При успехе сама пишет в беседу."""
    lot = economy["auction"].get(str(lot_id))
    if not lot:
        return False, "Лот не найден — его уже купили или сняли."
    kind, item, price = lot["kind"], lot["item"], lot["price"]
    if lot["seller"] == uid:
        return False, "Это ваш лот. Снять: аук снять " + str(lot_id)
    user = get_user(uid)
    if (owned(user, item) if kind == "char" else item in biz_owned(user)):
        return False, "У вас уже есть " + ("этот персонаж." if kind == "char" else "такой бизнес.")
    if in_auction(uid, kind, item):
        return False, "Эта вещь у вас на аукционе — снимите лот."
    if user["money"] < price:
        return False, f"Не хватает {fmt_num(price - user['money'])} 💰"
    seller = get_user(lot["seller"])
    user["money"] -= price
    seller["money"] += price
    del economy["auction"][str(lot_id)]
    lot_give(user, kind, item, equip=True)
    save_economy()
    log_action(peer_id, uid, f"аукцион: купил лот №{lot_id} ({kind} {item}) за {price} у {lot['seller']}")
    log_action(peer_id, lot["seller"], f"аукцион: продан лот №{lot_id} ({kind} {item}) за {price} → {uid}")
    names = get_names([uid, lot["seller"]])
    real = SHOP_ITEMS[item][1] if kind == "char" else f"{BUSINESSES[item]['emoji']} {BUSINESSES[item]['name']}"
    what = "секретного персонажа" if item in SECRET_ITEMS and kind == "char" else f"«{real}»"   # секрет в беседе не раскрываем
    try:
        send(peer_id, f"🏛 {mention(uid, names)} купил(а) {what} у {mention(lot['seller'], names)} "
                      f"за {fmt_num(price)} 💰 (лот №{lot_id})")
    except Exception as e:
        print(f"Не удалось написать о покупке лота: {err_text(e)}")
    return True, f"✅ Куплено: {real}"[:90]

def auction_cancel(peer_id, uid, lot_id):
    lot = economy["auction"].get(str(lot_id))
    if not lot:
        send(peer_id, "❌ Лот не найден — возможно, его уже купили или сняли.")
        return
    if lot["seller"] != uid and uid != OWNER_ID:
        send(peer_id, "⛔ Это не ваш лот.")
        return
    del economy["auction"][str(lot_id)]
    auction_return(lot)
    save_economy()
    log_action(peer_id, uid, f"аукцион: снят лот №{lot_id} ({lot['kind']} {lot['item']})")
    send(peer_id, f"↩️ Лот №{lot_id} ({lot_name(lot, lot['seller'])}) снят — вещь вернулась продавцу.")

def prune_auction():
    """Лот провисел AUCTION_TTL и не продался — вещь возвращается продавцу."""
    now = time.time()
    old = [l for l in economy["auction"].values() if now - l["t"] >= AUCTION_TTL]
    for lot in old:
        del economy["auction"][str(lot["id"])]
        auction_return(lot)
        log_action(0, lot["seller"], f"аукцион: лот №{lot['id']} не продан за срок, вещь возвращена")
    if old:
        save_economy()
        for lot in old:
            try:
                send(lot["seller"], f"⌛ Лот №{lot['id']} ({lot_name(lot, lot['seller'])}) не продался за "
                                    f"{AUCTION_TTL // 86400} дн. — вещь вернулась к вам.")
            except Exception:
                pass                                     # ЛС закрыты — не страшно

def build_auction_page(peer_id, page, opener_id):
    lots = sorted(economy["auction"].values(), key=lambda l: -l["t"])      # новые сверху
    pages = max(1, math.ceil(len(lots) / AUCTION_PAGE))
    page = max(1, min(page, pages))
    chunk = lots[(page - 1) * AUCTION_PAGE: page * AUCTION_PAGE]
    names = get_names(sorted({l["seller"] for l in chunk}))
    head = f"🏛 Аукцион — лотов: {len(lots)}" + (f" (стр. {page}/{pages})" if pages > 1 else "")
    lines = [head, ""]
    if not chunk:
        lines.append("Сейчас ничего не продаётся.")
    for lot in chunk:
        extra = ""
        if lot["kind"] == "biz":
            extra = f" · доход {kk_text(BUSINESSES[lot['item']]['income'])}/12ч"
        lines.append(f"№{lot['id']} {lot_name(lot, opener_id)} — {fmt_num(lot['price'])} 💰")
        lines.append(f"   в магазине {kk_text(lot_base_price(lot['kind'], lot['item']))}{extra} · "
                     f"продавец {mention(lot['seller'], names)}")
    lines += ["",
              "Купить — кнопкой или «аук купить №». Фото и подробности: «аук №».",
              "Выставить: «продать перс ID СУММА», «продать бизнес НАЗВАНИЕ СУММА». Свои лоты: «аук мои»."]
    kb = VkKeyboard(inline=True)
    has_buttons = False
    for i, lot in enumerate(chunk):
        if i and i % 2 == 0:
            kb.add_line()
        kb.add_callback_button(f"Купить №{lot['id']}", VkKeyboardColor.POSITIVE,
                               {"cmd": "auc", "a": "buy", "i": lot["id"], "x": page, "o": opener_id})
        has_buttons = True
    if pages > 1:
        if has_buttons:
            kb.add_line()
        base = {"cmd": "auc", "a": "pg", "o": opener_id}
        kb.add_callback_button("◀", VkKeyboardColor.SECONDARY, dict(base, x=page - 1 if page > 1 else pages))
        kb.add_callback_button(f"{page}/{pages}", VkKeyboardColor.SECONDARY, dict(base, x=page))
        kb.add_callback_button("▶", VkKeyboardColor.SECONDARY, dict(base, x=page + 1 if page < pages else 1))
        has_buttons = True
    return "\n".join(lines), (kb.get_keyboard() if has_buttons else None)

def auction_show(peer_id, viewer, lot_id):
    """Карточка лота с фото и кнопкой «Купить»."""
    lot = economy["auction"].get(str(lot_id))
    if not lot:
        send(peer_id, "❌ Лот не найден — возможно, его уже купили или сняли.")
        return
    kind, item = lot["kind"], lot["item"]
    names = get_names([lot["seller"]])
    lines = [f"🏛 Лот №{lot['id']}", "", lot_name(lot, viewer)]
    if kind == "biz":
        b = BUSINESSES[item]
        lines += [b["desc"], f"Доход: {fmt_num(b['income'])} 💰 за 12 ч. ({kk_text(b['income'])})"]
        att = biz_preview(peer_id, item)
    else:
        hidden = lot_hidden(lot, viewer)
        lines.append("Секретный персонаж. Что внутри — узнаете после покупки" if hidden else SHOP_ITEMS[item][3])
        att = item_preview(peer_id, item, hidden=hidden)
    left = AUCTION_TTL - (time.time() - lot["t"])
    lines += [f"💰 Цена: {fmt_num(lot['price'])} (в магазине {kk_text(lot_base_price(kind, item))})",
              f"Продавец: {mention(lot['seller'], names)}",
              f"Лот закроется через {fmt_duration(max(0, left))}"]
    kb = VkKeyboard(inline=True)
    kb.add_callback_button(f"Купить за {kk_text(lot['price'])}", VkKeyboardColor.POSITIVE,
                           {"cmd": "auc", "a": "buy", "i": lot["id"], "x": 0, "o": viewer})
    send(peer_id, "\n".join(lines), kb.get_keyboard(), attachment=att)

def auction_mine(peer_id, uid):
    mine = sorted(lots_of(uid), key=lambda l: l["id"])
    if not mine:
        send(peer_id, "🏛 У вас нет лотов. Выставить: продать перс ID СУММА или продать бизнес НАЗВАНИЕ СУММА")
        return
    now = time.time()
    lines = [f"🏛 Ваши лоты ({len(mine)}/{AUCTION_MAX_LOTS}):", ""]
    for lot in mine:
        left = fmt_duration(max(0, AUCTION_TTL - (now - lot["t"])))
        lines.append(f"№{lot['id']} {lot_name(lot, uid)} — {fmt_num(lot['price'])} 💰 (ещё {left})")
    lines += ["", "Снять лот: аук снять №"]
    send(peer_id, "\n".join(lines))

def cmd_auction(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    words = _norm(rest).split()
    if not words:
        text, kb = build_auction_page(peer_id, 1, uid)
        send(peer_id, text, kb)
        return
    first = words[0]
    num = words[1].lstrip("№#") if len(words) > 1 else ""
    if first in ("купить", "buy") and num.isdigit():
        ok, note = auction_buy(peer_id, uid, int(num))
        if not ok:
            send(peer_id, f"⚠ {note}")
    elif first in ("снять", "убрать", "cancel") and num.isdigit():
        auction_cancel(peer_id, uid, int(num))
    elif first in ("мои", "мой", "my", "лоты"):
        auction_mine(peer_id, uid)
    elif first.lstrip("№#").isdigit() and len(words) == 1:
        auction_show(peer_id, uid, int(first.lstrip("№#")))
    elif slash:
        send(peer_id, "ℹ️ Аукцион: аук — список лотов, аук № — подробности, аук купить №, аук снять №, аук мои")

def auction_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    act = p.get("a")
    page = int(p.get("x", 1))
    if act == "pg":
        if uid != p.get("o"):
            return "Листать может тот, кто открыл список. Напишите «аук» сами."
        answer_event(ev)
        text, kb = build_auction_page(peer_id, page, uid)
        edit_message(peer_id, cmid, text, kb)
        return None
    if act == "buy":
        lot_id = int(p.get("i", 0))
        ok, note = auction_buy(peer_id, uid, lot_id)
        answer_event(ev, note)
        if page == 0:                                    # карточка лота: после покупки убираем кнопку
            if ok:
                edit_message(peer_id, cmid, f"🏛 Лот №{lot_id} продан.")
        else:                                            # список: обновляем страницу (купленный лот исчез)
            text, kb = build_auction_page(peer_id, page, p.get("o", uid))
            edit_message(peer_id, cmid, text, kb)
        return None
    return None
