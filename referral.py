# -*- coding: utf-8 -*-
"""Рефералка: приглашения и награды."""
import re
import time

from config import (
    CHAT_OFFSET, err_text, GROUP_ID, REF_CHAT_LINK, REF_EXP, REF_INVITEE_REWARD,
    REF_PENDING_TTL, REF_REWARD, vk,
)
from database import economy, get_user, save_economy, stats
from helpers import fmt_num, get_names, mention, send
from logs import log_action
from player import add_exp


# ---------- Рефералка ----------
# Ссылка у каждого своя: https://vk.me/club<ID группы>?ref=r<ID игрока>_<номер беседы>
# 1) Человек переходит по ссылке и нажимает «Начать» → VK передаёт боту параметр ref → бот запоминает, кто пригласил,
#    и присылает ссылку-приглашение в беседу.
# 2) Когда он заходит в эту беседу — пригласивший получает REF_REWARD. За одного человека — один раз.
REF_RE = re.compile(r"^r(\d+)_(\d+)$")

def ref_link(uid, peer_id):
    return f"https://vk.me/club{GROUP_ID}?ref=r{uid}_{peer_id - CHAT_OFFSET}"

def ref_stats(uid):
    paid = [r for r in economy["refs"].values() if r.get("ref") == uid and r.get("paid")]
    return len(paid), sum(int(r.get("amount") or 0) for r in paid)

