# -*- coding: utf-8 -*-
"""Обработка сообщений и кнопок: таблица команд и разбор входящих событий."""
import json
import re

from auction import auction_action, cmd_auction
from backup import cmd_backup
from bank import cmd_bank
from bitcoin import cmd_btc, cmd_buy, cmd_sell
from business import biz_action, cmd_biz, cmd_income
from check import check_callback, cmd_check
from config import (
    BARE_COMMANDS, BOT_MENTION_RE, CHAT_OFFSET, COMMAND_CATEGORIES, DRONE_WORDS, err_text,
    has_perk, HISTORY_PAGES, MIN_LEVEL_HELP, OWNER_ID, ROLES,
)
from contest import contest_try_answer
from crash import cmd_crash
from debt import cmd_debt_give, cmd_debt_return, cmd_debts, debt_action
from database import count_message, economy, freeze_left, get_level, get_user, mute_left
from donate import build_donate_page, cmd_donate, donate_action, DONATE_KEYS
from duel import cmd_duel, duel_action
from extras import (
    cmd_safe, cmd_steal, handle_appeal_callback, safe_action,
)
from fishing import cmd_fishing, fish_action
from gban import cmd_deputy, cmd_gban, cmd_ungban, gban_guard
from gldeputy import cmd_fine, cmd_gl_deputy, cmd_norm_minus, cmd_norm_plus, cmd_renorm
from helpers import (
    answer_event, delete_message, drone_command, drone_guard, edit_message, freeze_text,
    get_names, HANDLERS, kick_from_chat, mention, PAGER_WORDS, register, send,
)
from info import (
    build_admins_page, build_commands_page, build_help_page, build_history_page, build_top_page,
    cmd_admins, cmd_bonus, cmd_commands, cmd_help, cmd_history, cmd_official, cmd_profile,
    cmd_profile_me, cmd_rules, cmd_top, cmd_top_rep, cmd_wallet, rollover_if_needed,
)
from logs import cmd_logs, log_action, log_message
from mines import cmd_mines, mines_action
from moderation import (
    cmd_ban, cmd_delete, cmd_freeze, cmd_kick, cmd_mute, cmd_rights, cmd_timeout, cmd_unban,
    cmd_unfreeze, cmd_unmute, cmd_unwarn, cmd_warn, handle_action, timeout_active,
)
from owner_cmds import cmd_owner_grant, cmd_owner_take
from pets import cmd_pets, pet_action
from player import cmd_prefix, cmd_rep_minus, cmd_rep_plus, vip_action
from referral import check_referral_join, cmd_ref
from reports_actions import handle_rate_callback, handle_staff_callback
from reports_dialog import cmd_report
from reports_owner import handle_report_callback
from roulette import cmd_roulette, roulette_action
from shop import cmd_shop, cmd_wardrobe, shop_action
from staff_money import (
    cmd_give_exp, cmd_give_money, cmd_promo, cmd_take_exp, cmd_take_money,
    handle_approval_callback, try_plain_promo,
)
from transfer import cmd_transfer
from wipe import cmd_restore_account, wipe_callback


