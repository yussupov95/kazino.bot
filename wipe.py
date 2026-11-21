# -*- coding: utf-8 -*-
"""Подозрительные «сдачи» в крестики-нолики: уведомление владельцу, обнуление аккаунтов, восстановление.

Как работает:
  • ttt.py при каждой сдаче зовёт note_surrender(). Один и тот же игрок сдался одному и тому же сопернику
    два раза за SUR_WINDOW секунд — владельцу в ЛС приходит карточка с кнопками «Обнулить у обоих» / «Отказать».
  • «Обнулить»: перед обнулением снимок аккаунта (деньги, бизнесы, питомцы, предметы, банк, лоты аукциона)
    сохраняется в economy["settings"]["wiped"] (лежит в базе, переживает перезапуск). В беседу уходит
    сообщение без имени владельца и без записи в логи.
  • «восстановить ID» (в беседе или в ЛС боту) возвращает аккаунт из снимка. «забрать ID СУММА» — как обычно.
"""
import copy
import re
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import CHAT_OFFSET, err_text, OWNER_ID
from database import economy, get_user, save_economy
from extras import appeal_keyboard, appeal_urls
from helpers import (
    answer_event, edit_message, fmt_num, get_names, mention, parse_target, send, send_dm,
)

SUR_WINDOW = 60              # два «сдался» одного игрока одному сопернику за столько секунд — тревога
WIPE_REASON = "порчу экономики, багоюзы, злоупотребление правами чата"
_sur = {}                    # (сдавшийся, победитель) -> [время сдач]


# ---------- слежка за сдачами (вызывается из ttt.ttt_finish) ----------
def note_surrender(g, loser, winner):
    if not loser or not winner or OWNER_ID in (loser, winner):
        return
    now = time.time()
    for k in [k for k, v in _sur.items() if now - v[-1] > SUR_WINDOW]:
        del _sur[k]
    key = (loser, winner)
    times = [t for t in _sur.get(key, []) if now - t <= SUR_WINDOW]
    times.append(now)
    if len(times) >= 2:
        _sur.pop(key, None)
        _notify_owner(g, loser, winner)
    else:
        _sur[key] = times

def _notify_owner(g, loser, winner):
    try:
        names = get_names([loser, winner])
        lu, wu = get_user(loser), get_user(winner)
        text = ("🚨 Подозрительная игра в крестики-нолики\n"
                f"{names.get(loser, '?')} (vk.com/id{loser}) сдался {names.get(winner, '?')} (vk.com/id{winner}) "
                f"два раза подряд за {SUR_WINDOW} сек.\n"
                f"Ставка: {fmt_num(g['bet'])} 💰 с каждого\n"
                f"Баланс сдавшегося: {fmt_num(lu['money'])} 💰\n"
                f"Баланс победителя: {fmt_num(wu['money'])} 💰\n"
                f"Беседа: peer_id {g.get('peer')}\n"
                f"Время: {time.strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                f"Обнулить аккаунты обоих игроков или отказать?\n"
                f"Вернуть позже: восстановить ID")
        base = {"cmd": "wipe", "u": loser, "v": winner, "p": g.get("peer") or 0}
        kb = VkKeyboard(inline=True)
        kb.add_callback_button("🧹 Обнулить у обоих", VkKeyboardColor.NEGATIVE, dict(base, a="y"))
        kb.add_callback_button("❌ Отказать", VkKeyboardColor.SECONDARY, dict(base, a="n"))
        send(OWNER_ID, text, kb.get_keyboard())
    except Exception as e:
        print(f"Не удалось уведомить владельца о подозрительных сдачах: {err_text(e)}")


# ---------- снимки, обнуление, восстановление ----------
def _snaps():
    return economy.setdefault("settings", {}).setdefault("wiped", {})

def wipe_account(uid):
    """Обнуляет аккаунт: деньги, опыт, бизнесы, питомцы, предметы, VIP, банк, лоты аукциона, долги.
    Перед этим кладёт снимок для «восстановить». True — аккаунт был."""
    key = str(uid)
    if uid <= 0 or uid == OWNER_ID:
        return False
    users = economy["users"]
    old = users.get(key)
    if old is None:
        return False
    snaps = _snaps()
    prev = snaps.get(key)
    already_empty = prev and old.get("money", 0) <= 0 and not old.get("biz")
    if not already_empty:                       # повторное обнуление не затирает снимок пустым аккаунтом
        lots = {lid: copy.deepcopy(l) for lid, l in economy.get("auction", {}).items() if l.get("seller") == uid}
        snaps[key] = {"t": int(time.time()), "user": copy.deepcopy(old),
                      "bank": copy.deepcopy(economy.get("bank", {}).get(key)), "lots": lots}
    users[key] = {"money": 0, "exp": 0, "last_bonus": 0, "reg": old.get("reg", time.time())}
    economy.get("bank", {}).pop(key, None)
    for lid in [lid for lid, l in economy.get("auction", {}).items() if l.get("seller") == uid]:
        del economy["auction"][lid]
    now = int(time.time())
    for d in economy.get("debts", {}).values():
        if uid in (d.get("lender"), d.get("borrower")) and d.get("status") in ("active", "pending"):
            d["status"], d["closed"] = "failed", now
    save_economy()
    return True

