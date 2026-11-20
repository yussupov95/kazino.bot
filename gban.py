# -*- coding: utf-8 -*-
"""Глобальный бан (гбан) и должность «Зам чата»."""
import threading
import time

from chats import known_chats
from config import (
    BROADCAST_DELAY, DEPUTY_LEVEL, err_text, GBAN_MIN_RANK, GBAN_TAG, GL_DEPUTY_LEVEL, GL_DEPUTY_RANK,
    MIN_LEVEL_TO_DEPUTY, OWNER_ID,
)
from database import data, get_level, is_deputy, punish, raw_level, save_data, save_punish, set_level
from helpers import deny, get_names, kick_from_chat, mention, no_target, parse_target, send
from logs import log_action

_kick_seen = {}     # (беседа, игрок) -> время последней попытки исключения (чтобы не сыпать запросами)


def rank(peer_id, uid):
    """Ранг для глобального бана: уровень × 10, «Зам чата» = 35 (между Администратором и Тех специалистом)."""
    if uid == OWNER_ID:
        return 100
    raw = raw_level(peer_id, uid)
    if raw == GL_DEPUTY_LEVEL:
        return GL_DEPUTY_RANK
    return 35 if raw == DEPUTY_LEVEL else raw * 10


def _mark_ban(peer, target, by, reason):
    """Записывает бан в беседу (обычный бан не перезаписывается). True — запись добавлена."""
    chat = punish.setdefault("bans", {}).setdefault(str(peer), {})
    if str(target) in chat:
        return False
    chat[str(target)] = {"by": by, "reason": GBAN_TAG + reason, "t": int(time.time())}
    return True


def _kick_all(report_peer, target, chats):
    kicked = 0
    for peer in chats:
        try:
            kick_from_chat(peer, target)
            kicked += 1
        except Exception:
            pass          # игрока нет в беседе или у бота нет прав — это нормально
        time.sleep(BROADCAST_DELAY)
    try:
        send(report_peer, f"🌐 Глобальный бан: исключён из {kicked} бесед (всего бесед: {len(chats)}).")
    except Exception as e:
        print(f"Гбан: не удалось отправить итог: {err_text(e)}")


def cmd_gban(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if rank(peer_id, uid) < GBAN_MIN_RANK:
        deny(msg, rest, slash, "⛔ Глобальный бан доступен с должности «Зам чата».")
        return
    if rest.strip().lower() in ("список", "list"):
        gb = punish.get("gbans", {})
        if not gb:
            send(peer_id, "🌐 Глобальных банов нет.")
            return
        ids = [int(k) for k in list(gb)[:30]]
        names = get_names(ids)
        send(peer_id, "🌐 Глобальный бан:\n" + "\n".join(
            f"• {mention(i, names)} — {gb[str(i)].get('reason') or 'без причины'}" for i in ids))
        return
    target, reason = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, "ℹ️ Глобальный бан: гбан (ответом / ID / @упоминание) [причина]")
        return
    if target <= 0:
        send(peer_id, "⚠ Это действие нельзя применить к сообществу.")
        return
    if target == OWNER_ID:
        send(peer_id, "⛔ Владельца трогать нельзя.")
        return
    if target == uid:
        send(peer_id, "⛔ Нельзя применить это к самому себе.")
        return
    if rank(peer_id, target) >= rank(peer_id, uid):
        send(peer_id, "⛔ Нельзя применить это к пользователю с таким же или более высоким уровнем.")
        return
    if str(target) in punish.setdefault("gbans", {}):
        send(peer_id, "ℹ️ Этот пользователь уже в глобальном бане.")
        return
    reason = reason or "без причины"
    punish["gbans"][str(target)] = {"by": uid, "reason": reason, "t": int(time.time())}
    chats = known_chats()
    if peer_id not in chats:
        chats.append(peer_id)
    for peer in chats:
        _mark_ban(peer, target, uid, reason)
        data.get(str(peer), {}).pop(str(target), None)      # заодно снимаем его роли
    save_punish()
    save_data()
    names = get_names([uid, target])
    send(peer_id, f"🌐 {mention(target, names)} получил глобальный бан от {mention(uid, names)}.\n"
                  f"Причина: {reason}\nИсключаю из всех бесед бота…")
    try:
        log_action(peer_id, uid, f"гбан {target}: {reason}")
    except Exception:
        pass
    threading.Thread(target=_kick_all, args=(peer_id, target, chats), daemon=True).start()


