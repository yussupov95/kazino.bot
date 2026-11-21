# -*- coding: utf-8 -*-
"""Небольшие команды: вампир (укусить), сейф, апелляция, лайки под постами бота."""
import os
import random
import re
import time

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from business import kk_text
from config import (
    err_text, _find, fmt_pct, GROUP_ID, heal_left, _here, OWNER_ID, requests, VAMPIRE_COOLDOWN,
    VAMPIRE_IMMUNE, VAMPIRE_PERCENT, VAMPIRE_TITLE, VAMPIRE_TOP_PERCENT, vk, vk_upload,
)
from database import economy, freeze_left, get_user, save_economy, stats
from helpers import (
    answer_event, edit_message, fmt_duration, fmt_num, get_names, mention, parse_target, send,
    send_dm, send_get_cmid,
)
from images import cached_photo
from logs import log_action
from player import add_exp


# ---------- Вампир ----------
def balance_leader(peer_id):
    """ID (строкой) игрока на 1 месте в топе беседы по балансу — как в «топ» → «Баланс». Если никого нет — None."""
    best, best_money = None, 0
    for u in stats.get(str(peer_id), {}):
        money = economy["users"].get(u, {}).get("money", 0)
        if money > best_money:
            best, best_money = u, money
    return best

def vampire_steal(msg, victim, quiet=False):
    """Вампир кусает игрока: забирает VAMPIRE_PERCENT% его денег, а у лидера топа по балансу — VAMPIRE_TOP_PERCENT%.
    Только по команде «укусить» / «украсть»: простое @упоминание вампира — это не укус.
    quiet — не отвечать на «ошибки новичков»."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    user = get_user(uid)

    def say(text):
        if not quiet:
            send(peer_id, text)

    if not user.get("vampire"):
        say(f"🧛 Кусать могут только {VAMPIRE_TITLE}ы. Получить должность: «донат».")
        return
    if victim is None or victim <= 0:
        say("ℹ️ Использование: укусить — ответом на сообщение игрока, или «укусить @имя».")
        return
    if victim == uid:
        say("🧛 Себя кусать бессмысленно.")
        return
    if victim in VAMPIRE_IMMUNE:
        say("🛡 У этого игрока иммунитет к вампирам.")
        return
    left = user.get("last_steal", 0) + VAMPIRE_COOLDOWN - time.time()
    if left > 0:
        say(f"🧛 Вы ещё сыты. Следующий укус через {fmt_duration(left)}.")
        return
    target = economy["users"].get(str(victim))
    if not target or str(victim) not in stats.get(str(peer_id), {}):
        say("🧛 Не нашёл такого игрока в этой беседе.")
        return
    if target.get("vampire"):
        say("🧛 Нельзя кусать других Вампиров.")
        return
    if heal_left(target) > 0:
        say(f"🧪 У этого игрока зелье лечения — укус не удался (действует ещё {fmt_duration(heal_left(target))}).")
        return
    is_leader = balance_leader(peer_id) == str(victim)       # 1 место в топе по балансу
    percent = VAMPIRE_TOP_PERCENT if is_leader else VAMPIRE_PERCENT
    amount = int(target.get("money", 0)) * int(round(percent * 10)) // 1000
    if amount <= 0:
        say("🧛 У жертвы нечего брать.")
        return
    target["money"] -= amount
    user["money"] += amount
    user["last_steal"] = time.time()
    save_economy()
    log_action(peer_id, uid, f"вампир укусил: {amount} у {victim} ({fmt_pct(percent)}%)")
    names = get_names([uid, victim])
    text = (f"🧛 {mention(uid, names)} укусил {mention(victim, names)} и забрал {fmt_num(amount)} 💰 "
            f"({fmt_pct(percent)}% баланса).")
    if is_leader:
        text += f"\n👑 {mention(victim, names)} на 1 месте в топе по балансу — его кусают только на {fmt_pct(VAMPIRE_TOP_PERCENT)}%."
    send(peer_id, text + f"\nСледующий укус — через {VAMPIRE_COOLDOWN // 3600} ч.")

def cmd_steal(msg, rest, slash):
    victim, _ = parse_target(msg, rest)
    vampire_steal(msg, victim)

# ---------- Бонус «Сейф» ----------
SAFE_PRIZE = 10_000_000         # выигрыш: 10кк
SAFE_COOLDOWN = 3600            # кд: раз в час
SAFE_IMAGE = _find("safe.jpg")  # картинка сейфа (если файла нет — бот сам скопирует его из папки assets/)

def safe_attachment(peer_id):
    return cached_photo(peer_id, SAFE_IMAGE, "safe") if os.path.exists(SAFE_IMAGE) else None

def cmd_safe(msg, rest, slash):
    """«сейф»: на выбор два кода, один из них подходит. Подошёл — приз, нет — «вы в розыске». Раз в час."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    user = get_user(uid)
    now = time.time()
    left = user.get("last_safe", 0) + SAFE_COOLDOWN - now
    if left > 0:
        send(peer_id, f"⏳ Сейф можно вскрыть снова через {fmt_duration(left)}.")
        return
    a, b = random.sample(range(1, 10), 2)
    codes = [str(a) * 4, str(b) * 4]                  # например 1111 и 7777
    win = random.randrange(2)
    kb = VkKeyboard(inline=True)
    for i, code in enumerate(codes):
        kb.add_callback_button(code, VkKeyboardColor.PRIMARY, {"cmd": "safe", "o": uid, "i": i})
    att = safe_attachment(peer_id)
    text = (f"🔐 Сейф\n\nВыберите код для сейфа: {codes[0]} или {codes[1]}\n"
            f"Подойдёт — заберёте {kk_text(SAFE_PRIZE)} 💰. Не подойдёт — ничего не потеряете.\n"
            "Сейф можно вскрывать раз в час.")
    cmid = send_get_cmid(peer_id, text, kb.get_keyboard(), attachment=att)
    user["last_safe"] = now
    user["safe"] = {"codes": codes, "win": win, "cmid": cmid, "att": att, "open": True}
    save_economy()

