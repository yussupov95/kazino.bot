# -*- coding: utf-8 -*-
"""Репорты, часть 3: назначение следящих и команды владельца по репортам."""
import re
import time

from backup import owner_dm_command
from bitcoin import owner_btc_command
from business import biz_open, cmd_income
from config import err_text, GROUP_ID, OWNER_ID, REPORT_STAFF_TITLE, vk
from database import economy, freeze_left, save_economy
from donate import cmd_donate, dm_is_free, donate_receipt
from extras import appeal_dm, owner_post_command
from helpers import (
    active_dialog_of, answer_event, freeze_text, get_names, mention, msg_photos, send,
    target_from_message, target_from_text,
)
from logs import log_action
from owner_cmds import owner_extra_commands, owner_help_command
from referral import handle_ref_start
from reports_actions import (
    owner_reward_input, rating_text, reassign_dialogs, report_action, report_text_command,
)
from reports_dialog import (
    is_report_staff, notify_report_user, refill_offers, _REPORT_CLOSE_WORDS, staff_dm,
    staff_dm_keyboard, staff_help_text, user_dm, user_dm_keyboard,
)
from shop import shop_menu_page


# ---------- назначение следящих и команды владельца ----------
def target_from_link(text):
    """vk.com/id123 или vk.com/короткое_имя → id пользователя."""
    m = re.search(r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/([A-Za-z0-9_.]+)", text)
    if not m:
        return None
    name = m.group(1)
    mid = re.fullmatch(r"id(\d+)", name)
    if mid:
        return int(mid.group(1))
    try:
        res = vk.utils.resolveScreenName(screen_name=name)
        if res and res.get("type") == "user":
            return int(res["object_id"])
    except Exception as e:
        print(f"Не удалось разобрать ссылку {name}: {err_text(e)}")
    return None

def owner_target(msg, text):
    return target_from_text(text) or target_from_link(text) or target_from_message(msg)

def staff_rights_usage():
    return (f"ℹ️ Должность «{REPORT_STAFF_TITLE}» (отвечает на репорты игроков в ЛС бота):\n"
            "права следящий ID — выдать (можно @упоминание или ответом на сообщение)\n"
            "права следящий снять ID — снять\n"
            "следящие (в ЛС боту) — список")

def set_report_staff(target, on, actor, peer_id):
    names = get_names([target])
    who = mention(target, names)
    staff = economy["report_staff"]
    if on:
        if target == OWNER_ID:
            return "ℹ️ Вы владелец — репорты и так доступны вам."
        if str(target) in staff:
            return f"ℹ️ {who} уже назначен: {REPORT_STAFF_TITLE}."
        staff[str(target)] = int(time.time())
        save_economy()
        log_action(peer_id, actor, f"следящий за репортами: назначен {target}")
        res = f"✅ {who} назначен: {REPORT_STAFF_TITLE}."
        try:
            send(target, "🎉 Вам выдана должность.\n\n" + staff_help_text(), staff_dm_keyboard())
        except Exception as e:
            print(f"Не удалось написать новому следящему {target}: {err_text(e)}")
            res += ("\n⚠ Не удалось написать ему в ЛС. Пусть откроет диалог с ботом и отправит любое сообщение: "
                    f"https://vk.me/club{GROUP_ID}")
        refill_offers()                           # неразобранные вопросы — новому следящему
        return res
    if str(target) not in staff:
        return f"ℹ️ У {who} нет должности «{REPORT_STAFF_TITLE}»."
    del staff[str(target)]
    save_economy()
    log_action(peer_id, actor, f"следящий за репортами: снят {target}")
    res = f"✅ У {who} снята должность «{REPORT_STAFF_TITLE}»."
    try:
        send(target, f"ℹ️ Вы больше не «{REPORT_STAFF_TITLE}».")
    except Exception:
        pass
    moved = reassign_dialogs(target)
    if moved:
        res += f"\nОткрытых диалогов передано дальше: {moved}."
    return res

def report_staff_rights(msg, tail):
    """«права следящий …» (владелец): tail — всё после слова «следящий». Возвращает текст ответа."""
    tail = tail.strip()
    off = False
    m = re.match(r"(" + "|".join(map(re.escape, _REPORT_CLOSE_WORDS)) + r")(?:\s+|$)(.*)", tail, re.I | re.S)
    if m:
        off, tail = True, m.group(2)
    target = owner_target(msg, tail)
    if target is None or target <= 0:
        return staff_rights_usage()
    return set_report_staff(target, not off, msg["from_id"], msg["peer_id"])

def owner_unban_report(peer_id, msg, tail):
    """«разбан ID» в ЛС: снять блокировку репортов; «разбан» без ID — список заблокированных."""
    blocked = [int(u) for u in economy["report_blocked"]]
    target = owner_target(msg, tail)
    if target is None:
        if not blocked:
            send(peer_id, "✅ В репортах никто не заблокирован.")
            return
        shown = blocked[:100]
        names = get_names(shown)
        lines = [f"• [id{u}|{names.get(u, f'id{u}')}] (id{u})" for u in shown]
        more = f"\n…и ещё {len(blocked) - len(shown)}" if len(blocked) > len(shown) else ""
        send(peer_id, f"🚫 Заблокированы в репортах ({len(blocked)}):\n" + "\n".join(lines) + more +
             "\n\nСнять блокировку: разбан ID")
        return
    names = get_names([target])
    who = f"[id{target}|{names.get(target, f'id{target}')}]"
    if not economy["report_blocked"].pop(str(target), None):
        send(peer_id, f"ℹ️ {who} не заблокирован в репортах.")
        return
    save_economy()
    log_action(peer_id, OWNER_ID, f"разбан в репортах {target}")
    notify_report_user(target, "✅ Вам снова доступна отправка репортов. Нажмите «Репорт».", user_dm_keyboard())
    send(peer_id, f"✅ {who} разблокирован в репортах.")

def owner_staff_list(peer_id):
    ids = [int(u) for u in economy["report_staff"]]
    if not ids:
        send(peer_id, f"👥 {REPORT_STAFF_TITLE}: пока никого.\nНазначить: права следящий ID")
        return
    names = get_names(ids)
    busy = {}
    for r, rep in economy["reports"].items():
        if rep.get("status") == "open" and rep.get("staff"):
            busy[rep["staff"]] = r
    lines = [f"• [id{u}|{names.get(u, f'id{u}')}] (id{u}) — " +
             (f"занят: репорт #{busy[u]}" if u in busy else "свободен") + f" · {rating_text(u)}" for u in ids]
    waiting = sum(1 for rep in economy["reports"].values() if rep.get("status") == "queue")
    tail = f"\n\n⏳ Вопросов ждёт принятия: {waiting}" if waiting else ""
    send(peer_id, f"👥 {REPORT_STAFF_TITLE} ({len(ids)}):\n" + "\n".join(lines) + tail +
         "\n\nНазначить: права следящий ID\nСнять: права следящий снять ID")

def owner_report_command(msg, text):
    """Команды владельца про репорты в ЛС: разбан, следящие, права следящий. True — обработано."""
    peer_id = msg["peer_id"]
    word, _, tail = text.strip().partition(" ")
    w = word.lower().replace("ё", "е").strip(" .!?")
    tail = tail.strip()
    if w in ("разбан", "unban"):
        owner_unban_report(peer_id, msg, tail)
        return True
    if w in ("следящие", "staff"):
        owner_staff_list(peer_id)
        return True
    if w in ("права", "rights"):
        m = re.match(r"(следящ\w*)\s*(.*)", tail, re.I | re.S)
        if not m:
            return False
        send(peer_id, report_staff_rights(msg, m.group(2)))
        return True
    return False

OWNER_DM_WORDS = ("файл", "file", "бэкап", "backup", "восстановить", "restore")

def owner_open_dialogs():
    return any(rep.get("status") == "open" and rep.get("staff") == OWNER_ID for rep in economy["reports"].values())

def handle_dm(msg):
    """Личные сообщения боту: репорты (игроки ↔ следящие ↔ владелец)."""
    uid = msg["from_id"]
    if uid <= 0:
        return
    peer_id = msg["peer_id"]
    if not msg.get("ref"):                            # VK не передал ref (диалог уже был) — берём код из текста
        raw = (msg.get("text") or "").strip()
        code = re.search(r"[?&]ref=(r\d+_\d+)", raw) or re.fullmatch(r"(r\d+_\d+)", raw)
        if code:
            msg = dict(msg, ref=code.group(1))
    if msg.get("ref") and handle_ref_start(msg):      # перешли по реф-ссылке
        return
    text = (msg.get("text") or "").strip()
    low_d = text.lower().strip(" .!?")
    if appeal_dm(msg, text):                          # «апелляция» (игрок) и настройка ссылок (владелец)
        return
    if dm_is_free(uid) and (low_d in ("донат", "donate") or low_d.startswith(("донат ", "donate "))):
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}.")
        else:
            cmd_donate({"peer_id": peer_id, "from_id": uid}, text.strip().partition(" ")[2].strip(), True)
        return
    if uid != OWNER_ID and msg_photos(msg) and dm_is_free(uid) and donate_receipt(msg):      # скриншот чека
        return
    if (text.lower().strip(" .!?") in ("магазин", "shop") and not active_dialog_of(uid)
            and not any(r.get("status") == "open" and r.get("staff") == uid for r in economy["reports"].values())
            and not (uid == OWNER_ID and economy.get("report_wait"))):
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}.")
        else:
            menu_text, menu_kb = shop_menu_page(uid, "shop")
            send(peer_id, menu_text, menu_kb)
        return
    low_dm = text.lower().strip(" .!?")
    if (low_dm in ("бизнес", "бизнесы", "business", "доход", "income") and not active_dialog_of(uid)
            and not any(r.get("status") == "open" and r.get("staff") == uid for r in economy["reports"].values())
            and not (uid == OWNER_ID and economy.get("report_wait"))):
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}.")
        elif low_dm in ("доход", "income"):
            cmd_income({"peer_id": peer_id, "from_id": uid}, "", False)
        else:
            biz_open(peer_id, uid)
        return
    if (uid == OWNER_ID or is_report_staff(uid)) and report_text_command(msg, text):
        return                                      # «принять 12», «награда 12 5кк», «вернуть 12 5кк»… — если кнопки не работают
    if uid == OWNER_ID:
        if owner_help_command(msg, text):           # «хелп-команды»: все команды владельца
            return
        if owner_post_command(msg, text):           # «пост ТЕКСТ»: запись в сообществе (лайки → награда)
            return
        if owner_btc_command(msg, text):            # секрет: курс биткоина
            return
        if owner_extra_commands(msg, text):         # «промокод …», «деньги …», «дрон …» прямо в ЛС
            return
        if owner_report_command(msg, text):
            return
        wait = economy.get("report_wait")
        if text and wait and wait.get("mode") == "reply" and owner_reward_input(msg, text):
            return                                  # ответ игроку (текст «восстановили баг» — не команда)
        has_doc = any(a.get("type") == "doc" for a in msg.get("attachments") or [])
        if ((text or msg_photos(msg)) and not economy.get("report_wait") and owner_open_dialogs() and not has_doc
                and text.lower().strip(" .!?") not in OWNER_DM_WORDS):
            staff_dm(msg, text)                     # владелец принял вопрос — переписывается как следящий
            return
        if owner_dm_command(msg, text):
            return
        if text and economy.get("report_wait") and owner_reward_input(msg, text):
            return
        send(peer_id, "✅ Личный диалог открыт: сюда приходят репорты, логи и копии базы.\n"
                      "Все ваши команды — «хелп-команды». Команда «файл» — прислать копию базы. Восстановить: пришлите файл копии и напишите «восстановить».\n"
                      "Репорты: «разбан ID» — снять блокировку (без ID — список), «следящие» — список, "
                      "«права следящий ID» — назначить.")
        return
    if is_report_staff(uid):
        staff_dm(msg, text)
        return
    user_dm(msg, text)

def handle_report_callback(ev, p):
    note = None
    try:
        if ev["user_id"] != OWNER_ID:
            note = "Это действие доступно только владельцу."
        else:
            note = report_action(ev, p)
    finally:
        answer_event(ev, note)
