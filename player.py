# -*- coding: utf-8 -*-
"""Игрок: опыт и уровни, VIP, префикс, репутация."""
import re
import time

from config import (
    BONUS_EXP, BONUS_MONEY, LEVEL_UP_REWARD, MIN_LEVEL_TO_PREFIX, REP_COOLDOWN, ROLES,
    VIP_BONUS_MONEY, VIP_DAYS, VIP_PREFIX, VIP_PRICE, VIP_WIN_BONUS,
)
from database import (
    economy, exp_text, get_level, get_user, player_level, save_economy, vip_active,
)
from helpers import (
    answer_event, deny, edit_message, fmt_duration, fmt_num, fmt_time, get_names, mention,
    parse_target, send,
)
from logs import log_action


# ---------- Опыт, VIP, префикс ----------
def add_exp(uid, amount):
    """Начисляет опыт. За каждый новый уровень — награда. Возвращает текст о повышении или ''."""
    user = get_user(uid)
    old_level = player_level(user["exp"])[0]
    user["exp"] += amount
    new_level, new_name, _, _ = player_level(user["exp"])
    gained = new_level - old_level
    if gained <= 0:
        return ""
    reward = gained * LEVEL_UP_REWARD
    user["money"] += reward
    return f"🎉 Новый уровень: {new_level} — {new_name}!\nНаграда: +{fmt_num(reward)} 💰"

def sanitize_prefix(text):
    return re.sub(r"[\[\]|\r\n]", "", text).strip()[:20]

def vip_benefits():
    return (
        f"• Бонус каждый час: {fmt_num(VIP_BONUS_MONEY)} 💰 (вместо {fmt_num(BONUS_MONEY)})\n"
        f"• Опыт каждый час: {BONUS_EXP} exp\n"
        f"• Выигрыши в играх x{VIP_WIN_BONUS} (например, 2x → {2 * VIP_WIN_BONUS:g}x)\n"
        "• Переводы денег без паузы\n"
        f"• Список действующих промокодов в «истории»\n"
        f"• Префикс {VIP_PREFIX} рядом с именем\n"
        f"• Срок действия: {VIP_DAYS} дней"
    )

def vip_action(ev, p):
    uid = ev["user_id"]
    if uid != p.get("o"):
        return "Это окно открыл другой участник."
    peer_id, cmid = ev["peer_id"], ev["conversation_message_id"]
    key = f"vip:{peer_id}:{cmid}"
    if key in economy["games"]:
        return "Покупка уже оформлена."
    user = get_user(uid)
    if p.get("act") == "no":
        economy["games"][key] = {"t": int(time.time()), "done": True, "owner": uid}
        answer_event(ev)
        edit_message(peer_id, cmid, "❌ Покупка VIP отменена.")
        return None
    if user["money"] < VIP_PRICE:
        return f"Не хватает {fmt_num(VIP_PRICE - user['money'])} 💰"

    now = time.time()
    base = user["vip_until"] if vip_active(user) else now
    user["money"] -= VIP_PRICE
    user["vip"] = True
    user["vip_until"] = base + VIP_DAYS * 86400
    if user.get("prefix", "") in ("", "VIP✨", VIP_PREFIX):
        user["prefix"] = VIP_PREFIX
    economy["games"][key] = {"t": int(now), "done": True, "owner": uid}
    save_economy()
    log_action(peer_id, uid, f"купил VIP за {VIP_PRICE}")
    answer_event(ev)
    edit_message(peer_id, cmid,
                 f"✅ Поздравляем! VIP ✨ активен до {fmt_time(user['vip_until'])}\n\n"
                 f"Списано: {fmt_num(VIP_PRICE)} 💰\n"
                 f"Ваш баланс: {fmt_num(user['money'])} 💰\n\n"
                 f"Преимущества VIP:\n{vip_benefits()}")
    return None