def safe_action(ev, p):
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это не ваш сейф. Напишите «сейф» сами."
    user = get_user(uid)
    game = user.get("safe")
    if not game or not game.get("open") or game.get("cmid") != cmid:
        return "Эта попытка уже использована. Напишите «сейф» заново."
    try:
        idx = int(p.get("i"))
        chosen = game["codes"][idx]
    except (TypeError, ValueError, IndexError):
        return "Кнопка устарела. Напишите «сейф» заново."
    game["open"] = False                                # сначала закрываем игру — повторное нажатие ничего не даст
    won = idx == game["win"]
    names = get_names([uid])
    who = mention(uid, names)
    if won:
        user["money"] += SAFE_PRIZE
        text = (f"🔓 {who}, код {chosen} подошёл — сейф открыт!\n"
                f"+{fmt_num(SAFE_PRIZE)} 💰\n💰 Баланс: {fmt_num(user['money'])}")
    else:
        text = f"🔐 {who} выбрал код {chosen}\n❌ Код неправильный, вы в розыске! 🚨"
    save_economy()
    log_action(peer_id, uid, f"сейф: код {chosen}, {'выигрыш ' + str(SAFE_PRIZE) if won else 'проигрыш'}")
    try:
        edit_message(peer_id, cmid, text, attachment=game.get("att"))
    except Exception as e:
        print(f"Не удалось обновить сообщение сейфа: {err_text(e)}")
        send(peer_id, text)
    return None

