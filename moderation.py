# -*- coding: utf-8 -*-
"""Модерация: мут, кик, бан, права, варны, тишина, удаление сообщений, заморозка игрока."""
import re
import time

from config import (
    err_text, FREEZE_FOREVER, has_perk, MAX_DELETE_AT_ONCE, MAX_MUTE_SECONDS, MAX_TIMEOUT_MINUTES,
    MIN_LEVEL_TO_DELETE, MIN_LEVEL_TO_FREEZE, MIN_LEVEL_TO_GRANT, MIN_LEVEL_TO_KICK,
    MIN_LEVEL_TO_MUTE, MIN_LEVEL_TO_TIMEOUT, MIN_LEVEL_TO_UNWARN, MIN_LEVEL_TO_WARN, OWNER_ID,
    REPORT_STAFF_TITLE, ROLES, TIME_UNITS, vk, WARNS_LIMIT,
)
from database import (
    get_level, get_user, get_warns, mute_user, punish, save_punish, set_level, unmute_user,
)
from helpers import (
    check_punish_target, delete_message, deny, extract_target, fmt_duration, fmt_time,
    get_names, kick_from_chat, LINK_RE, mention, outranks, parse_target, send,
)
from config import MENTION_RE
from extras import appeal_keyboard
from logs import log_action
from referral import check_referral_join
from reports_owner import report_staff_rights


# ---------- Мут ----------
MUTE_USAGE = ("ℹ️ Использование: мут МИНУТЫ — ответом на сообщение участника\n"
              "Или: мут ID МИНУТЫ / мут @упоминание МИНУТЫ\n"
              "Пример: мут 30 (можно также 2ч, 1д)")

def cmd_mute(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
    if level < MIN_LEVEL_TO_MUTE:
        deny(msg, rest, slash, f"⛔ Выдавать мут могут {ROLES[MIN_LEVEL_TO_MUTE]} и выше.")
        return

    target, tail = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, MUTE_USAGE)
        return

    m = re.search(r"(\d+)\s*([a-zа-яё]*)", tail, re.IGNORECASE)
    if not m:
        send(peer_id, "⚠ Не указано время мута.\n\n" + MUTE_USAGE)
        return
    seconds = int(m.group(1)) * TIME_UNITS.get(m.group(2)[:1].lower(), 60)
    if seconds <= 0:
        send(peer_id, "⚠ Время мута должно быть больше нуля.")
        return
    if seconds > MAX_MUTE_SECONDS:
        send(peer_id, f"⚠ Максимальный срок мута — {fmt_duration(MAX_MUTE_SECONDS)}.")
        return

    err = check_punish_target(peer_id, actor, level, target)
    if err:
        send(peer_id, err)
        return

    until = mute_user(peer_id, target, seconds)
    log_action(peer_id, actor, f"мут {target} на {fmt_duration(seconds)}")
    names = get_names([target, actor])
    send(peer_id, f"🔇 {mention(target, names)} получил мут на {fmt_duration(seconds)} "
                  f"(до {fmt_time(until)}).\nМодератор: {mention(actor, names)}\n"
                  "Все его сообщения будут удаляться.", appeal_keyboard(target))

def cmd_unmute(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_MUTE:
        deny(msg, rest, slash, f"⛔ Снимать мут могут {ROLES[MIN_LEVEL_TO_MUTE]} и выше.")
        return

    target, _ = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ️ Использование: размут — ответом на сообщение, либо размут ID / @упоминание")
        return

    names = get_names([target])
    if unmute_user(peer_id, target):
        log_action(peer_id, actor, f"снял мут с {target}")
        send(peer_id, f"🔊 Мут снят с {mention(target, names)}.")
    else:
        send(peer_id, f"⚠ {mention(target, names)} сейчас не в муте.")

# ---------- Кик / бан ----------
def punish_cmd(msg, rest, slash, ban):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
    word = "бан" if ban else "кик"

    if level < MIN_LEVEL_TO_KICK:
        deny(msg, rest, slash, f"⛔ Команда «{word}» доступна: {ROLES[MIN_LEVEL_TO_KICK]} и выше.")
        return

    target, reason = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, f"ℹ️ Использование: {word} — ответом на сообщение [причина], "
                          f"либо {word} ID / @упоминание [причина]\n"
                          f"Пример: {word} 123456789 спам")
        return

    err = check_punish_target(peer_id, actor, level, target)
    if err:
        send(peer_id, err)
        return

    reason = reason[:200] or "не указана"
    names = get_names([target, actor])
    who, admin = mention(target, names), mention(actor, names)

    if ban:
        bans = punish["bans"].setdefault(str(peer_id), {})
        if str(target) in bans:
            send(peer_id, f"⚠ {who} уже в бане.")
            return
        bans[str(target)] = {"by": actor, "reason": reason, "t": int(time.time())}
        save_punish()

    try:
        kick_from_chat(peer_id, target)
        kicked = True
    except Exception as e:
        print(f"Не удалось исключить {target}: {err_text(e)}")
        kicked = False

    log_action(peer_id, actor, f"{word} {target}: {reason}")

    if ban:
        text = f"🚫 {who} заблокирован навсегда."
        if not kicked:
            text += ("\n⚠ Исключить сейчас не удалось (его нет в беседе или у бота нет прав), "
                     "но при входе он будет исключён автоматически.")
    else:
        if not kicked:
            send(peer_id, "❌ Не удалось исключить. Бот должен быть администратором беседы, "
                          "а исключаемый — участником (не админом).")
            return
        text = f"👢 {who} исключён из беседы."
    send(peer_id, f"{text}\nПричина: {reason}\nМодератор: {admin}", appeal_keyboard(target))

