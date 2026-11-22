# -*- coding: utf-8 -*-
"""Чеки: Зам чата и выше пишет «чек @игрок СУММА» → владельцу в ЛС приходит карточка с подписью
и кнопками «Подтвердить / Отказать». Деньги игрок получает только после подтверждения.
Если кнопки не нажимаются — владелец может написать боту в ЛС: «чек подтвердить 7» / «чек отказать 7»."""
import json
import os
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from config import (
    _asset, CHAT_OFFSET, DEPUTY_LEVEL, err_text, _find, GL_DEPUTY_LEVEL, _here, MIN_LEVEL_TO_DEPUTY,
    OWNER_ID, ROLES, vk_upload,
)
from database import economy, get_user, is_gl_deputy, raw_level, save_economy
from helpers import (
    answer_event, deny, edit_message, fmt_duration, fmt_num, get_names, mention, no_target,
    parse_amount, parse_target, send, send_dm,
)
from logs import log_action

WORDS = ("чек", "check")
SIGN_FILE = "check_sign.jpg"          # фото подписи: кладите рядом с ботом (или в assets/)
CHECK_ROLES = {MIN_LEVEL_TO_DEPUTY, 5, DEPUTY_LEVEL, GL_DEPUTY_LEVEL}   # Тех специалист, Владелец, Зам чата, Гл.Следящий Зам
CHECK_MAX_PENDING = 5                 # сколько неподтверждённых чеков может висеть у одного зама
CHECK_TTL = 24 * 3600                 # чек, который владелец не рассмотрел за сутки, аннулируется
_MAX_BALANCE = 9 * 10 ** 18           # предел числа в базе
_FILE = _here("checks.json")
_data = {"next": 1, "items": {}}      # items: {"номер": {...}} — переживает перезапуск


# ---------- Хранилище ----------
def _load():
    try:
        with open(_FILE, encoding="utf-8") as f:
            loaded = json.load(f)
        _data["next"] = int(loaded.get("next", 1))
        _data["items"] = dict(loaded.get("items", {}))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Не удалось прочитать {_FILE}: {err_text(e)}")

def _save():
    now = time.time()
    for k in [k for k, c in _data["items"].items()          # решённые чеки старше недели забываем
              if c["status"] != "wait" and now - c.get("done", c["t"]) > 7 * 86400]:
        del _data["items"][k]
    try:
        with open(_FILE, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False)
    except Exception as e:
        print(f"Не удалось сохранить {_FILE}: {err_text(e)}")


# ---------- Подпись ----------
def sign_attachment():
    """Фото подписи в VK (загружается один раз и запоминается). None — файла нет или загрузка не удалась."""
    path = next((p for p in (_find(SIGN_FILE), _asset(SIGN_FILE)) if os.path.exists(p)), None)
    if not path:
        return None
    key = f"check_sign_{int(os.path.getmtime(path))}"
    att = economy["media"].get(key)
    if att:
        return att
    try:
        photo = vk_upload.photo_messages(path)[0]
    except Exception as e:
        print(f"Не удалось загрузить подпись {path}: {err_text(e)}")
        return None
    att = f"photo{photo['owner_id']}_{photo['id']}"
    economy["media"][key] = att
    save_economy()
    return att


# ---------- Кто может выписывать ----------
def _can_issue(peer_id, uid):
    """Зам чата и выше: Зам чата, Тех специалист, Гл.Следящий Зам, Владелец."""
    if uid == OWNER_ID:
        return True
    try:
        return bool(is_gl_deputy(peer_id, uid)) or raw_level(peer_id, uid) in CHECK_ROLES
    except Exception as e:
        print(f"Чек: не удалось узнать роль {uid}: {err_text(e)}")
        return False

def _role_name(peer_id, uid):
    if uid == OWNER_ID:
        return ROLES[5]
    try:
        if is_gl_deputy(peer_id, uid):
            return ROLES[GL_DEPUTY_LEVEL]
        return ROLES.get(raw_level(peer_id, uid), "?")
    except Exception:
        return "?"

def _pending(uid=None):
    now = time.time()
    return [c for c in _data["items"].values()
            if c["status"] == "wait" and now - c["t"] <= CHECK_TTL and (uid is None or c["by"] == uid)]


