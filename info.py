# -*- coding: utf-8 -*-
"""Основные команды: админы, хелп, команды, профиль, топ, история, бонус, кошелёк, правила."""
import threading
import time
from datetime import datetime

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from backup import db_has_data, send_backup_to_owner
from bitcoin import fmt_btc
from business import kk_text
from config import (
    ABILITIES_TEXT, BONUS_COOLDOWN, BONUS_EXP, BONUS_MONEY, BTC_UNIT, BUSINESSES, CHAT_RULES,
    COMMAND_CATEGORIES, err_text, fmt_cmd_block, heal_left, HISTORY_DAYS, HISTORY_PAGES, PETS, pets_of,
    LEVEL_UP_REWARD, MIN_LEVEL_HELP, MIN_LEVEL_TO_VIEW_PROFILES, OWNER_ID, PLAYER_LEVELS,
    PROMO_TTL, ROLES, STAFF_COMMANDS, TOP_REWARDS, TOP_SIZE, VAMPIRE_TITLE, VIP_BONUS_MONEY,
    VIP_DAYS, VIP_PRICE, WARNS_LIMIT,
)
from database import (
    backup_db, daily, economy, exp_text, fmt_day, freeze_left, get_level, get_user, get_warns,
    mute_left, player_level, promo_expired, save_economy, save_stats, stats, stats_state,
    today_str, users_with_level, vip_active,
)
from helpers import (
    fmt_duration, fmt_num, fmt_time, freeze_text, get_names, get_user_info, mention,
    nav_keyboard, role_tabs_keyboard, send, target_from_message, target_from_text,
)
from images import drop_photo_cache
from logs import prune_logs
from player import add_exp, vip_benefits
from shop import avatar_attachment


# ---------- «админы» ----------
def build_admins_page(peer_id, page, opener_id):
    if page == len(ROLES) + 1:  # вкладка VIP
        members = [int(u) for u in stats.get(str(peer_id), {})
                   if vip_active(economy["users"].get(u, {}))]
        names = get_names(members[:20])
        lines = ["✨ VIP — участники беседы", ""]
        if members:
            lines += [f"• {mention(u, names)}" for u in members[:20]]
        else:
            lines.append("Пока никого нет")
        lines += ["", f"Купить: «купить вип» — {fmt_num(VIP_PRICE)} 💰", "",
                  "Преимущества VIP:", vip_benefits()]
        return "\n".join(lines), role_tabs_keyboard("admins", page, opener_id)

    members = users_with_level(peer_id, page)
    names = get_names(members)
    if members:
        people = "\n".join(f"• {mention(u, names)}" for u in members)
    else:
        people = "Пока никого нет"

    text = (
        f"👤 {ROLES[page]} ({page}/{len(ROLES)})\n\n"
        f"⚙ Возможности: {ABILITIES_TEXT}\n\n"
        f"Назначены в этой беседе:\n{people}"
    )
    return text, role_tabs_keyboard("admins", page, opener_id)

def cmd_admins(msg, rest, slash):
    text, keyboard = build_admins_page(msg["peer_id"], 1, msg["from_id"])
    send(msg["peer_id"], text, keyboard)

