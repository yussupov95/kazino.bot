# -*- coding: utf-8 -*-
"""Биткоин: авто-курс, графики, купить / продать."""
import math
import os
import random
import re
import time
from decimal import Decimal

from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from auction import AUC_BIZ_WORDS, AUC_CHAR_WORDS, auction_sell
from config import (
    BTC_ACTIVE_DAYS, BTC_AUTO_MAX_RATE, BTC_CATCHUP_MAX, BTC_DEPTH_SHARE, BTC_ECON_SMOOTH,
    BTC_EVENT_CHANCE, BTC_HEAT_GAIN, BTC_HEAT_HIGH, BTC_HEAT_LOW, BTC_HIST_MAX, BTC_IMAGE,
    BTC_IMPACT_K, BTC_IMPACT_MAX, BTC_MAX_RATE, BTC_MIN_DEPTH, BTC_MIN_RATE, BTC_MOMENTUM,
    BTC_MOOD_DRIFT, BTC_MOODS, BTC_NEWS_DOWN, BTC_NEWS_TTL, BTC_NEWS_UP, BTC_PLAYERS_ELASTICITY,
    BTC_REVERT, BTC_STEP_MAX, BTC_TICK_SECONDS, BTC_UNIT, BTC_VOLATILITY, BTC_WEALTH_ELASTICITY,
    BTC_WORDS, BUSINESSES, err_text, _n, OWNER_AMOUNT_RE, OWNER_ID, VIP_DAYS, VIP_PRICE,
)
from database import economy, get_user, save_economy, stats, vip_active
from helpers import fmt_duration, fmt_num, fmt_time, parse_amount, send
from images import cached_photo
from logs import log_action
from player import vip_benefits


# ---------- Биткоин ----------
# Курс живёт сам: раз в BTC_TICK_SECONDS бот пересчитывает его по экономике игры (btc_step):
#   • «справедливая» цена растёт, когда игроки богатеют и их становится больше, и падает, когда они беднеют/уходят;
#   • если слишком много богатства лежит в ₿ — рынок перегрет и остывает, если почти нет — дешёвый и греется;
#   • сверху — настроение рынка (быки/медведи), инерция, случайный шум и редкие «новости»;
#   • покупки и продажи игроков двигают курс сразу (крупная сделка — заметно, мелкая — почти нет).
# Игрокам это выглядит как самостоятельное движение рынка: стрелка, % к прошлому курсу, график за сутки.
# Владелец (секретная команда в личке) может вручную поставить курс или заморозить авто-рынок.
def fmt_btc(units):
    """150000000 → «1,5»; 50000000 → «0,5»."""
    return format((Decimal(units) / BTC_UNIT).normalize(), "f").replace(".", ",")

def short_money(n):
    """1000000000 → «1000кк», 450000000 → «450кк», 52400000 → «52,4кк», 1500 → «1.500»."""
    if n >= 10 ** 6:
        v = n / 10 ** 6
        s = f"{v:.0f}" if v >= 100 else f"{v:.1f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") + "кк"
    if n >= 1000 and n % 1000 == 0:
        return f"{n // 1000}к"
    return _n(n)

def btc_pct(new, old):
    return f"{abs(new - old) * 100 / old:.1f}".replace(".", ",")

def btc_change(new, old):
    if new > old:
        return f"📈 +{btc_pct(new, old)}%"
    if new < old:
        return f"📉 −{btc_pct(new, old)}%"
    return "➖ без изменений"

def btc_trend(b):
    rate, prev = b["rate"], b.get("prev") or b["rate"]
    ch = btc_change(rate, prev)
    return f"{ch} (было {short_money(prev)})" if rate != prev else ch

def btc_attachment(peer_id):
    return cached_photo(peer_id, BTC_IMAGE, "bitcoin") if os.path.exists(BTC_IMAGE) else None

# ---------- авто-рынок: экономика → справедливая цена → шаг курса ----------
def _round_rate(x):
    """Курс при пересчёте округляется до 4 значащих цифр: 1.003.000.000, а не 1.003.482.191."""
    x = max(1, int(x))
    digits = len(str(x))
    if digits > 4:
        step = 10 ** (digits - 4)
        x = int(round(x / step)) * step
    return x

def btc_bounds(rate):
    """Пол и потолок авто-курса (если владелец поставил курс за их пределами — он остаётся допустимым)."""
    return min(BTC_MIN_RATE, rate), max(BTC_AUTO_MAX_RATE, rate)