def _merge(base, cur):
    """К восстановленному аккаунту добавляем то, что игрок получил после обнуления."""
    for k, v in cur.items():
        if k in ("money", "exp", "btc"):
            base[k] = base.get(k, 0) + v
        elif k not in base:
            base[k] = v
        elif isinstance(v, dict) and isinstance(base[k], dict):
            for kk, vv in v.items():
                base[k].setdefault(kk, vv)
        elif isinstance(v, list) and isinstance(base[k], list):
            base[k] += [x for x in v if x not in base[k]]
    return base

def restore_account(uid):
    """Возвращает аккаунт из снимка. None — снимка нет."""
    key = str(uid)
    snap = _snaps().get(key)
    if not snap:
        return None
    user = _merge(copy.deepcopy(snap["user"]), economy["users"].get(key) or {})
    economy["users"][key] = user
    if snap.get("bank"):
        economy.setdefault("bank", {}).setdefault(key, []).extend(copy.deepcopy(snap["bank"]))
    for lid, lot in (snap.get("lots") or {}).items():
        economy.setdefault("auction", {}).setdefault(lid, copy.deepcopy(lot))
    del _snaps()[key]
    save_economy()
    return user


# ---------- кнопки в ЛС владельца ----------
def _edit(ev, text):
    try:
        edit_message(ev["peer_id"], ev["conversation_message_id"], text)
    except Exception as e:
        print(f"Не удалось обновить карточку обнуления: {err_text(e)}")

def _wipe_action(ev, p):
    u, v, peer = int(p.get("u", 0)), int(p.get("v", 0)), int(p.get("p", 0))
    if p.get("a") == "n":
        _edit(ev, "❌ Отказано: аккаунты не тронуты.")
        return "Отказано"
    wiped = [x for x in (u, v) if wipe_account(x)]
    if not wiped:
        _edit(ev, "ℹ️ Нечего обнулять: аккаунты не найдены.")
        return "Аккаунты не найдены"
    names = get_names(wiped)
    who = ", ".join(mention(x, names) for x in wiped)
    _edit(ev, f"🧹 Обнулено: {who}\nВернуть: восстановить ID\nЗабрать деньги: забрать ID СУММА")
    if peer >= CHAT_OFFSET:                      # сообщение игрокам: без имени владельца, без записи в логи
        form, _ = appeal_urls()
        text = (f"🧹 Аккаунты {who} обнулены за {WIPE_REASON}.\n\n" +
                (f"📝 Если вы не согласны, ссылка на апелляцию:\n{form}" if form else
                 "📝 Если вы не согласны, нажмите «Отправить обжалование»."))
        try:
            send(peer, text, appeal_keyboard(wiped))
        except Exception as e:
            print(f"Не удалось написать в беседу об обнулении: {err_text(e)}")
    return "Обнулено"

def wipe_callback(ev, p):
    note = None
    try:
        note = "Это действие доступно только владельцу." if ev["user_id"] != OWNER_ID else _wipe_action(ev, p)
    finally:
        answer_event(ev, note)


# ---------- «восстановить ID»: беседа и ЛС владельца ----------
RESTORE_USAGE = ("ℹ️ Вернуть обнулённый аккаунт: восстановить ID (или ответом на сообщение игрока)\n"
                 "Забрать деньги после восстановления: забрать ID СУММА")

def find_id(msg, text):
    """ID из текста: [id1|имя], vk.com/id1, просто число; в беседе — ещё и ответ на сообщение."""
    m = re.search(r"vk\.(?:com|ru)/id(\d+)", text)
    if m:
        return int(m.group(1))
    target, _ = parse_target(msg, text)
    return target

def restore_command(msg, rest, strict=False):
    """True — сообщение обработано. strict=True (ЛС): без ID не отвечаем, потому что «восстановить»
    без ID — это восстановление базы из файла (backup.py)."""
    peer = msg["peer_id"]
    target = find_id(msg, rest or "")
    if target is None or target <= 0:
        if strict:
            return False
        send(peer, RESTORE_USAGE)
        return True
    names = get_names([target])
    who = mention(target, names)
    user = restore_account(target)
    if user is None:
        send(peer, f"ℹ️ У {who} нет снимка: аккаунт не обнулялся (или уже восстановлен).")
        return True
    send(peer, f"✅ Аккаунт {who} восстановлен.\nБаланс: {fmt_num(user['money'])} 💰\n"
               "Деньги, полученные после обнуления, сохранены. Забрать часть: забрать ID СУММА")
    try:
        send_dm(target, "✅ Ваша апелляция рассмотрена: аккаунт восстановлен.")
    except Exception:
        pass                                    # у игрока закрыты ЛС — не страшно
    return True

def cmd_restore_account(msg, rest, slash):
    """Команда в беседе. Только владелец; остальным не отвечаем (обычное слово «восстановить»)."""
    if msg["from_id"] != OWNER_ID:
        return
    restore_command(msg, rest)