# ---------- «хелп» (только модераторы и выше) ----------
def build_help_page(peer_id, page, opener_id):
    """Вкладки 1–5 — команды одной роли, 6 — VIP. Вкладка вашей роли открывается первой."""
    if page == len(ROLES) + 1:
        text = (f"✨ VIP\n\nЦена: {fmt_num(VIP_PRICE)} 💰\n\n"
                f"Преимущества VIP:\n{vip_benefits()}\n\n"
                "Купить: «купить вип»")
        return text, role_tabs_keyboard("help", page, opener_id)

    viewer = get_level(peer_id, opener_id)
    title = f"📖 Команды: {ROLES[page]}"
    if page == viewer:
        title += " — ваша роль"
    lines = [title, ""]
    if page <= viewer:
        lines.append("✅ Эти команды вам доступны")
    else:
        lines.append(f"🔒 Откроются с роли «{ROLES[page]}»")
    lines.append("")
    cmds = STAFF_COMMANDS[page]
    if cmds:
        for i, (c, d) in enumerate(cmds):
            if i:
                lines.append("")
            lines.append(f"🔹 {c[:1].upper() + c[1:]}\n{d}")
    else:
        lines.append("🛠️ Новые команды на тех. доработке")
    if page > 1:
        lines += ["", "ℹ️ Роль включает команды всех ролей ниже."]
    if page == 5 and opener_id == OWNER_ID:
        lines += ["", "🔒 Ваши команды — «хелп-команды» в ЛС боту."]
    return "\n".join(lines), role_tabs_keyboard("help", page, opener_id)
def cmd_help(msg, rest, slash):
    peer_id = msg["peer_id"]
    user_id = msg["from_id"]
    level = get_level(peer_id, user_id)
    if level < MIN_LEVEL_HELP:
        send(peer_id, "⛔ Команда доступна модераторам и выше. Список команд: «команды».")
        return
    # Открываем страницу своей роли, «Вперед» листает остальные
    text, keyboard = build_help_page(peer_id, level, user_id)
    send(peer_id, text, keyboard)