def btc_net_worth(user, rate):
    """Капитал игрока: деньги + бизнесы (по цене покупки) + биткоины по курсу."""
    worth = max(0, user.get("money", 0)) + user.get("btc", 0) * rate // BTC_UNIT
    for k in user.get("biz") or {}:
        if k in BUSINESSES:
            worth += BUSINESSES[k]["price"]
    return worth

def btc_snapshot(rate):
    """Срез экономики: сколько активных игроков, их средний капитал (без верхних 10% — один богач не перекашивает курс),
    общий капитал и доля богатства, лежащая в биткоинах. Владелец не считается. None — игроков нет."""
    since = time.time() - BTC_ACTIVE_DAYS * 86400
    seen = {}
    for chat in stats.values():
        for uid, s in chat.items():
            seen[uid] = max(seen.get(uid, 0), s.get("last") or 0)
    owner = str(OWNER_ID)
    players = [u for uid, u in economy["users"].items() if uid != owner]
    active = [u for uid, u in economy["users"].items()
              if uid != owner and max(seen.get(uid, 0), u.get("last_bonus") or 0) >= since]
    rows = active or players            # никто не заходил неделю — считаем по всем
    if not rows:
        return None
    worths = sorted(btc_net_worth(u, rate) for u in rows)
    held = sum(u.get("btc", 0) * rate // BTC_UNIT for u in rows)
    kept = worths[:max(1, int(len(worths) * 0.9))]
    total = sum(worths)
    return {"n": len(rows), "w": sum(kept) // len(kept), "total": total, "h": (held / total) if total else 0.0}

def btc_set_anchor(b, snap):
    """Запоминает, при какой экономике текущий курс считается «справедливым» — дальше рынок считает от него."""
    if snap:
        b.update(base_rate=b["rate"], base_w=max(snap["w"], 1), base_n=max(snap["n"], 1),
                 w_ema=snap["w"], n_ema=snap["n"])

def btc_fair_rate(b):
    """Справедливая цена по экономике: растёт вместе с капиталом и числом активных игроков."""
    w = max(b.get("w_ema") or 1, 1) / b["base_w"]
    n = max(b.get("n_ema") or 1, 1) / b["base_n"]
    return b["base_rate"] * w ** BTC_WEALTH_ELASTICITY * n ** BTC_PLAYERS_ELASTICITY

def btc_pick_mood(dev):
    """Новое настроение рынка. dev > 0 — курс выше «справедливого»: падение вероятнее, и наоборот."""
    bear = min(0.6, max(0.1, 0.30 + 1.5 * dev))
    bull = min(0.6, max(0.1, 0.30 - 1.5 * dev))
    return random.choices(("bull", "bear", "flat"), weights=(bull, bear, max(0.1, 1 - bull - bear)))[0]

def btc_step(b, snap, now):
    """Один пересчёт курса. Складывается из: притяжения к цене по экономике, перегрева/недооценки,
    настроения рынка, инерции, случайного шума и редких новостей."""
    rate = b["rate"]
    prev = b.get("tick_rate") or rate
    dev = revert = heat = 0.0
    fair = None
    if snap:
        if not b.get("base_w"):
            btc_set_anchor(b, snap)
        b["w_ema"] += BTC_ECON_SMOOTH * (snap["w"] - b["w_ema"])
        b["n_ema"] += BTC_ECON_SMOOTH * (snap["n"] - b["n_ema"])
        fair = btc_fair_rate(b)
        dev = math.log(rate / fair)                                  # > 0 — курс выше справедливого
        revert = -BTC_REVERT * dev * (1 + (dev / 0.6) ** 2)          # чем дальше от нормы, тем сильнее тянет назад
        h = snap["h"]                                                # доля капитала игроков, лежащая в ₿
        heat = (-BTC_HEAT_GAIN * (h - BTC_HEAT_HIGH) if h > BTC_HEAT_HIGH          # перегрев охлаждает,
                else BTC_HEAT_GAIN * (BTC_HEAT_LOW - h) if h < BTC_HEAT_LOW else 0.0)   # недооценка греет

    b["mood_left"] = b.get("mood_left", 0) - 1
    if b["mood_left"] <= 0 or b.get("mood") not in ("bull", "bear", "flat"):
        b["mood"], b["mood_left"] = btc_pick_mood(dev), random.randint(6, 36)
    drift = {"bull": BTC_MOOD_DRIFT, "bear": -BTC_MOOD_DRIFT}.get(b["mood"], 0.0)
    momentum = BTC_MOMENTUM * max(-0.05, min(0.05, b.get("ret", 0.0)))
    noise = random.gauss(0, BTC_VOLATILITY)

    jump = 0.0
    if random.random() < BTC_EVENT_CHANCE:                           # «новость»: резкий скачок
        up = random.random() < min(0.8, max(0.2, 0.5 - 1.5 * dev))   # дорогой курс чаще роняют, дешёвый — поднимают
        size = random.uniform(0.07, 0.14) if random.random() < 0.3 else random.uniform(0.025, 0.06)
        jump = size if up else -size
        b["news"] = {"t": int(now), "up": up, "text": random.choice(BTC_NEWS_UP if up else BTC_NEWS_DOWN)}

    change = max(-BTC_STEP_MAX, min(BTC_STEP_MAX, revert + heat + drift + momentum + noise + jump))
    lo, hi = btc_bounds(rate)
    new = max(lo, min(hi, _round_rate(rate * math.exp(change))))

    b["prev"], b["rate"], b["tick_rate"], b["t"] = prev, new, new, int(now)
    b["ret"] = math.log(new / prev)
    b["fair"], b["dev"] = (int(fair) if fair else 0), round(dev, 4)
    hist = b.setdefault("hist", [])
    if not hist:
        hist.append([int(now) - BTC_TICK_SECONDS, prev])
    hist.append([int(now), new])
    del hist[:-BTC_HIST_MAX]

def btc_market_step():
    """Раз в BTC_TICK_SECONDS пересчитывает курс (если владелец не выключил авто-рынок).
    Бот был выключен — «догоняет» пропущенные обновления (не больше BTC_CATCHUP_MAX)."""
    b = economy["btc"]
    now = time.time()
    last = b.get("tick_t") or 0
    if not b.get("auto", True) or now - last < BTC_TICK_SECONDS:
        return
    due = int((now - last) // BTC_TICK_SECONDS) if last else 1
    steps = max(1, min(due, BTC_CATCHUP_MAX))
    snap = btc_snapshot(b["rate"])
    for i in range(steps):
        btc_step(b, snap, now - (steps - 1 - i) * BTC_TICK_SECONDS)
    b["tick_t"] = int(now)
    if snap:
        b["snap"] = {"n": snap["n"], "w": snap["w"], "total": snap["total"], "h": round(snap["h"], 4), "t": int(now)}
    else:
        b.pop("snap", None)
    save_economy()

def check_btc_market():
    """Вызывается из tick_loop каждую секунду; сам решает, пора ли пересчитывать курс."""
    try:
        btc_market_step()
    except Exception as e:
        economy["btc"]["tick_t"] = int(time.time())     # чтобы ошибка не повторялась каждую секунду
        print(f"Ошибка рынка биткоина: {err_text(e)}")

def btc_depth():
    """«Глубина» рынка: чем больше капитал игроков, тем труднее сдвинуть курс одной сделкой."""
    total = (economy["btc"].get("snap") or {}).get("total", 0)
    return max(BTC_MIN_DEPTH, int(total * BTC_DEPTH_SHARE))

def btc_impact(money):
    """На сколько (в логарифмах) сделка на сумму money сдвигает курс: крупная — заметно, мелкая — почти нет."""
    return min(BTC_IMPACT_MAX, BTC_IMPACT_K * math.log1p(money / btc_depth()))

# ---------- как это видит игрок ----------
def btc_chart(b, points=14):
    """График курса за сутки одной строкой: ▁▂▃▅▇."""
    cut = time.time() - 86400
    vals = [r for t, r in b.get("hist", []) if t >= cut] + [b["rate"]]
    if len(vals) < 4:
        return ""
    if len(vals) > points:
        vals = [vals[round(i * (len(vals) - 1) / (points - 1))] for i in range(points)]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return "▄" * len(vals)
    return "".join("▁▂▃▄▅▆▇█"[round((v - lo) * 7 / (hi - lo))] for v in vals)

def btc_day_line(b):
    """«За 24 ч: 📉 −3,4% · мин 950кк · макс 1040кк»; пока истории мало — пусто."""
    now = time.time()
    pts = [(t, r) for t, r in b.get("hist", []) if t >= now - 86400]
    if len(pts) < 4:
        return None
    rates = [r for _, r in pts] + [b["rate"]]
    span = now - pts[0][0]
    label = "24 ч" if span >= 23 * 3600 else f"{max(1, round(span / 3600))} ч"
    return (f"За {label}: {btc_change(b['rate'], rates[0])} · "
            f"мин {short_money(min(rates))} · макс {short_money(max(rates))}")

def cmd_btc(msg, rest, slash):
    """«бит» / «курс бит»: курс биткоина, динамика, график, новости и запас игрока (с картинкой)."""
    peer_id = msg["peer_id"]
    user = get_user(msg["from_id"])
    b = economy["btc"]
    now = time.time()
    own = user.get("btc", 0)
    auto = b.get("auto", True)
    lines = ["₿ Биткоин", "",
             f"Курс: 1 ₿ = {fmt_num(b['rate'])} 💰 ({short_money(b['rate'])})",
             btc_trend(b)]
    day = btc_day_line(b)
    if day:
        lines.append(day)
    chart = btc_chart(b)
    if chart:
        lines.append(f"📊 {chart}")
    if auto and b.get("mood") in BTC_MOODS and b.get("tick_t"):
        lines.append(BTC_MOODS[b["mood"]])
    news = b.get("news")
    if news and now - news.get("t", 0) < BTC_NEWS_TTL:
        lines.append(f"📰 {news['text']}")
    snap = b.get("snap")
    if snap:
        lines.append(f"🌍 Активных игроков: {snap['n']} · средний капитал: {short_money(int(snap['w']))} · "
                     f"в ₿ лежит {snap['h'] * 100:.0f}% капитала")
    if b.get("t"):
        upd = f"🕒 Обновлён: {fmt_time(b['t'])}"
        if auto and b.get("tick_t"):
            left = max(0, b["tick_t"] + BTC_TICK_SECONDS - now)
            upd += f" · следующее через {fmt_duration(left)}"
        lines.append(upd)
    lines += ["", f"У вас: {fmt_btc(own)} ₿" + (f" ≈ {fmt_num(own * b['rate'] // BTC_UNIT)} 💰" if own else ""),
              f"Баланс: {fmt_num(user['money'])} 💰", "",
              "Купить: «купить бит» (1 ₿) или «купить бит 0,5»",
              "Продать: «продать бит» (1 ₿), «продать бит 0,5» или «продать бит все»"]
    send(peer_id, "\n".join(lines), attachment=btc_attachment(peer_id))

def parse_btc_qty(arg):
    """«» → 1 ₿; «1», «0,5», «0.25» → сатоши. None — не число / ноль / больше 8 знаков после запятой."""
    t = arg.strip().lower().replace(",", ".")
    if not t:
        return BTC_UNIT
    if not re.fullmatch(r"\d{1,12}(?:\.\d{1,8})?", t):
        return None
    units = int(Decimal(t) * BTC_UNIT)
    return units if units > 0 else None

def btc_trade(msg, arg, sell):
    """Покупка / продажа. Без количества — 1 ₿; при продаже «все» — весь запас.
    Крупная сделка двигает курс (покупка — вверх, продажа — вниз) и исполняется по средней цене между «до» и «после»:
    купить и сразу продать с выгодой нельзя."""
    peer_id, uid = msg["peer_id"], msg["from_id"]
    user = get_user(uid)
    b = economy["btc"]
    rate = b["rate"]
    word = arg.strip().lower().replace("ё", "е")
    have = user.get("btc", 0)
    if sell and word in ("все", "all"):
        units = have
        if units <= 0:
            send(peer_id, "⚠ У вас нет биткоинов.")
            return
    else:
        units = parse_btc_qty(word)
        if units is None:
            cmd = "продать" if sell else "купить"
            send(peer_id, f"ℹ️ Укажите количество числом: «{cmd} бит 1» или «{cmd} бит 0,5» "
                          f"(до 8 знаков после запятой){', «продать бит все» — весь запас' if sell else ''}.")
            return
    shift = btc_impact(rate * units // BTC_UNIT)                         # на сколько сделка сдвинет курс
    avg = int(math.exp((-shift if sell else shift) / 2) * 10 ** 9)      # средняя цена сделки к курсу (×10⁹, без float-ошибок)
    if sell:
        if have < units:
            send(peer_id, f"⚠ Недостаточно биткоинов. У вас: {fmt_btc(have)} ₿")
            return
        money = rate * units * avg // (BTC_UNIT * 10 ** 9)
        if money < 1:
            send(peer_id, "⚠ Слишком маленькое количество.")
            return
        user["btc"] = have - units
        user["money"] += money
        new_rate = rate * math.exp(-shift)
        head = f"🔴 Продано: {fmt_btc(units)} ₿ за {fmt_num(money)} 💰"
    else:
        money = -(-rate * units * avg // (BTC_UNIT * 10 ** 9))          # покупка округляется вверх, продажа — вниз
        if user["money"] < money:
            send(peer_id, f"⚠ Недостаточно денег: {fmt_btc(units)} ₿ стоит {fmt_num(money)} 💰, "
                          f"у вас {fmt_num(user['money'])} 💰")
            return
        user["money"] -= money
        user["btc"] = have + units
        new_rate = rate * math.exp(shift)
        head = f"🟢 Куплено: {fmt_btc(units)} ₿ за {fmt_num(money)} 💰"
    lo, hi = btc_bounds(rate)
    b["rate"] = max(lo, min(hi, int(new_rate)))
    save_economy()
    log_action(peer_id, uid, f"{'продал' if sell else 'купил'} {fmt_btc(units)} BTC за {money} (курс {rate})")
    if shift >= 0.001 and b["rate"] != rate:
        rate_line = f"Курс после сделки: 1 ₿ = {short_money(b['rate'])} ({btc_change(b['rate'], rate)})"
    else:
        rate_line = f"Курс: 1 ₿ = {short_money(b['rate'])}"
    send(peer_id, f"{head}\n{rate_line}\n"
                  f"У вас: {fmt_btc(user.get('btc', 0))} ₿ · Баланс: {fmt_num(user['money'])} 💰")

def cmd_sell(msg, rest, slash):
    words = rest.strip().lower().replace("ё", "е").split()
    if words and words[0] in AUC_CHAR_WORDS:           # продать перс ID СУММА → аукцион
        auction_sell(msg, "char", words[1:])
        return
    if words and words[0] in AUC_BIZ_WORDS:            # продать бизнес НАЗВАНИЕ СУММА → аукцион
        auction_sell(msg, "biz", words[1:])
        return
    if not words or words[0] not in BTC_WORDS:
        if slash or not words:
            send(msg["peer_id"], "ℹ️ Доступно: продать бит [КОЛИЧЕСТВО | все], продать перс ID СУММА, "
                                 "продать бизнес НАЗВАНИЕ СУММА")
        return
    btc_trade(msg, words[1] if len(words) > 1 else "", sell=True)

def owner_btc_status(b):
    """Подробности авто-рынка — только владельцу."""
    now = time.time()
    lines = [f"₿ Авто-рынок: {'ВКЛ' if b.get('auto', True) else 'ВЫКЛ'}",
             f"Курс: {short_money(b['rate'])}"]
    if b.get("fair"):
        lines.append(f"По экономике: ≈ {short_money(b['fair'])} (курс {'выше' if b.get('dev', 0) > 0 else 'ниже'} на "
                     f"{abs(b.get('dev', 0)) * 100:.1f}%)".replace(".", ","))
    if b.get("mood") in BTC_MOODS:
        lines.append(f"Настроение: {BTC_MOODS[b['mood']]} (ещё ~{max(0, b.get('mood_left', 0))} обн.)")
    snap = b.get("snap")
    if snap:
        lines.append(f"Игроков: {snap['n']} · средний капитал: {short_money(int(snap['w']))} · "
                     f"всего: {short_money(int(snap['total']))} · в ₿: {snap['h'] * 100:.0f}%")
    if b.get("tick_t") and b.get("auto", True):
        lines.append(f"Обновление раз в {BTC_TICK_SECONDS // 60} мин, следующее через "
                     f"{fmt_duration(max(0, b['tick_t'] + BTC_TICK_SECONDS - now))}")
    lines += ["", "Вручную: «курс бит 900кк». Заморозить: «курс бит авто выкл», вернуть: «курс бит авто вкл»."]
    return "\n".join(lines)

def owner_btc_command(msg, text):
    """СЕКРЕТ, только личка владельца: «курс бит 900кк» (или «курс бит из 1000кк до 900кк») ставит курс,
    «курс бит авто» — состояние рынка, «курс бит авто выкл/вкл» — заморозить/вернуть авто-рынок.
    Нигде не упоминается в справках и не пишется в логи. True — сообщение обработано."""
    words = text.lower().replace("ё", "е").split()
    if len(words) < 2 or words[0] not in ("курс", "rate") or words[1] not in BTC_WORDS:
        return False
    peer_id = msg["peer_id"]
    b = economy["btc"]
    if len(words) >= 3 and words[2] in ("авто", "auto"):
        arg = words[3] if len(words) > 3 else ""
        if arg in ("выкл", "off", "стоп"):
            b["auto"] = False
            save_economy()
            send(peer_id, "⏸ Авто-рынок выключен: курс стоит, пока вы не включите его («курс бит авто вкл»).")
        elif arg in ("вкл", "on", "старт"):
            b["auto"], b["tick_t"] = True, int(time.time())
            save_economy()
            send(peer_id, f"▶️ Авто-рынок включён: курс пересчитывается раз в {BTC_TICK_SECONDS // 60} мин.")
        else:
            send(peer_id, owner_btc_status(b))
        return True
    amounts = [a for a in (parse_amount(w, regex=OWNER_AMOUNT_RE) for w in words[2:]) if a]
    if not amounts:
        send(peer_id, owner_btc_status(b))
        return True
    new, old = amounts[-1], b["rate"]
    if not 1 <= new <= BTC_MAX_RATE:
        send(peer_id, f"⚠ Курс — от 1 до {fmt_num(BTC_MAX_RATE)} 💰")
        return True
    if new == old:
        send(peer_id, f"ℹ️ Курс уже {short_money(old)}.")
        return True
    now = int(time.time())
    b["prev"], b["rate"], b["t"] = old, new, now
    b["tick_rate"], b["tick_t"] = new, now                    # следующий авто-пересчёт — через полный интервал
    b["ret"] = max(-0.05, min(0.05, math.log(new / old)))     # ручной скачок даёт рынку инерцию
    btc_set_anchor(b, btc_snapshot(new))                      # новый курс — новая «справедливая» цена для текущей экономики
    hist = b.setdefault("hist", [])
    hist.append([now, new])
    del hist[:-BTC_HIST_MAX]
    save_economy()
    note = "Авто-рынок продолжит от этого курса." if b.get("auto", True) else "Авто-рынок выключен — курс стоит."
    send(peer_id, f"✅ Курс биткоина: {short_money(old)} → {short_money(new)} "
                  f"({'+' if new > old else '−'}{btc_pct(new, old)}%)\n{note}")
    return True

# ---------- Опыт, VIP, префикс ----------
def cmd_buy(msg, rest, slash):
    peer_id = msg["peer_id"]
    uid = msg["from_id"]
    item = rest.strip().lower()
    words = item.replace("ё", "е").split()
    if words and words[0] in BTC_WORDS:
        btc_trade(msg, words[1] if len(words) > 1 else "", sell=False)
        return
    if item not in ("вип", "vip"):
        if slash or not item:
            send(peer_id, "ℹ️ Доступно: купить вип, купить бит")
        return

    user = get_user(uid)
    active = vip_active(user)
    if active:
        head = (f"✨ Продление VIP\nСейчас действует до {fmt_time(user['vip_until'])}\n"
                f"Продление: +{VIP_DAYS} дней")
        question = "Вы точно хотите продлить услугу VIP?"
        button = "✅ Продлить"
    else:
        head = "✨ Услуга VIP"
        question = "Вы точно хотите приобрести услугу VIP?"
        button = "✅ Купить"

    kb = VkKeyboard(inline=True)
    kb.add_callback_button(button, VkKeyboardColor.POSITIVE, {"cmd": "vip", "act": "yes", "o": uid})
    kb.add_callback_button("❌ Отмена", VkKeyboardColor.NEGATIVE, {"cmd": "vip", "act": "no", "o": uid})
    send(peer_id,
         f"{head}\n"
         f"Цена: {fmt_num(VIP_PRICE)} 💰 на {VIP_DAYS} дней\n"
         f"Ваш баланс: {fmt_num(user['money'])} 💰\n\n"
         f"Преимущества VIP:\n{vip_benefits()}\n\n"
         f"{question}",
         kb.get_keyboard())