# ---------- «апелляция» ----------
# Игрок получает ссылку на отдельный документ/форму (не через бота), заполняет его и нажимает «Я заполнил(а)» —
# после этого владельцу в ЛС приходит «Апелляция была закинута, проверьте» со ссылкой на документ.
# Работает и в беседе, и в ЛС бота (забаненный игрок в беседу написать не может).
APPEAL_FORM_URL = ""        # ссылка, где игроки заполняют апелляцию (Google Форма / Документ). Можно задать в ЛС: «апелляция форма ССЫЛКА»
APPEAL_DOC_URL = ""         # ссылка на документ/таблицу с ответами — её бот присылает вам. Пусто — та же, что форма. В ЛС: «апелляция документ ССЫЛКА»
APPEAL_COOLDOWN = 3600      # один игрок может отправить уведомление не чаще раза в час
APPEAL_WORDS = ("апелляция", "апеляция", "аппеляция", "апелляцию", "обжалование", "appeal")

def appeal_urls():
    s = economy.setdefault("settings", {})
    form = s.get("appeal_form") or APPEAL_FORM_URL
    doc = s.get("appeal_doc") or APPEAL_DOC_URL or form
    return form, doc

def cmd_appeal(msg, rest, slash):
    peer_id, uid = msg["peer_id"], msg["from_id"]
    form, _ = appeal_urls()
    if not form:
        send(peer_id, "⚠ Ссылка на апелляцию пока не настроена. Напишите владельцу.")
        return
    text = ("📝 Апелляция — жалоба на модератора или обжалование бана\n\n"
            f"1) Перейдите по ссылке и заполните документ:\n{form}\n\n"
            "В нём нужно указать: ваш ник, за что вас забанили, когда это было, ник модератора "
            "и подробно описать ситуацию.\n\n"
            "2) Когда заполните — нажмите кнопку ниже, и владелец получит уведомление.")
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("✅ Я заполнил(а)", VkKeyboardColor.POSITIVE, {"cmd": "appeal", "o": uid})
    send(peer_id, text, kb.get_keyboard())

def appeal_keyboard(uids):
    """Кнопка «Отправить обжалование» под сообщением о наказании. uids — кому можно нажимать (число или список)."""
    kb = VkKeyboard(inline=True)
    kb.add_callback_button("📝 Отправить обжалование", VkKeyboardColor.SECONDARY,
                           {"cmd": "appeal", "a": "start", "o": uids})
    return kb.get_keyboard()

def appeal_start(ev, p):
    """Нажатие «Отправить обжалование»: форма приходит в ЛС (если ЛС закрыты — в беседу)."""
    uid, peer_id = ev["user_id"], ev["peer_id"]
    owners = p.get("o")
    if uid not in (owners if isinstance(owners, list) else [owners]):
        return "Эта кнопка не для вас."
    form, _ = appeal_urls()
    if not form:
        return "Ссылка пока не настроена. Напишите владельцу."
    try:
        cmd_appeal({"peer_id": uid, "from_id": uid}, "", False)
        return "📨 Форма отправлена вам в ЛС бота."
    except Exception:
        pass
    cmd_appeal({"peer_id": peer_id, "from_id": uid}, "", False)
    return "Форма — в сообщении ниже."

def appeal_action(ev, p):
    if p.get("a") == "start":
        return appeal_start(ev, p)
    peer_id, uid, cmid = ev["peer_id"], ev["user_id"], ev["conversation_message_id"]
    if uid != p.get("o"):
        return "Это не ваша кнопка. Напишите «апелляция» сами."
    user = get_user(uid)
    left = user.get("last_appeal", 0) + APPEAL_COOLDOWN - time.time()
    if left > 0:
        return f"Вы уже отправляли апелляцию. Подождите {fmt_duration(left)}."
    form, doc = appeal_urls()
    names = get_names([uid])
    who = f"[id{uid}|{names.get(uid, f'id{uid}')}] (id{uid})"
    try:
        send_dm(OWNER_ID, f"📩 Апелляция была закинута, проверьте!\n\nОт: {who}\n📄 Документ: {doc}")
    except Exception as e:
        print(f"Не удалось уведомить владельца об апелляции: {err_text(e)}")
        return "Не получилось уведомить владельца. Попробуйте позже."
    user["last_appeal"] = time.time()
    economy["seq"]["appeal"] = economy["seq"].get("appeal", 0) + 1
    save_economy()
    log_action(peer_id, uid, "отправил апелляцию")
    try:
        edit_message(peer_id, cmid, "✅ Апелляция отправлена владельцу. Ответ придёт после проверки.")
    except Exception as e:
        print(f"Не удалось обновить сообщение апелляции: {err_text(e)}")
    return "✅ Апелляция отправлена"