def cmd_ungban(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if rank(peer_id, uid) < GBAN_MIN_RANK:
        deny(msg, rest, slash, "⛔ Снять глобальный бан может «Зам чата» и выше.")
        return
    target, _ = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, "ℹ️ Снять глобальный бан: разгбан (ответом / ID / @упоминание)")
        return
    if punish.setdefault("gbans", {}).pop(str(target), None) is None:
        send(peer_id, "ℹ️ Этот пользователь не в глобальном бане.")
        return
    removed = 0
    for chat in punish.setdefault("bans", {}).values():      # убираем только баны с пометкой гбана — обычные остаются
        entry = chat.get(str(target))
        if entry and (entry.get("reason") or "").startswith(GBAN_TAG):
            del chat[str(target)]
            removed += 1
    save_punish()
    names = get_names([target])
    send(peer_id, f"✅ Глобальный бан с {mention(target, names)} снят (бесед очищено: {removed}).")
    try:
        log_action(peer_id, uid, f"разгбан {target}")
    except Exception:
        pass


def gban_guard(msg):
    """True — это вход или сообщение игрока из глобального бана (он исключён, дальше обрабатывать не нужно)."""
    gb = punish.get("gbans")
    if not gb:
        return False
    peer, uid = msg["peer_id"], msg["from_id"]
    action = msg.get("action")
    victim = None
    if action:
        t = action.get("type")
        if t == "chat_invite_user":
            victim = action.get("member_id")
        elif t in ("chat_invite_user_by_link", "chat_invite_user_by_message_request"):
            victim = uid
    elif uid > 0:
        victim = uid
    if not victim or victim <= 0 or str(victim) not in gb:
        return False
    if _mark_ban(peer, victim, gb[str(victim)].get("by", 0), gb[str(victim)].get("reason") or "без причины"):
        save_punish()
    if not action:
        from helpers import delete_message
        delete_message(peer, msg["conversation_message_id"])
    now = time.time()
    if now - _kick_seen.get((peer, victim), 0) > 60:
        _kick_seen[(peer, victim)] = now
        try:
            kick_from_chat(peer, victim)
        except Exception as e:
            print(f"Гбан: не удалось исключить {victim} из {peer}: {err_text(e)}")
    return True


def cmd_deputy(msg, rest, slash):
    """«права зам (ответом / ID)» и «права зам снять ID» — вызывается через псевдоним в handlers.py."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if get_level(peer_id, uid) < MIN_LEVEL_TO_DEPUTY and rank(peer_id, uid) < GL_DEPUTY_RANK:
        deny(msg, rest, slash, "⛔ Назначать «Зам чата» может Тех специалист, Гл.Следящий Зам и Владелец.")
        return
    words = rest.split()
    if words and words[0].lower() == "чата":
        words = words[1:]
    remove = False
    for w in (words[:1] + words[-1:]):
        if w.lower() in ("снять", "убрать", "0", "-"):
            remove = True
    if remove:
        words = [w for w in words if w.lower() not in ("снять", "убрать", "0", "-")]
    target, _ = parse_target(msg, " ".join(words))
    if target is None:
        no_target(msg, rest, slash, "ℹ️ Назначить: права зам (ответом / ID). Снять: права зам снять ID")
        return
    if target <= 0 or target == OWNER_ID:
        send(peer_id, "⛔ Этому пользователю роль выдать нельзя.")
        return
    names = get_names([target])
    if remove:
        if not is_deputy(peer_id, target):
            send(peer_id, "ℹ️ Этот пользователь не Зам чата.")
            return
        set_level(peer_id, target, 0)
        send(peer_id, f"✅ {mention(target, names)} больше не Зам чата.")
        return
    if get_level(peer_id, target) >= MIN_LEVEL_TO_DEPUTY or raw_level(peer_id, target) == GL_DEPUTY_LEVEL:
        send(peer_id, "⛔ У этого пользователя уже должность выше.")
        return
    set_level(peer_id, target, DEPUTY_LEVEL)
    send(peer_id, f"✅ {mention(target, names)} назначен(а) на должность «Зам чата».")