def cmd_prefix(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    # «префикс» без аргументов — показать свой префикс и уровень (для всех)
    if not rest.strip() and not msg.get("reply_message") and not msg.get("fwd_messages"):
        show_own_prefix(msg)
        return
    level = get_level(peer_id, actor)
    if level < MIN_LEVEL_TO_PREFIX:
        deny(msg, rest, slash, f"⛔ Менять префикс могут {ROLES[MIN_LEVEL_TO_PREFIX]} и выше.")
        return

    usage = ("ℹ️ Использование: префикс НОВЫЙ_ПРЕФИКС — ответом на сообщение участника\n"
             "Или: префикс ID НОВЫЙ_ПРЕФИКС\nУбрать префикс: префикс -")
    target, tail = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, usage)
        return
    new = sanitize_prefix(tail)
    if not new:
        send(peer_id, usage)
        return
    if target <= 0:
        send(peer_id, "⚠ У сообществ нет префикса.")
        return
    if target != actor and get_level(peer_id, target) >= level:
        send(peer_id, "⛔ Нельзя менять префикс пользователю с таким же или более высоким уровнем.")
        return

    user = get_user(target)
    names = get_names([target])
    if new.lower() in ("-", "нет", "убрать", "сброс"):
        user.pop("prefix", None)
        save_economy()
        log_action(peer_id, actor, f"убрал префикс у {target}")
        send(peer_id, f"✅ Префикс убран у {mention(target, names)}.")
        return
    user["prefix"] = new
    save_economy()
    log_action(peer_id, actor, f"префикс {target}: {new}")
    send(peer_id, f"✅ Новый префикс: {mention(target, names)}")

# ---------- VIP: срок действия и коэффициент ----------
def win_mult(uid):
    """Во сколько раз VIP увеличивает коэффициент выигрыша (2x → 2.3x)."""
    return VIP_WIN_BONUS if vip_active(get_user(uid)) else 1.0

def show_own_prefix(msg):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    user = get_user(uid)
    active = vip_active(user)
    lvl, name, _, _ = player_level(user["exp"])
    role = ROLES.get(get_level(peer_id, uid), "Участник")
    lines = [
        "🏷️ Ваш префикс",
        "",
        f"Префикс: {user.get('prefix') or 'нет'}",
        f"Уровень: {lvl} — {name}",
        f"Опыт: {exp_text(user['exp'])}",
        f"Роль в беседе: {role}",
    ]
    if active:
        lines.append(f"✨ VIP до {fmt_time(user['vip_until'])}")
    else:
        lines += ["", f"Красивый префикс {VIP_PREFIX} даёт VIP — команда «купить вип»."]
    send(peer_id, "\n".join(lines))

# ---------- Репутация (+реп / −реп) ----------
def cmd_rep(msg, rest, slash, delta):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    word = "+реп" if delta > 0 else "-реп"
    target, tail = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, f"ℹ️ Использование: {word} — ответом на сообщение участника (можно с причиной)\n"
                          f"Или: {word} ID\nПауза между изменениями репутации — {REP_COOLDOWN // 3600} ч.")
        return
    if target <= 0 or target == uid:
        send(peer_id, "⛔ Нельзя менять репутацию себе или сообществу.")
        return

    user = get_user(uid)
    left = user.get("last_rep", 0) + REP_COOLDOWN - time.time()
    if left > 0:
        send(peer_id, f"⏳ Репутацию можно менять раз в {REP_COOLDOWN // 3600} ч. "
                      f"Следующий раз через {fmt_duration(left)}.")
        return

    other = get_user(target)
    other["rep"] = other.get("rep", 0) + delta
    user["last_rep"] = time.time()
    save_economy()
    log_action(peer_id, uid, f"{word} → {target}")
    names = get_names([uid, target])
    reason = f"\nПричина: {tail[:100]}" if tail.strip() else ""
    verb = "повысил" if delta > 0 else "понизил"
    send(peer_id, f"{'👍' if delta > 0 else '👎'} {mention(uid, names)} {verb} репутацию "
                  f"{mention(target, names)} ({delta:+d}). Репутация: {other['rep']}{reason}")

def cmd_rep_plus(msg, rest, slash):
    cmd_rep(msg, rest, slash, +1)

def cmd_rep_minus(msg, rest, slash):
    cmd_rep(msg, rest, slash, -1)
