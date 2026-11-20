# -*- coding: utf-8 -*-
"""Гл.Следящий Зам: штраф, норматив (-норма / +норма / +перенорма) и назначение должности."""
from config import (
    FINE_MAX, GL_DEPUTY_LEVEL, GL_DEPUTY_RANK, NORM_REWARD, NORM_WARNS_LIMIT, OWNER_ID, RENORM_REWARD,
)
from database import get_user, is_gl_deputy, punish, raw_level, save_economy, save_punish, set_level
from gban import rank
from helpers import deny, fmt_num, get_names, mention, no_target, parse_amount, parse_target, send
from logs import log_action

NO_RIGHTS = "⛔ Команда доступна только Гл.Следящему Заму и Владельцу."


def _norms(peer_id):
    return punish.setdefault("norms", {}).setdefault(str(peer_id), {})

def _norm_get(peer_id, uid):
    return _norms(peer_id).get(str(uid), 0)

def _norm_set(peer_id, uid, n):
    if n <= 0:
        _norms(peer_id).pop(str(uid), None)
    else:
        _norms(peer_id)[str(uid)] = n
    save_punish()

def _log(peer_id, uid, text):
    try:
        log_action(peer_id, uid, text)
    except Exception:
        pass

def _check_target(peer_id, uid, target, need_role=False):
    if target <= 0:
        return "⚠ Это действие нельзя применить к сообществу."
    if target == OWNER_ID:
        return "⛔ Владельца трогать нельзя."
    if target == uid:
        return "⛔ Нельзя применить это к самому себе."
    if rank(peer_id, target) >= rank(peer_id, uid):
        return "⛔ Нельзя применить это к пользователю с таким же или более высоким уровнем."
    if need_role and raw_level(peer_id, target) == 0:
        return "⚠ У этого пользователя нет должности в этой беседе."
    return None


def cmd_fine(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if rank(peer_id, uid) < GL_DEPUTY_RANK:
        deny(msg, rest, slash, NO_RIGHTS)
        return
    target, tail = parse_target(msg, rest)
    usage = "ℹ️ Штраф: штраф (ответом / ID / @упоминание) СУММА [причина]\nПример: штраф @ivan 50кк срыв норматива"
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split(maxsplit=1)
    amount = parse_amount(parts[0]) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    err = _check_target(peer_id, uid, target)
    if err:
        send(peer_id, err)
        return
    if amount > FINE_MAX:
        send(peer_id, f"⚠ Максимум одного штрафа: {fmt_num(FINE_MAX)} 💰")
        return
    reason = parts[1].strip() if len(parts) > 1 else "без причины"
    user = get_user(target)
    user["money"] -= amount
    save_economy()
    names = get_names([uid, target])
    send(peer_id, f"💸 {mention(uid, names)} выдал штраф {mention(target, names)}: {fmt_num(amount)} 💰\n"
                  f"Причина: {reason}\nБаланс: {fmt_num(user['money'])} 💰")
    _log(peer_id, uid, f"штраф {target}: {amount} ({reason})")


def _norm_prepare(msg, rest, slash, usage):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if rank(peer_id, uid) < GL_DEPUTY_RANK:
        deny(msg, rest, slash, NO_RIGHTS)
        return None, ""
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return None, ""
    err = _check_target(peer_id, uid, target, need_role=True)
    if err:
        send(peer_id, err)
        return None, ""
    return target, tail


def cmd_norm_minus(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    target, tail = _norm_prepare(msg, rest, slash, "ℹ️ Предупреждение за норматив: -норма (ответом / ID / @упоминание) [причина]")
    if target is None:
        return
    n = _norm_get(peer_id, target) + 1
    names = get_names([uid, target])
    who = mention(target, names)
    if n >= NORM_WARNS_LIMIT:
        _norm_set(peer_id, target, 0)
        set_level(peer_id, target, 0)
        send(peer_id, f"⚠ {who}, вам была выдана предупреждение за отсутствие норматива ({NORM_WARNS_LIMIT}/{NORM_WARNS_LIMIT}).\n"
                      f"🚫 {NORM_WARNS_LIMIT}/{NORM_WARNS_LIMIT} — вы сняты с должности.")
        _log(peer_id, uid, f"-норма {target}: {NORM_WARNS_LIMIT}/{NORM_WARNS_LIMIT}, снят с должности")
        return
    _norm_set(peer_id, target, n)
    extra = f"\nПричина: {tail}" if tail else ""
    send(peer_id, f"⚠ {who}, вам была выдана предупреждение за отсутствие норматива ({n}/{NORM_WARNS_LIMIT}).\n"
                  f"Чтобы снять предупреждение, необходимо сделать перенорму.{extra}")
    _log(peer_id, uid, f"-норма {target}: {n}/{NORM_WARNS_LIMIT}")


def cmd_norm_plus(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    target, _ = _norm_prepare(msg, rest, slash, "ℹ️ Норматив выполнен: +норма (ответом / ID / @упоминание)")
    if target is None:
        return
    get_user(target)["money"] += NORM_REWARD
    save_economy()
    names = get_names([target])
    send(peer_id, f"✅ {mention(target, names)} выполнил(а) норматив: +{fmt_num(NORM_REWARD)} 💰")
    _log(peer_id, uid, f"+норма {target}: {NORM_REWARD}")


def cmd_renorm(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    target, _ = _norm_prepare(msg, rest, slash, "ℹ️ Перенорма: +перенорма (ответом / ID / @упоминание)")
    if target is None:
        return
    n = _norm_get(peer_id, target)
    names = get_names([target])
    if n <= 0:
        send(peer_id, f"ℹ️ У {mention(target, names)} нет предупреждений за норматив.")
        return
    _norm_set(peer_id, target, n - 1)
    get_user(target)["money"] += RENORM_REWARD
    save_economy()
    send(peer_id, f"✅ {mention(target, names)} сделал(а) перенорму: предупреждение снято ({n - 1}/{NORM_WARNS_LIMIT}), "
                  f"+{fmt_num(RENORM_REWARD)} 💰")
    _log(peer_id, uid, f"+перенорма {target}: {RENORM_REWARD}")


def cmd_gl_deputy(msg, rest, slash):
    """«права гл (ответом / ID)» и «права гл снять ID» — только Владелец (псевдоним в handlers.py)."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if uid != OWNER_ID:
        deny(msg, rest, slash, "⛔ Назначать «Гл.Следящий Зам» может только Владелец.")
        return
    words = rest.split()
    while words and words[0].lower().strip(".") in ("зам", "следящий", "чата", "гл"):
        words = words[1:]
    remove = any(w.lower() in ("снять", "убрать", "0", "-") for w in words[:1] + words[-1:])
    if remove:
        words = [w for w in words if w.lower() not in ("снять", "убрать", "0", "-")]
    target, _ = parse_target(msg, " ".join(words))
    if target is None:
        no_target(msg, rest, slash, "ℹ️ Назначить: права гл (ответом / ID). Снять: права гл снять ID")
        return
    if target <= 0 or target == OWNER_ID:
        send(peer_id, "⛔ Этому пользователю роль выдать нельзя.")
        return
    names = get_names([target])
    if remove:
        if not is_gl_deputy(peer_id, target):
            send(peer_id, "ℹ️ Этот пользователь не Гл.Следящий Зам.")
            return
        set_level(peer_id, target, 0)
        send(peer_id, f"✅ {mention(target, names)} больше не Гл.Следящий Зам.")
        return
    set_level(peer_id, target, GL_DEPUTY_LEVEL)
    send(peer_id, f"✅ {mention(target, names)} назначен(а) на должность «Гл.Следящий Зам».")