def handle_appeal_callback(ev, p):
    note = None
    try:
        note = appeal_action(ev, p)
    finally:
        answer_event(ev, note)

def owner_appeal_settings(msg, tail):
    """ЛС владельца: «апелляция форма ССЫЛКА» / «апелляция документ ССЫЛКА»."""
    peer_id = msg["peer_id"]
    kind, _, url = tail.partition(" ")
    kind, url = kind.lower().replace("ё", "е"), url.strip()
    key = {"форма": "appeal_form", "form": "appeal_form", "ссылка": "appeal_form",
           "документ": "appeal_doc", "таблица": "appeal_doc", "doc": "appeal_doc", "ответы": "appeal_doc"}.get(kind)
    if not key or not url.lower().startswith(("http://", "https://")):
        form, doc = appeal_urls()
        send(peer_id, "ℹ️ Апелляция.\n"
                      "• апелляция форма ССЫЛКА — где игроки заполняют апелляцию\n"
                      "• апелляция документ ССЫЛКА — документ/таблица с ответами (её бот пришлёт вам в уведомлении)\n\n"
                      f"Сейчас:\nФорма: {form or 'не задана'}\nДокумент: {doc or 'не задан'}")
        return True
    economy.setdefault("settings", {})[key] = url
    save_economy()
    form, doc = appeal_urls()
    send(peer_id, f"✅ Сохранено.\nФорма: {form or 'не задана'}\nДокумент: {doc or 'не задан'}")
    return True

def appeal_dm(msg, text):
    """«апелляция» в ЛС боту: игрок получает ссылку, владелец может задать ссылки. True — обработано."""
    word, _, tail = text.strip().partition(" ")
    if word.lower().strip(" .!?") not in APPEAL_WORDS:
        return False
    tail = tail.strip()
    if msg["from_id"] == OWNER_ID and tail:
        return owner_appeal_settings(msg, tail)
    if tail:
        return False
    cmd_appeal(msg, "", False)
    return True

# ---------- Лайки под постами, опубликованными через бота ----------
# Владелец пишет боту в ЛС «пост ТЕКСТ» (можно с фото) — бот публикует запись в сообществе от своего имени.
# Каждый, кто лайкнул ЭТУ запись, получает WALL_LIKE_MONEY и WALL_LIKE_EXP (один раз за запись).
# Нужно: у ключа сообщества право «Стена», а в Long Poll включены события о лайках (like_add).
WALL_LIKE_MONEY = 10_000_000    # 10кк за лайк
WALL_LIKE_EXP = 3               # и 3 exp
WALL_POSTS_KEEP = 300           # сколько последних записей бота помнить
POST_WORDS = ("пост", "post")

def wall_photos_from_msg(msg):
    """Фото из сообщения владельца загружаются на стену сообщества. Возвращает (attachments, ошибка)."""
    found = []
    for a in msg.get("attachments") or []:
        if a.get("type") == "photo":
            sizes = a["photo"].get("sizes") or []
            if sizes:
                found.append(max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))["url"])
    if not found:
        return [], None
    if requests is None:
        return [], "для фото нужен модуль requests (pip install requests) — пост выйдет без картинок"
    out = []
    for i, url in enumerate(found[:4]):
        path = _here(f"cache/wallpost_{int(time.time())}_{i}.jpg")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(requests.get(url, timeout=30).content)
            ph = vk_upload.photo_wall(path, group_id=GROUP_ID)[0]
            out.append(f"photo{ph['owner_id']}_{ph['id']}")
        except Exception as e:
            print(f"Не удалось загрузить фото на стену: {err_text(e)}")
            return out, f"фото загрузить не удалось ({err_text(e)})"
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    return out, None