# ---------- Команда в беседе ----------
def cmd_check(msg, rest, slash):
    """«чек @игрок СУММА [причина]» или ответом на сообщение: «чек СУММА»."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    if uid <= 0:
        return
    if not _can_issue(peer_id, uid):
        deny(msg, rest, slash, "⛔ Чеки выписывает Зам чата и выше.")
        return
    usage = ("ℹ️ Использование: чек @игрок СУММА [причина] — или ответом на сообщение: чек СУММА\n"
             "Чек уходит владельцу на подтверждение, деньги игрок получит после его решения.")
    target, tail = parse_target(msg, rest)
    if target is None:
        no_target(msg, rest, slash, usage)
        return
    parts = tail.split()
    amount = parse_amount(parts[0]) if parts else None
    if amount is None:
        send(peer_id, usage)
        return
    note = " ".join(parts[1:])[:100]
    if target <= 0:
        send(peer_id, "⚠ Сообществу чек выписывать нельзя.")
        return
    if target == uid and uid != OWNER_ID:
        send(peer_id, "⛔ Нельзя выписать чек самому себе.")
        return
    if uid != OWNER_ID and len(_pending(uid)) >= CHECK_MAX_PENDING:
        send(peer_id, f"⏳ У вас уже {CHECK_MAX_PENDING} чеков ждут решения владельца. Дождитесь ответа.")
        return

    cid = _data["next"]
    _data["next"] = cid + 1
    c = {"id": cid, "peer": peer_id, "by": uid, "to": target, "amount": amount, "note": note,
         "t": time.time(), "status": "wait", "dm": None, "dm_text": ""}
    _data["items"][str(cid)] = c
    _save()

    if uid == OWNER_ID:                                   # владельцу разрешение не нужно
        note, line = _approve(c, by_owner=True)
        if not line:
            del _data["items"][str(cid)]
            _save()
            send(peer_id, f"⚠ {note}")
        return

    names = get_names([uid, target])
    text = (f"🧾 Чек №{cid} на подтверждение\n"
            f"Выписал: {names.get(uid, '?')} (vk.com/id{uid}) — {_role_name(peer_id, uid)}\n"
            f"Получатель: {names.get(target, '?')} (vk.com/id{target}, ID {target})\n"
            f"Сумма: {fmt_num(amount)} 💰\n"
            f"Баланс получателя: {fmt_num(get_user(target)['money'])} 💰\n"
            + (f"Причина: {note}\n" if note else "")
            + f"Беседа: peer_id {peer_id}\n"
            f"Время: {time.strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            f"Ответ текстом, если кнопки не работают: «чек подтвердить {cid}» / «чек отказать {cid}»")
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Подтвердить", VkKeyboardColor.POSITIVE, {"cmd": "chk", "a": "ok", "i": cid})
    kb.add_callback_button("❌ Отказать", VkKeyboardColor.NEGATIVE, {"cmd": "chk", "a": "no", "i": cid})
    try:
        c["dm"] = send_dm(OWNER_ID, text, kb.get_keyboard(), attachment=sign_attachment())
    except Exception as e:
        del _data["items"][str(cid)]
        _save()
        print(f"Чек №{cid}: не удалось написать владельцу: {err_text(e)}")
        send(peer_id, "⚠ Не удалось отправить чек владельцу (он не открыл диалог с ботом). Чек отменён.")
        return
    c["dm_text"] = text
    _save()
    send(peer_id, f"🧾 Чек №{cid} отправлен владельцу на подтверждение.\n"
                  f"Получатель: {mention(target, names)} · сумма: {fmt_num(amount)} 💰")


# ---------- Решение владельца ----------
def _announce(c, text, attachment=None):
    try:
        send(c["peer"], text, attachment=attachment)
    except Exception as e:
        print(f"Чек №{c['id']}: не удалось написать в беседу {c['peer']}: {err_text(e)}")

def _strip_card(c, line):
    """Убирает кнопки с карточки у владельца и дописывает итог."""
    if not c.get("dm"):
        return
    try:
        edit_message(OWNER_ID, c["dm"], f"{c['dm_text']}\n\n{line}", attachment=sign_attachment())
    except Exception as e:
        print(f"Чек №{c['id']}: не удалось обновить карточку: {err_text(e)}")

def _approve(c, by_owner=False):
    """Выдаёт деньги и объявляет в беседе. Возвращает (подсказка владельцу, итоговая строка для карточки)."""
    receiver = get_user(c["to"])
    if receiver["money"] + c["amount"] > _MAX_BALANCE:
        return "У получателя баланс переполнится.", None          # чек остаётся в ожидании
    receiver["money"] += c["amount"]
    c["status"], c["done"] = "ok", time.time()
    save_economy()
    _save()
    log_action(c["peer"], c["by"], f"чек №{c['id']}: {c['amount']} → {c['to']} "
                                    f"({'выписал владелец' if by_owner else 'подтвердил владелец'})")
    names = get_names([c["by"], c["to"]])
    text = (f"🧾 Чек №{c['id']} подтверждён\n"
            f"{mention(c['to'], names)} получает {fmt_num(c['amount'])} 💰\n"
            + (f"Причина: {c['note']}\n" if c.get("note") else "")
            + ("" if by_owner else f"Выписал: {mention(c['by'], names)}\n")
            + "✍ Подписано владельцем")
    _announce(c, text, attachment=sign_attachment())
    return f"Чек №{c['id']} подтверждён.", "✅ Подтверждено — деньги выданы."

def _refuse(c):
    c["status"], c["done"] = "no", time.time()
    _save()
    log_action(c["peer"], c["by"], f"чек №{c['id']}: владелец отказал ({c['amount']} → {c['to']})")
    names = get_names([c["by"], c["to"]])
    _announce(c, f"❌ Владелец отказал в чеке №{c['id']}\n"
                 f"{mention(c['to'], names)} · {fmt_num(c['amount'])} 💰 (выписал {mention(c['by'], names)})")
    return f"Чек №{c['id']}: отказано.", "❌ Отказано."

def _decide(cid, approve):
    """Общая логика для кнопок и текстовых команд. Возвращает (подсказка, итоговая строка для карточки или None)."""
    c = _data["items"].get(str(cid))
    if not c:
        return f"Чек №{cid} не найден.", None
    if c["status"] != "wait":
        return f"Чек №{cid} уже обработан.", "Уже обработан."
    if time.time() - c["t"] > CHECK_TTL:
        c["status"], c["done"] = "exp", time.time()
        _save()
        _announce(c, f"⌛ Чек №{cid} аннулирован: владелец не рассмотрел его за {fmt_duration(CHECK_TTL)}.")
        return f"Чек №{cid}: срок вышел.", "⌛ Срок вышел, чек аннулирован."
    note, line = _approve(c) if approve else _refuse(c)
    if line:
        _strip_card(c, line)
    return note, line

def check_callback(ev, p):
    """Кнопки «Подтвердить / Отказать» под карточкой чека (ЛС владельца)."""
    note = None
    try:
        if ev["user_id"] != OWNER_ID:
            note = "Чеки подтверждает только владелец."
            return
        note, _ = _decide(p.get("i"), p.get("a") == "ok")
    except Exception as e:
        print(f"Ошибка чека: {err_text(e)}")
        note = "Ошибка, смотрите консоль бота."
    finally:
        answer_event(ev, note)


# ---------- Запасной вариант: текстом в ЛС владельца ----------
def _pending_text():
    items = sorted(_pending(), key=lambda c: c["id"])
    if not items:
        return "Неподтверждённых чеков нет."
    names = get_names(list({u for c in items for u in (c["by"], c["to"])}))
    return "Ждут решения:\n" + "\n".join(
        f"№{c['id']}: {names.get(c['by'], c['by'])} → {names.get(c['to'], c['to'])}, {fmt_num(c['amount'])} 💰"
        for c in items)

def check_dm_hook(msg):
    """True — сообщение владельца в ЛС было командой по чекам (дальше его обрабатывать не нужно)."""
    if msg.get("from_id") != OWNER_ID or msg.get("peer_id") != OWNER_ID:
        return False
    parts = (msg.get("text") or "").strip().split()
    if not parts or parts[0].lower().lstrip("/") not in WORDS:
        return False
    verb = parts[1].lower() if len(parts) > 1 else ""
    approve = verb in ("подтвердить", "ок", "ok", "да", "yes")
    refuse = verb in ("отказать", "отказ", "нет", "no")
    if not (approve or refuse):
        send(OWNER_ID, "ℹ️ Чеки: «чек подтвердить НОМЕР» · «чек отказать НОМЕР» · «чек список»\n\n" + _pending_text())
        return True
    cid = parts[2] if len(parts) > 2 else None
    if cid is None and len(_pending()) == 1:                # номер не нужен, если ждёт только один чек
        cid = _pending()[0]["id"]
    if cid is None or not str(cid).isdigit():
        send(OWNER_ID, "ℹ️ Укажите номер чека: «чек подтвердить 7».\n\n" + _pending_text())
        return True
    note, _ = _decide(int(cid), approve)
    send(OWNER_ID, ("✅ " if approve else "❌ ") + note)
    return True


# ---------- выполняется при запуске ----------
_load()