# ---------- «профиль» ----------
def build_profile(peer_id, uid):
    info = get_user_info(uid)
    user = get_user(uid)
    if not user.get("reg"):  # игрок из прошлой версии: дата — первое сообщение, которое видел бот
        firsts = [c[str(uid)]["first"] for c in stats.values() if str(uid) in c and c[str(uid)].get("first")]
        user["reg"] = min(firsts) if firsts else time.time()
        save_economy()
    level = get_level(peer_id, uid)
    lvl, lname, lo, hi = player_level(user["exp"])
    progress = f"{user['exp']}/{hi}" if user["exp"] < PLAYER_LEVELS[-1][2] else "макс."

    lines = [
        f"🏠 Профиль {mention(uid, {uid: info['name']})}",
        f"💰 Баланс: {fmt_num(user['money'])}",
        f"💪 Уровень: {lvl} — {lname} ({progress})",
        f"😘 Репутация: {user.get('rep', 0)}",
        f"🆔 ID: {uid}",
        f"👀 Дата регистрации: {datetime.fromtimestamp(user['reg']).strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    extra = []
    if level:
        extra.append(f"🛡️ Роль в беседе: {ROLES[level]}")
    if vip_active(user):
        extra.append(f"✨ VIP до {fmt_time(user['vip_until'])}")
    if user.get("vampire"):
        extra.append(f"🧛 Должность: {VAMPIRE_TITLE}")
    if pets_of(user):
        mine = sorted(pets_of(user), key=lambda p: PETS[p]["level"])
        extra.append("🐾 Питомцы: " + ", ".join(PETS[p]["name"] for p in mine))
    if heal_left(user) > 0:
        extra.append(f"🧪 Зелье лечения до {fmt_time(user['heal_until'])}")
    chat_st = stats.get(str(peer_id), {}).get(str(uid))
    if chat_st:
        extra.append(f"💬 Сообщений в чате: {fmt_num(chat_st['n'])}")
    warns = len(get_warns(peer_id, uid))
    if warns:
        extra.append(f"⚠ Предупреждения: {warns}/{WARNS_LIMIT}")
    left = mute_left(peer_id, uid)
    if left > 0:
        extra.append(f"🔇 В муте ещё: {fmt_duration(left)}")
    fz = freeze_left(uid)
    if fz > 0:
        extra.append(f"🧊 Заморожен {freeze_text(fz)}")
    if extra:
        lines += [""] + extra
    return "\n".join(lines)

def cmd_profile(msg, rest, slash):
    peer_id = msg["peer_id"]
    actor = msg["from_id"]

    text_target = target_from_text(rest)
    # «профиль у него классный» — это не команда
    if rest.strip() and text_target is None and not slash:
        return

    target = text_target or target_from_message(msg) or actor
    if target <= 0:
        send(peer_id, "⚠ У сообществ нет профиля.")
        return

    if target != actor and get_level(peer_id, actor) < MIN_LEVEL_TO_VIEW_PROFILES:
        send(peer_id, "⛔ Чужие профили могут смотреть модераторы и выше. "
                      "Свой профиль — команда «профиль».")
        return

    text = build_profile(peer_id, target)
    att = avatar_attachment(peer_id, target)
    try:
        send(peer_id, text, attachment=att)
    except Exception as e:
        if not att:
            raise
        print(f"Не удалось отправить картинку профиля, шлю без неё: {err_text(e)}")
        for name in ("avatar",):
            drop_photo_cache(name)
        send(peer_id, text)

# ---------- «топ» ----------
def cmd_top(msg, rest, slash):
    text, kb = build_top_page(msg["peer_id"], 1, msg["from_id"])
    send(msg["peer_id"], text, kb)

def cmd_top_rep(msg, rest, slash):
    """«топ реп» — сразу топ по репутации."""
    text, kb = build_top_page(msg["peer_id"], 3, msg["from_id"])
    send(msg["peer_id"], text, kb)

# ---------- «бонус» и «кошелёк» ----------
def cmd_bonus(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    user = get_user(uid)
    now = time.time()

    left = user["last_bonus"] + BONUS_COOLDOWN - now
    if left > 0:
        send(peer_id, f"⏳ Следующий бонус можно получить через {fmt_duration(left)}.")
        return

    vip = vip_active(user)
    money = VIP_BONUS_MONEY if vip else BONUS_MONEY
    user["money"] += money
    user["last_bonus"] = now
    level_note = add_exp(uid, BONUS_EXP)
    save_economy()

    lines = ["🎁 Бонус получен! ✨ VIP" if vip else "🎁 Бонус получен!",
             f"+{fmt_num(money)} 💰",
             f"+{BONUS_EXP} exp"]
    if level_note:
        lines += ["", level_note]
    lines += ["", f"💰 Баланс: {fmt_num(user['money'])}", "Следующий бонус — через час."]
    if not vip:
        lines.append(f"✨ С VIP бонус {fmt_num(VIP_BONUS_MONEY)} 💰 — команда «купить вип»")
    send(peer_id, "\n".join(lines))

def cmd_wallet(msg, rest, slash):
    uid = msg["from_id"]
    user = get_user(uid)
    lvl, name, _, hi = player_level(user["exp"])
    lines = [
        "💳 Кошелёк",
        "",
        f"💰 Баланс: {fmt_num(user['money'])}",
        f"⭐ Опыт: {exp_text(user['exp'])}",
        f"🏅 Уровень: {lvl} — {name}",
    ]
    if user["exp"] < PLAYER_LEVELS[-1][2]:
        lines.append(f"До следующего уровня: {hi - user['exp']} exp (награда: +{fmt_num(LEVEL_UP_REWARD)} 💰)")
    if vip_active(user):
        lines.append(f"✨ VIP: до {fmt_time(user['vip_until'])}")
    if user.get("btc", 0) > 0:
        lines.append(f"₿ Биткоин: {fmt_btc(user['btc'])} (≈ {fmt_num(user['btc'] * economy['btc']['rate'] // BTC_UNIT)} 💰)")
    if user.get("biz"):
        lines.append(f"🏢 Бизнес: {', '.join(BUSINESSES[k]['name'] for k in BUSINESSES if k in user['biz'])} — "
                     f"{kk_text(sum(BUSINESSES[k]['income'] for k in user['biz'] if k in BUSINESSES))} 💰 за 12 ч. («доход»)")
    send(msg["peer_id"], "\n".join(lines))

# ---------- Топ дня, итоги и история ----------
def finish_day(day):
    """Подводит итоги дня: сохраняет топ в историю, выдаёт опыт топ-3 и пишет об этом в беседу."""
    medals = ["🥇", "🥈", "🥉"]
    for peer, counts in daily.get("counts", {}).items():
        ranking = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:TOP_SIZE]
        if not ranking:
            continue
        hist = daily["history"].setdefault(peer, [])
        hist.append({"day": day, "top": ranking})
        del hist[:-HISTORY_DAYS]

        names = get_names([int(u) for u, _ in ranking[:3]])
        lines = [f"🏆 Итоги дня {fmt_day(day)} — топ по сообщениям", ""]
        for i, (uid, n) in enumerate(ranking[:3]):
            exp = TOP_REWARDS[i]
            note = add_exp(int(uid), exp)
            lines.append(f"{medals[i]} {mention(int(uid), names)} — {fmt_num(n)} сообщ. (+{exp} exp)")
            if note:
                lines.append("    " + note.replace("\n", " "))
        try:
            send(int(peer), "\n".join(lines))
        except Exception as e:
            print(f"Не удалось отправить итоги дня в {peer}: {err_text(e)}")
    save_economy()

def rollover_if_needed():
    """Раз в сутки сбрасывает дневной топ. Старый топ уходит в историю."""
    today = today_str()
    if daily.get("day") == today:
        return
    if daily.get("day"):
        finish_day(daily["day"])
    daily["day"] = today
    daily["counts"] = {}
    stats_state["dirty"] = True
    save_stats(force=True)
    prune_logs()
    backup_db()
    if db_has_data():  # копию пустой базы владельцу не шлём
        threading.Thread(target=send_backup_to_owner, args=("ежедневная",), daemon=True).start()

def prune_promos():
    """Удаляет промокоды, которым больше 24 часов."""
    old = [k for k, p in economy["promos"].items() if promo_expired(p)]
    for k in old:
        del economy["promos"][k]
    if old:
        save_economy()

def promo_lists(viewer):
    """Только действующие сейчас промокоды (не истекли и ещё есть использования)."""
    avail = [p for p in economy["promos"].values()
             if not promo_expired(p) and len(p["used_by"]) < p["uses"]]
    lines = ["📜 История: действующие промокоды", ""]
    if avail:
        for p in avail[:15]:
            left = p["uses"] - len(p["used_by"])
            ttl = (p.get("exp") or p.get("t", 0) + PROMO_TTL) - time.time()
            mark = " (вы уже активировали)" if viewer in p["used_by"] else ""
            lines.append(f"• {p['name']} — {fmt_num(p['amount'])} 💰, осталось {left}/{p['uses']}, "
                         f"ещё {fmt_duration(max(ttl, 0))}{mark}")
        lines += ["", "Активировать: промокод НАЗВАНИЕ (или просто НАЗВАНИЕ)"]
    else:
        lines.append("Сейчас нет действующих промокодов.")
    return lines

def past_tops_lines(peer_id):
    hist = daily["history"].get(str(peer_id), [])
    lines = ["📜 История: прошлые топы дня", ""]
    if not hist:
        lines.append("Пока пусто — первый топ появится после окончания дня.")
        return lines
    recent = list(reversed(hist))[:HISTORY_DAYS]
    ids = [int(u) for day in recent for u, _ in day["top"][:3]]
    names = get_names(list(set(ids)))
    medals = ["🥇", "🥈", "🥉"]
    for day in recent:
        lines.append(f"📅 {fmt_day(day['day'])}")
        for i, (uid, n) in enumerate(day["top"][:3]):
            lines.append(f"{medals[i]} {mention(int(uid), names)} — {fmt_num(n)}")
        lines.append("")
    return lines

def build_history_page(peer_id, page, opener_id):
    if page == 1 and not vip_active(get_user(opener_id)):
        lines = ["📜 История: промокоды", "",
                 "🔒 Список промокодов доступен только VIP-игрокам.",
                 f"VIP на {VIP_DAYS} дней — {fmt_num(VIP_PRICE)} 💰, команда «купить вип».",
                 "", "Прошлые топы дня доступны всем — кнопка «Вперёд»."]
    elif page == 1:
        lines = promo_lists(opener_id)
    else:
        lines = past_tops_lines(peer_id)
    return "\n".join(lines), nav_keyboard("history", page, 1, HISTORY_PAGES, opener_id)

def cmd_history(msg, rest, slash):
    text, kb = build_history_page(msg["peer_id"], 1, msg["from_id"])
    send(msg["peer_id"], text, kb)

# ---------- Команды по разделам ----------
def cmd_label(cmd_text):
    """«мины [ставка]» → «мины», «купить вип» → «купить вип» (без аргументов)."""
    words = []
    for w in cmd_text.split():
        if w[0] in "([" or w.isupper():
            break
        words.append(w)
    return " ".join(words) or cmd_text

def build_commands_page(peer_id, page, opener_id):
    if page == 0:
        lines = ["📋 Команды бота", "", "Выберите раздел кнопкой 👇", ""]
        for name, cmds in COMMAND_CATEGORIES:
            lines.append(name)
            lines.append(", ".join(cmd_label(c) for c, _ in cmds))
            lines.append("")
        if lines[-1] == "":
            lines.pop()
        if get_level(peer_id, opener_id) >= MIN_LEVEL_HELP:
            lines += ["", "🛡️ Команды модераторов — «хелп»."]
        kb = VkKeyboard(inline=True)
        for i, (name, _) in enumerate(COMMAND_CATEGORIES, 1):
            if i > 1 and (i - 1) % 2 == 0:
                kb.add_line()
            kb.add_callback_button(name, VkKeyboardColor.PRIMARY, {"cmd": "cmds", "p": i, "o": opener_id})
        return "\n".join(lines), kb.get_keyboard()

    name, cmds = COMMAND_CATEGORIES[page - 1]
    lines = [name, ""]
    for i, (c, d) in enumerate(cmds):
        if i:
            lines.append("")
        lines.append(fmt_cmd_block(c, d))
    return "\n".join(lines), nav_keyboard("cmds", page, 1, len(COMMAND_CATEGORIES), opener_id,
                                           middle=("☰ Меню", 0))

def cmd_commands(msg, rest, slash):
    text, kb = build_commands_page(msg["peer_id"], 0, msg["from_id"])
    send(msg["peer_id"], text, kb)

# ---------- Правила беседы ----------
def cmd_rules(msg, rest, slash):
    lines = ["📜 Правила беседы", ""]
    for i, rule in enumerate(CHAT_RULES, 1):
        lines += [f"{i}️⃣ {rule}" if i < 10 else f"🔟 {rule}", ""]
    lines.pop()
    send(msg["peer_id"], "\n".join(lines))

# ---------- Топ: сообщения / баланс ----------
def top_tabs_keyboard(page, opener_id):
    kb = VkKeyboard(inline=True)
    for i, label in ((1, "💬 Сообщения"), (2, "💰 Баланс"), (3, "😘 Репутация")):
        current = i == page
        payload = {"cmd": "top", "p": i, "o": opener_id}
        if current:
            payload["n"] = 1  # нажатие на открытую вкладку ничего не меняет
        kb.add_callback_button(("✔ " if current else "") + label,
                               VkKeyboardColor.POSITIVE if current else VkKeyboardColor.PRIMARY,
                               payload)
    return kb.get_keyboard()

def build_top_page(peer_id, page, opener_id):
    medals = ["🥇", "🥈", "🥉"]
    me = str(opener_id)

    if page == 3:  # топ по репутации среди участников этой беседы
        members = list(stats.get(str(peer_id), {}).keys())
        ranking = sorted(((u, economy["users"].get(u, {}).get("rep", 0)) for u in members),
                         key=lambda kv: kv[1], reverse=True)
        ranking = [kv for kv in ranking if kv[1] > 0]
        if not ranking:
            return "😘 Топ по репутации пока пуст — репутацию выдаёт «+реп» (ответом на сообщение).", \
                   top_tabs_keyboard(page, opener_id)
        top = ranking[:TOP_SIZE]
        names = get_names([int(u) for u, _ in top])
        lines = ["🏆 Топ беседы по репутации", ""]
        for i, (uid, rep_value) in enumerate(top):
            prefix = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{prefix} {mention(int(uid), names)} — {fmt_num(rep_value)} 😘")
        place = next((i for i, (u, _) in enumerate(ranking, 1) if u == me), None)
        if place and place > TOP_SIZE:
            lines += ["", f"Ваше место: {place} ({fmt_num(economy['users'][me].get('rep', 0))} 😘)"]
        lines += ["", "Повысить репутацию: «+реп» ответом на сообщение (раз в час)."]
        return "\n".join(lines), top_tabs_keyboard(page, opener_id)

    if page == 2:  # топ по балансу среди участников этой беседы
        members = list(stats.get(str(peer_id), {}).keys())
        ranking = sorted(((u, economy["users"].get(u, {}).get("money", 0)) for u in members),
                         key=lambda kv: kv[1], reverse=True)
        ranking = [kv for kv in ranking if kv[1] > 0]
        if not ranking:
            return "💰 Топ по балансу пока пуст — получите «бонус».", top_tabs_keyboard(page, opener_id)
        top = ranking[:TOP_SIZE]
        names = get_names([int(u) for u, _ in top])
        lines = ["🏆 Топ беседы по балансу", ""]
        for i, (uid, money) in enumerate(top):
            prefix = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{prefix} {mention(int(uid), names)} — {fmt_num(money)} 💰")
        place = next((i for i, (u, _) in enumerate(ranking, 1) if u == me), None)
        if place and place > TOP_SIZE:
            lines += ["", f"Ваше место: {place} ({fmt_num(economy['users'][me]['money'])} 💰)"]
        return "\n".join(lines), top_tabs_keyboard(page, opener_id)

    counts = daily["counts"].get(str(peer_id), {})
    if not counts:
        return "🏆 Сегодня в беседе ещё никто не писал.", top_tabs_keyboard(page, opener_id)
    ranking = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top = ranking[:TOP_SIZE]
    names = get_names([int(u) for u, _ in top])
    lines = [f"🏆 Топ дня по сообщениям ({fmt_day(daily['day'])})", ""]
    for i, (uid, n) in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {mention(int(uid), names)} — {fmt_num(n)}")
    place = next((i for i, (u, _) in enumerate(ranking, 1) if u == me), None)
    if place and place > TOP_SIZE:
        lines += ["", f"Ваше место: {place} ({fmt_num(counts[me])})"]
    lines += [
        "",
        f"Награда после окончания дня: 🥇 {TOP_REWARDS[0]} exp, 🥈 {TOP_REWARDS[1]} exp, 🥉 {TOP_REWARDS[2]} exp",
        "Прошлые топы — команда «история».",
    ]
    return "\n".join(lines), top_tabs_keyboard(page, opener_id)

# ---------- «офиц» ----------
# Окна с листалкой: команда -> (функция страницы, первая страница, последняя страница)
OFFICIAL_CHAT_LINK = "https://vk.me/join/AZQ1d0OJ9yhAm3LDn1SSjPoi"

def cmd_official(msg, rest, slash):
    send(msg["peer_id"], f"💬 Официальный чат бота\n{OFFICIAL_CHAT_LINK}")

# ---------- «я» — всегда свой профиль (даже если «я» написали ответом на чужое сообщение) ----------
def cmd_profile_me(msg, rest, slash):
    own = dict(msg)
    own.pop("reply_message", None)
    own.pop("fwd_messages", None)
    cmd_profile(own, "", slash)