def owner_post_command(msg, text):
    """«пост ТЕКСТ» в ЛС владельца. True — обработано."""
    word, _, body = text.strip().partition(" ")
    if word.lower().strip(" .!?:") not in POST_WORDS:
        return False
    peer_id = msg["peer_id"]
    body = body.strip()
    atts, photo_err = wall_photos_from_msg(msg)
    if not body and not atts:
        send(peer_id, "ℹ️ Использование: пост ТЕКСТ (можно приложить фото).\n"
                      f"Каждый, кто лайкнет эту запись, получит {kk_text(WALL_LIKE_MONEY)} 💰 и {WALL_LIKE_EXP} exp.")
        return True
    try:
        res = vk.wall.post(owner_id=-GROUP_ID, from_group=1, message=body or None,
                           attachments=",".join(atts) or None)
        post_id = res["post_id"]
    except Exception as e:
        print(f"Не удалось опубликовать пост: {err_text(e)}")
        send(peer_id, f"❌ Не удалось опубликовать пост: {err_text(e)}\n"
                      "У ключа сообщества должно быть право «Стена» (для фото — ещё «Фотографии»).")
        return True
    posts = economy.setdefault("wall_posts", {})
    posts[str(post_id)] = {"t": int(time.time()), "likers": []}
    for old in sorted(posts, key=lambda k: posts[k].get("t", 0))[:-WALL_POSTS_KEEP]:
        del posts[old]
    save_economy()
    log_action(0, OWNER_ID, f"пост на стене {post_id}")
    note = f"\n⚠ {photo_err}" if photo_err else ""
    send(peer_id, f"✅ Пост опубликован: https://vk.com/wall-{GROUP_ID}_{post_id}\n"
                  f"За каждый лайк — +{kk_text(WALL_LIKE_MONEY)} 💰 и +{WALL_LIKE_EXP} exp (один раз на человека).{note}")
    return True

def handle_like(obj):
    """Событие like_add: лайк на запись, которую опубликовал бот → награда."""
    if obj.get("object_type") != "post":
        return
    try:
        if int(obj.get("object_owner_id", 0)) != -GROUP_ID:
            return
    except (TypeError, ValueError):
        return
    pid = str(obj.get("object_id") or obj.get("post_id") or "")
    rec = economy.get("wall_posts", {}).get(pid)
    uid = obj.get("liker_id")
    if not rec or not isinstance(uid, int) or uid <= 0:
        return
    if uid in rec["likers"]:                            # уже получал за эту запись: лайк-дизлайк-лайк денег не даёт
        return
    rec["likers"].append(uid)
    user = get_user(uid)
    user["money"] += WALL_LIKE_MONEY
    level_note = add_exp(uid, WALL_LIKE_EXP)
    save_economy()
    log_action(0, uid, f"лайк записи {pid}: +{WALL_LIKE_MONEY}, +{WALL_LIKE_EXP} exp")
    lines = ["❤ Спасибо за лайк!", f"+{fmt_num(WALL_LIKE_MONEY)} 💰 и +{WALL_LIKE_EXP} exp"]
    if level_note:
        lines += ["", level_note]
    try:
        send(uid, "\n".join(lines))                     # если ЛС закрыты — просто молчим, награда уже выдана
    except Exception:
        pass

def event_is(event, name):
    """Событие Long Poll по имени ('like_add'): работает и со старыми версиями vk_api."""
    return str(getattr(event.type, "value", event.type)) == name