def cmd_ref(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    if uid <= 0:
        return
    get_user(uid)               # игрок должен быть в базе — иначе ссылка не сработает
    save_economy()
    count, earned = ref_stats(uid)
    exp_earned = sum(int(r.get("exp_amount") or 0) for r in economy["refs"].values() if r.get("ref") == uid and r.get("paid"))
    send(peer_id, f"🔗 Ваша реферальная ссылка:\n{ref_link(uid, peer_id)}\n\n"
                  f"Отправьте её другу: он перейдёт по ссылке, нажмёт «Начать», получит приглашение в беседу — "
                  f"и когда зайдёт, вы ОБА получите {fmt_num(REF_REWARD)} 💰 и {REF_EXP} exp.\n"
                  f"Друг должен быть новичком беседы (раньше в ней не писал). За каждого нового человека — один раз.\n"
                  f"Если после перехода бот не ответил — пусть друг отправит ему в личку эту ссылку сообщением.\n\n"
                  f"👥 Приглашено: {count}\n"
                  f"💰 Заработано: {fmt_num(earned)}\n"
                  f"⭐ Опыта: {fmt_num(exp_earned)}")

def get_chat_invite_link(chat_peer):
    """Ссылка-приглашение в беседу: бот должен быть администратором беседы. Иначе — REF_CHAT_LINK."""
    try:
        res = vk.messages.getInviteLink(peer_id=chat_peer, reset=0)
        if res.get("link"):
            return res["link"]
    except Exception as e:
        print(f"Не удалось получить ссылку на беседу {chat_peer}: {err_text(e)}")
    return REF_CHAT_LINK or None

def handle_ref_start(msg):
    """Личка: человек перешёл по реф-ссылке. Возвращает True, если сообщение было реф-переходом."""
    m = REF_RE.match((msg.get("ref") or "").strip())
    if not m:
        return False
    uid = msg["from_id"]
    peer_id = msg["peer_id"]
    referrer, chat_peer = int(m.group(1)), CHAT_OFFSET + int(m.group(2))

    if referrer == uid:
        send(peer_id, "⚠ Это ваша собственная реферальная ссылка — по ней нельзя приглашать себя. Отправьте её другу!")
        return True
    if str(referrer) not in economy["users"]:
        send(peer_id, "❌ Эта реферальная ссылка недействительна.")
        return True

    rec = economy["refs"].get(str(uid))
    if rec and rec.get("paid"):
        send(peer_id, "ℹ️ Вы уже приходили по приглашению — повторно награда за вас не выдаётся.")
        return True
    if not ref_is_newcomer(chat_peer, uid, rec):
        print(f"[реф] {uid} уже писал в беседе {chat_peer} — награда за приглашение не положена")
        send(peer_id, "ℹ️ Вы уже есть в этой беседе (писали в ней раньше) — награда за приглашение выдаётся только новичкам.")
        return True
    fresh = rec and not rec.get("paid") and time.time() - rec.get("t", 0) < REF_PENDING_TTL
    if not fresh:       # первый пригласивший остаётся за человеком, пока приглашение не сгорело
        economy["refs"][str(uid)] = {"ref": referrer, "peer": chat_peer, "t": time.time(), "paid": False}
        save_economy()
        rec = economy["refs"][str(uid)]

    names = get_names([rec["ref"]])
    link = get_chat_invite_link(rec["peer"])
    lines = [f"👋 Вас пригласил {mention(rec['ref'], names)}!", ""]
    if link:
        lines += [f"Заходите в беседу: {link}",
                  f"Когда вы зайдёте, вы оба получите {fmt_num(REF_REWARD)} 💰 и {REF_EXP} exp: и вы, и пригласивший."]
    else:
        lines += ["Беседу не удалось открыть автоматически — попросите пригласившего прислать ссылку-приглашение."]
    send(peer_id, "\n".join(lines))
    return True

def ref_is_newcomer(chat_peer, uid, rec=None):
    """Новичок беседы: в этой беседе ещё не писал (или первое сообщение было уже ПОСЛЕ перехода по ссылке)."""
    st = stats.get(str(chat_peer), {}).get(str(uid))
    if not st:
        return True
    return bool(rec) and st.get("first", 0) >= rec.get("t", 0) - 60

def check_referral_join(peer_id, uid):
    """Человек зашёл в беседу (или написал в ней первое сообщение): если он пришёл по реф-ссылке именно в эту
    беседу — награда и пригласившему, и ему самому (деньги + опыт)."""
    rec = economy["refs"].get(str(uid))
    if not rec or rec.get("paid") or rec.get("peer") != peer_id:
        return
    if time.time() - rec.get("t", 0) > REF_PENDING_TTL:
        del economy["refs"][str(uid)]       # приглашение сгорело
        save_economy()
        return
    referrer = rec["ref"]
    if referrer == uid:
        return
    if not ref_is_newcomer(peer_id, uid, rec):   # уже писал в этой беседе до перехода по ссылке — не новичок
        print(f"[реф] {uid} уже писал в беседе {peer_id} — награда за приглашение не выдана")
        return
    get_user(referrer)["money"] += REF_REWARD
    get_user(uid)["money"] += REF_INVITEE_REWARD
    level_notes = [add_exp(referrer, REF_EXP), add_exp(uid, REF_EXP)]
    rec["paid"] = True
    rec["paid_t"] = time.time()
    rec["amount"] = REF_REWARD
    rec["exp_amount"] = REF_EXP
    save_economy()
    log_action(peer_id, referrer, f"реферал: +{REF_REWARD} и {REF_EXP} exp за приглашение {uid} (ему тоже +{REF_INVITEE_REWARD}, {REF_EXP} exp)")
    names = get_names([uid, referrer])
    lines = [f"🎉 {mention(uid, names)} зашёл(ла) в беседу по приглашению {mention(referrer, names)}!",
             f"+{fmt_num(REF_REWARD)} 💰 и +{REF_EXP} exp — {mention(referrer, names)} (пригласил)",
             f"+{fmt_num(REF_INVITEE_REWARD)} 💰 и +{REF_EXP} exp — {mention(uid, names)} (зашёл)"]
    for who, note in zip((referrer, uid), level_notes):
        if note:
            lines += ["", f"{mention(who, names)}: {note}"]
    try:
        send(peer_id, "\n".join(lines))
    except Exception as e:
        print(f"Не удалось отправить сообщение о реферале: {err_text(e)}")