def cmd_kick(msg, rest, slash):
    punish_cmd(msg, rest, slash, ban=False)

def cmd_ban(msg, rest, slash):
    punish_cmd(msg, rest, slash, ban=True)
def cmd_unban(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_KICK:
        deny(msg, rest, slash, f"⛔ Команда «разбан» доступна: {ROLES[MIN_LEVEL_TO_KICK]} и выше.")
        return

    target, _ = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ️ Использование: разбан ID / @упоминание")
        return

    names = get_names([target])
    removed = punish["bans"].get(str(peer_id), {}).pop(str(target), None)
    if removed is None:
        send(peer_id, f"⚠ {mention(target, names)} не в бане.")
        return
    save_punish()
    log_action(peer_id, actor, f"разбан {target}")
    send(peer_id, f"✅ {mention(target, names)} разблокирован. Теперь его можно снова пригласить.")

def handle_action(msg, action):
    """Если забаненный вернулся в беседу (пригласили или по ссылке) — исключаем снова."""
    if action.get("type") not in ("chat_invite_user", "chat_invite_user_by_link", "chat_invite_user_by_message_request"):
        return
    peer_id = msg["peer_id"]
    uid = action.get("member_id") or msg["from_id"]
    if uid <= 0:
        return
    ban = punish["bans"].get(str(peer_id), {}).get(str(uid))
    if not ban:
        check_referral_join(peer_id, uid)       # зашёл новый участник — возможно, по реф-ссылке
        return
    try:
        kick_from_chat(peer_id, uid)
        names = get_names([uid])
        send(peer_id, f"🚫 {mention(uid, names)} в бане этой беседы — исключён.\n"
                      f"Причина: {ban['reason']}")
    except Exception as e:
        print(f"Не удалось исключить забаненного {uid}: {err_text(e)}")

# ---------- «удалить» ----------
def cmd_delete(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)

    if level < MIN_LEVEL_TO_DELETE:
        send(peer_id, "⛔ Удалять сообщения могут модераторы и выше.")
        return

    reply = msg.get("reply_message")
    if reply:
        candidates = [reply]
    else:
        # Пересланные берём только из этой же беседы, чтобы не удалить чужое по совпавшему номеру
        fwd = msg.get("fwd_messages", [])[:MAX_DELETE_AT_ONCE]
        candidates = [m for m in fwd if m.get("peer_id") == peer_id]
    candidates = [m for m in candidates if m.get("conversation_message_id")]

    if not candidates:
        send(peer_id, "⚠ Ответьте командой «удалить» на сообщение, которое нужно удалить.")
        return

    cmids = []
    blocked = 0
    for m in candidates:
        author = m.get("from_id", 0)
        if author != actor and not outranks(peer_id, actor, author, level):
            blocked += 1
            continue
        cmids.append(m["conversation_message_id"])

    if not cmids:
        send(peer_id, "⛔ Нельзя удалять сообщения пользователей с таким же или более высоким уровнем.")
        return

    try:
        vk.messages.delete(peer_id=peer_id, cmids=",".join(map(str, cmids)), delete_for_all=1)
    except Exception as e:
        print(f"Ошибка удаления: {err_text(e)}")
        send(peer_id, "❌ Не удалось удалить сообщение. Бот должен быть администратором беседы, "
                      "а сообщение — не старше 24 часов.")
        return

    log_action(peer_id, actor, f"удалил сообщения: {cmids}")
    # Убираем и саму команду, чтобы не засорять чат
    delete_message(peer_id, msg["conversation_message_id"])

    if blocked:
        send(peer_id, f"⚠ Сообщений не удалено: {blocked} (у авторов уровень не ниже вашего).")

# ---------- «права» ----------
def rights_usage():
    roles = "\n".join(f"{lvl} — {name}" for lvl, name in ROLES.items() if lvl < 5)
    return (
        "ℹ️ Использование команды:\n"
        "права 1 ID — выдать роль по ID\n"
        "права 2 @упоминание — выдать роль по упоминанию\n"
        "права 2 (ответом на сообщение) — выдать роль автору сообщения\n"
        "права 0 ID — снять роль\n"
        f"права следящий ID — должность «{REPORT_STAFF_TITLE}» (только владелец)\n\n"
        f"Роли:\n{roles}"
    )

def cmd_rights(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]

    m_staff = re.match(r"(следящ\w*)\s*(.*)", rest.strip(), re.I | re.S)   # «права следящий …»
    if m_staff:
        if actor != OWNER_ID:
            send(peer_id, f"⛔ Должность «{REPORT_STAFF_TITLE}» выдаёт только владелец.")
            return
        send(peer_id, report_staff_rights(msg, m_staff.group(2)))
        return

    m = re.match(r"(\d+)\s*(.*)", rest, re.S)
    mt = re.match(r"(\S+)\s+(\d)\s*$", rest.strip())      # «права https://vk.ru/name 1» / «права @имя 2»
    if mt and (LINK_RE.match(mt.group(1)) or MENTION_RE.match(mt.group(1))):
        level, target_text = int(mt.group(2)), mt.group(1)
    elif m:
        level, target_text = int(m.group(1)), m.group(2)
    else:
        # Без слеша молчим, чтобы не реагировать на фразы вроде «права водителя…»
        if slash:
            send(peer_id, rights_usage())
        return

    actor_level = get_level(peer_id, actor)
    if actor_level < MIN_LEVEL_TO_GRANT:
        send(peer_id, "⛔ У вас недостаточно прав для этой команды.")
        return

    if level < 0 or level > 4:
        send(peer_id, "⚠ Доступные уровни: 0 (снять) и 1–4.\n\n" + rights_usage())
        return

    target = extract_target(msg, target_text)
    if target is None or target <= 0:
        send(peer_id, "⚠ Укажите пользователя: ID, упоминание или ответьте на его сообщение.")
        return

    if target == OWNER_ID:
        send(peer_id, "⛔ Права владельца менять нельзя.")
        return
    if target == actor:
        send(peer_id, "⛔ Нельзя менять права самому себе.")
        return
    if not outranks(peer_id, actor, target, actor_level):
        send(peer_id, "⛔ Нельзя менять права пользователя с таким же или более высоким уровнем.")
        return
    if level >= actor_level:
        send(peer_id, "⛔ Вы можете выдавать только уровни ниже своего.")
        return

    set_level(peer_id, target, level)
    log_action(peer_id, actor, f"права {target}: уровень {level}")
    names = get_names([target])
    who = mention(target, names)
    if level == 0:
        send(peer_id, f"✅ У {who} сняты все права.")
    else:
        send(peer_id, f"✅ {who} назначен: {ROLES[level]}.")

# ---------- Предупреждения (варны) ----------
def cmd_warn(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
    if level < MIN_LEVEL_TO_WARN:
        deny(msg, rest, slash, f"⛔ Выдавать предупреждения могут {ROLES[MIN_LEVEL_TO_WARN]} и выше.")
        return

    target, reason = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ️ Использование: варн [причина] — ответом на сообщение участника\n"
                          "Или: варн ID [причина]\n"
                          f"{WARNS_LIMIT}/{WARNS_LIMIT} предупреждений — кик из беседы.")
        return
    err = check_punish_target(peer_id, actor, level, target)
    if err:
        send(peer_id, err)
        return
    if actor != OWNER_ID and has_perk(get_user(target), "warn_immune"):
        send(peer_id, "🛡 У этого игрока иммунитет от варна.")
        return
    reason = reason[:200] or "не указана"
    warns = punish["warns"].setdefault(str(peer_id), {}).setdefault(str(target), [])
    warns.append({"by": actor, "reason": reason, "t": int(time.time())})
    save_punish()
    count = len(warns)
    names = get_names([target, actor])
    text = (f"⚠ {mention(target, names)} получил предупреждение ({count}/{WARNS_LIMIT}).\n"
            f"Причина: {reason}\nМодератор: {mention(actor, names)}")

    if count >= WARNS_LIMIT:
        try:
            kick_from_chat(peer_id, target)
            del punish["warns"][str(peer_id)][str(target)]
            save_punish()
            text += f"\n\n👢 Набрано {WARNS_LIMIT}/{WARNS_LIMIT} предупреждений — исключён из беседы."
        except Exception as e:
            print(f"Не удалось исключить за варны {target}: {err_text(e)}")
            text += "\n\n❌ Лимит достигнут, но исключить не удалось (бот должен быть админом беседы)."
    log_action(peer_id, actor, f"варн {target} ({count}/{WARNS_LIMIT}): {reason}")
    send(peer_id, text, appeal_keyboard(target))

def cmd_unwarn(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_UNWARN:
        deny(msg, rest, slash, f"⛔ Снимать предупреждения могут {ROLES[MIN_LEVEL_TO_UNWARN]} и выше.")
        return

    target, _ = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ️ Использование: снять варн — ответом на сообщение участника, либо снять варн ID")
        return

    names = get_names([target])
    warns = get_warns(peer_id, target)
    if not warns:
        send(peer_id, f"⚠ У {mention(target, names)} нет предупреждений.")
        return
    warns.pop()
    if not warns:
        del punish["warns"][str(peer_id)][str(target)]
    save_punish()
    log_action(peer_id, actor, f"снял варн с {target}")
    send(peer_id, f"✅ Предупреждение снято с {mention(target, names)}. "
                  f"Осталось: {len(warns)}/{WARNS_LIMIT}.")

# ---------- Режим тишины (timeout) ----------
def timeout_active(peer_id):
    key = str(peer_id)
    if key not in punish["timeouts"]:
        return False
    until = punish["timeouts"][key]
    if until and until <= time.time():
        del punish["timeouts"][key]
        save_punish()
        try:
            send(peer_id, "🔔 Режим тишины закончился. Писать можно всем.")
        except Exception as e:
            print(f"Ошибка уведомления о конце тишины: {err_text(e)}")
        return False
    return True

def cmd_timeout(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_TIMEOUT:
        deny(msg, rest, slash, f"⛔ Режим тишины могут включать {ROLES[MIN_LEVEL_TO_TIMEOUT]} и выше.")
        return

    if timeout_active(peer_id):
        del punish["timeouts"][str(peer_id)]
        save_punish()
        log_action(peer_id, actor, "выключил режим тишины")
        send(peer_id, "🔔 Режим тишины выключен. Писать можно всем.")
        return

    m = re.search(r"\d+", rest)
    minutes = int(m.group()) if m else 0
    if minutes > MAX_TIMEOUT_MINUTES:
        send(peer_id, f"⚠ Максимальный срок режима тишины — {MAX_TIMEOUT_MINUTES} мин (сутки).")
        return
    punish["timeouts"][str(peer_id)] = time.time() + minutes * 60 if minutes else 0
    save_punish()
    log_action(peer_id, actor, f"включил режим тишины ({minutes or 'без срока'})")
    period = f" на {minutes} мин" if minutes else ""
    send(peer_id, f"🤫 Режим тишины включён{period}.\n"
                  "Писать могут только модераторы, сообщения остальных удаляются.\n"
                  "Выключить: timeout")

# ---------- Заморозка игрока (Тех специалист) ----------
def cmd_freeze(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    level = get_level(peer_id, actor)
    if level < MIN_LEVEL_TO_FREEZE:
        deny(msg, rest, slash, f"⛔ Замораживать могут {ROLES[MIN_LEVEL_TO_FREEZE]} и выше.")
        return

    usage = ("ℹ️ Использование: заморозить — ответом на сообщение участника\n"
             "Или: заморозить ID [минуты]\nПример: заморозить 60 (на час). Без числа — до «разморозить».")
    target, tail = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, usage)
        return
    err = check_punish_target(peer_id, actor, level, target)
    if err:
        send(peer_id, err)
        return

    m = re.search(r"\d+", tail)
    minutes = int(m.group()) if m else 0
    now = time.time()
    punish["freezes"][str(target)] = now + (minutes * 60 if minutes else FREEZE_FOREVER)
    save_punish()
    log_action(peer_id, actor, f"заморозил {target} ({minutes or 'без срока'})")
    names = get_names([target, actor])
    period = f"на {fmt_duration(minutes * 60)}" if minutes else "без срока"
    send(peer_id, f"🧊 {mention(target, names)} заморожен {period}.\n"
                  "Он может только общаться в чате: все команды и кнопки бота недоступны.\n"
                  f"Модератор: {mention(actor, names)}", appeal_keyboard(target))

def cmd_unfreeze(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]
    if get_level(peer_id, actor) < MIN_LEVEL_TO_FREEZE:
        deny(msg, rest, slash, f"⛔ Размораживать могут {ROLES[MIN_LEVEL_TO_FREEZE]} и выше.")
        return
    target, _ = parse_target(msg, rest)
    if target is None:
        if slash or not rest.strip():
            send(peer_id, "ℹ️ Использование: разморозить — ответом на сообщение, либо разморозить ID")
        return
    names = get_names([target])
    if punish["freezes"].pop(str(target), None) is None:
        send(peer_id, f"⚠ {mention(target, names)} не заморожен.")
        return
    save_punish()
    log_action(peer_id, actor, f"разморозил {target}")
    send(peer_id, f"🔥 {mention(target, names)} разморожен — команды снова доступны.")