# ---------- Листалка (общая для «админы» и «хелп») ----------
def handle_callback(ev):
    payload = ev["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    cmd = payload.get("cmd")

    if cmd == "rep":                  # кнопки владельца в личных сообщениях
        handle_report_callback(ev, payload)
        return
    if cmd == "appr":                 # разрешения владельца (деньги, промокоды, опыт)
        handle_approval_callback(ev, payload)
        return
    if cmd == "chk":                  # чеки: владелец подтверждает / отказывает в ЛС
        check_callback(ev, payload)
        return
    if cmd == "rs":                   # кнопки следящего за репортами в ЛС
        handle_staff_callback(ev, payload)
        return
    if cmd == "rate":                 # оценка следящего игроком (звёздочки в ЛС)
        handle_rate_callback(ev, payload)
        return
    if cmd == "wipe":                   # кнопки «Обнулить у обоих / Отказать» в ЛС владельца
        wipe_callback(ev, payload)
        return
    if cmd == "appeal":               # «Я заполнил(а)» под апелляцией (в беседе и в ЛС)
        handle_appeal_callback(ev, payload)
        return
    if ev["peer_id"] < CHAT_OFFSET and cmd not in ("shop", "biz", "don", "dpg", "pet"):   # всё остальное работает только в беседах (магазин, бизнесы и питомцы — и в ЛС)
        answer_event(ev, "Эта кнопка работает только в беседе.")
        return

    uid = ev["user_id"]
    left = freeze_left(uid) if uid != OWNER_ID else 0
    if left > 0:
        answer_event(ev, f"🧊 Вы в заморозке {freeze_text(left)}.")
        return

    actions = {"mines": mines_action, "duel": duel_action, "vip": vip_action,
               "roul": roulette_action, "fish": fish_action, "shop": shop_action, "biz": biz_action,
               "auc": auction_action, "debt": debt_action, "don": donate_action, "safe": safe_action,
               "pet": pet_action}
    if cmd in actions:
        note = None
        try:
            note = actions[cmd](ev, payload)
        finally:
            answer_event(ev, note)    # кнопка не должна «крутиться» ни при каких ошибках
        return

    if cmd not in PAGERS:             # кнопка из старой версии бота
        answer_event(ev, "Кнопка устарела. Напишите команду заново.")
        return
    builder, first, last = PAGERS[cmd]
    peer_id = ev["peer_id"]

    # Листать может только тот, кто вызвал команду
    if uid != payload.get("o", payload.get("opener")):
        answer_event(ev, f"Это окно открыл другой участник. Напишите «{PAGER_WORDS[cmd]}» сами.")
        return
    if cmd == "help" and get_level(peer_id, uid) < MIN_LEVEL_HELP and not has_perk(get_user(uid), "help"):
        answer_event(ev, "Эта команда доступна только модераторам и выше.")
        return
    if payload.get("n"):              # открытая вкладка / счётчик страниц
        answer_event(ev)
        return

    page = int(payload.get("p", payload.get("level", first)))
    if not first <= page <= last:
        page = first
    answer_event(ev)                  # сначала ответ, потом долгие запросы
    text, keyboard = builder(peer_id, page, uid)
    edit_message(peer_id, ev["conversation_message_id"], text, keyboard)

# ---------- Команды владельца в ЛС боту: промокод, деньги себе, режим «беспилотник» ----------
PAGERS = {
    "top": (build_top_page, 1, 3),
    "admins": (build_admins_page, 1, len(ROLES) + 1),
    "help": (build_help_page, 1, len(ROLES) + 1),
    "history": (build_history_page, 1, HISTORY_PAGES),
    "cmds": (build_commands_page, 0, len(COMMAND_CATEGORIES)),
    "dpg": (build_donate_page, 0, len(DONATE_KEYS)),
}
# Команды из двух слов
TWO_WORD_COMMANDS = {
    ("снять", "варн"): "унварн",
    ("выдать", "опыт"): "опыт",
    ("выдать", "деньги"): "деньги",
    ("забрать", "деньги"): "забрать",
    ("забрать", "опыт"): "забрать_опыт",
    ("снять", "опыт"): "забрать_опыт",
    ("мои", "аксессуары"): "мои_аксессуары",
    ("топ", "реп"): "топ_реп",
    ("топ", "репутация"): "топ_реп",
    ("топ", "репутации"): "топ_реп",
    ("top", "rep"): "топ_реп",
    ("+", "реп"): "+реп",
    ("-", "реп"): "-реп",
    ("курс", "бит"): "бит",
    ("курс", "биткоин"): "биткоин",
    ("курс", "btc"): "btc",
    ("права", "зам"): "зам_чата",
    ("права", "заместитель"): "зам_чата",
    ("права", "замчата"): "зам_чата",
    ("права", "гл"): "гл_зам",
    ("права", "гл.зам"): "гл_зам",
    ("права", "глзам"): "гл_зам",
    ("права", "главный"): "гл_зам",
    ("дать", "долг"): "долг_дать",
    ("отдать", "долг"): "долг_вернуть",
    ("вернуть", "долг"): "долг_вернуть",
    ("+", "норма"): "+норма",
    ("-", "норма"): "-норма",
    ("+", "перенорма"): "+перенорма",
}

MASS_MENTION_RE = re.compile(r"(?<![\w@])[@*](all|everyone|online|here|все|всем|онлайн|здесь)(?![\w])", re.IGNORECASE)

def handle_message(msg):
    rollover_if_needed()
    peer_id = msg["peer_id"]
    uid = msg["from_id"]

    # Глобальный бан: забаненный вошёл или написал в любой беседе — исключаем
    if gban_guard(msg):
        return

    # Служебные события: вход в беседу (проверка бана)
    action = msg.get("action")
    if action:
        handle_action(msg, action)
        return

    # Запрет на @all / @everyone / @online / @here: сообщение удаляется, автор исключается (владелец не затрагивается)
    if uid > 0 and uid != OWNER_ID and MASS_MENTION_RE.search(msg.get("text", "") or ""):
        delete_message(peer_id, msg["conversation_message_id"])
        log_message(msg, "удалено: @all")
        try:
            kick_from_chat(peer_id, uid)
            names = get_names([uid])
            send(peer_id, f"🚫 {mention(uid, names)} исключён из беседы: массовое упоминание (@all) запрещено.")
            log_action(peer_id, uid, "кик за @all")
        except Exception as e:
            print(f"Не удалось исключить за @all {uid}: {err_text(e)}")
            send(peer_id, "⚠ Обнаружен @all, но исключить не удалось — у бота должны быть права администратора беседы.")
        return

    # Мут и режим тишины: сообщения удаляются, команды не работают
    muted = uid > 0 and mute_left(peer_id, uid) > 0
    silenced = (not muted and uid > 0 and get_level(peer_id, uid) == 0
                and timeout_active(peer_id))
    if muted or silenced:
        log_message(msg, "удалено: мут" if muted else "удалено: тишина")
        delete_message(peer_id, msg["conversation_message_id"])
        return

    if uid > 0 and str(uid) in economy["refs"]:
        check_referral_join(peer_id, uid)       # реф-новичок написал первое сообщение — платим, даже если вход не заметили

    log_message(msg)
    count_message(msg)

    text = BOT_MENTION_RE.sub("", msg.get("text", "")).strip()
    if not text:
        return

    if uid > 0 and contest_try_answer(msg, text):   # верный ответ на конкурс «решите пример»
        return

    parts = text.split(maxsplit=1)
    raw_cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    slash = raw_cmd.startswith("/")
    cmd = raw_cmd.lstrip("/").replace("ё", "е")

    if rest:  # «снять варн», «выдать опыт» и т.п.
        word, _, tail = rest.partition(" ")
        alias = TWO_WORD_COMMANDS.get((cmd, word.lower()))
        if alias:
            cmd, rest = alias, tail.strip()

    if cmd in BARE_COMMANDS and rest and not slash:
        return

    if uid == OWNER_ID and cmd in DRONE_WORDS:       # владелец: «дрон вкл / выкл» — режим «беспилотник»
        drone_command(peer_id, rest.split())
        return

    handler = HANDLERS.get(cmd)
    if handler:
        left = freeze_left(uid) if uid != OWNER_ID else 0
        if left > 0:  # заморозка: все команды недоступны
            send(peer_id, f"🧊 Ваши команды заморожены {freeze_text(left)}. Можно только общаться в чате.")
            return
        if drone_guard(msg, cmd, rest, slash):         # кнопки сейчас не работают — игру не начинаем
            return
        handler(msg, rest, slash)
    elif not rest and not slash:
        try_plain_promo(msg, text)      # просто слово-промокод, без слова «промокод»

# ---------- выполняется при запуске ----------
register(("админы", "admins"), cmd_admins)
register(("права", "rights"), cmd_rights)
register(("хелп", "help"), cmd_help)
register(("команды", "commands"), cmd_commands)
register(("профиль", "profile", "проф", "prof"), cmd_profile)
register(("я",), cmd_profile_me)
register(("топ", "top"), cmd_top)
register(("топ_реп",), cmd_top_rep)
register(("история", "history"), cmd_history)
register(("бонус", "bonus"), cmd_bonus)
register(("кошелек", "wallet", "баланс", "balance"), cmd_wallet)   # «ё» заменяется на «е» до поиска
register(("купить", "buy"), cmd_buy)
register(("продать", "sell"), cmd_sell)
register(("бит", "биткоин", "btc", "bitcoin"), cmd_btc)
register(("бизнес", "бизнесы", "business"), cmd_biz)
register(("доход", "income"), cmd_income)
register(("передать", "transfer"), cmd_transfer)
register(("мины", "mines"), cmd_mines)
register(("дуэль", "duel"), cmd_duel)
register(("промокод", "promo"), cmd_promo)
register(("реф", "рефералка", "ref", "referral"), cmd_ref)
register(("аук", "аукцион", "auction", "auc"), cmd_auction)
register(("репорт", "report"), cmd_report)
register(("мут", "mute"), cmd_mute)
register(("размут", "unmute"), cmd_unmute)
register(("варн", "warn"), cmd_warn)
register(("унварн", "unwarn"), cmd_unwarn)
register(("кик", "kick"), cmd_kick)
register(("бан", "ban"), cmd_ban)
register(("разбан", "unban"), cmd_unban)
register(("префикс", "prefix"), cmd_prefix)
register(("timeout", "тишина"), cmd_timeout)
register(("деньги", "money"), cmd_give_money)
register(("опыт", "exp"), cmd_give_exp)
register(("забрать", "take"), cmd_take_money)
register(("правила", "rules"), cmd_rules)
register(("рулетка", "roulette"), cmd_roulette)
register(("рыбалка", "fishing"), cmd_fishing)
register(("магазин", "shop"), cmd_shop)
register(("мои_аксессуары", "гардероб", "wardrobe"), cmd_wardrobe)
register(("+реп", "+rep", "+репутация"), cmd_rep_plus)
register(("-реп", "-rep", "-репутация"), cmd_rep_minus)
register(("заморозить", "freeze"), cmd_freeze)
register(("разморозить", "unfreeze"), cmd_unfreeze)
register(("забрать_опыт",), cmd_take_exp)
register(("удалить", "delete"), cmd_delete)
register(("logs", "логи"), cmd_logs)
register(("бэкап", "backup"), cmd_backup)
register(("донат", "donate"), cmd_donate)
register(("укусить", "bite", "украсть", "steal"), cmd_steal)
register(("питомцы", "питомец", "пит", "pets", "pet"), cmd_pets)
register(("офиц", "official"), cmd_official)
register(("сейф", "safe"), cmd_safe)
register(("восстановить", "restore"), cmd_restore_account)   # владелец: вернуть обнулённый аккаунт
register(("банк", "bank"), cmd_bank)
register(("гбан", "gban"), cmd_gban)
register(("разгбан", "ungban", "гразбан"), cmd_ungban)
register(("зам_чата",), cmd_deputy)
register(("гл_зам",), cmd_gl_deputy)
register(("штраф", "fine"), cmd_fine)
register(("-норма",), cmd_norm_minus)
register(("+норма",), cmd_norm_plus)
register(("+перенорма",), cmd_renorm)
register(("выдать", "give"), cmd_owner_grant)
register(("отобрать",), cmd_owner_take)
register(("долг_дать",), cmd_debt_give)
register(("долг_вернуть",), cmd_debt_return)
register(("долги", "debts"), cmd_debts)
register(("краш", "crash"), cmd_crash)
register(("чек", "check"), cmd_check)
