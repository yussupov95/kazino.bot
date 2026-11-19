# -*- coding: utf-8 -*-
"""База данных SQLite (bot.db): таблицы, сохранение, роли, муты и баны, данные игроков."""
import json
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime

from config import (
    BACKUP_DIR, BACKUP_KEEP, BTC_START_RATE, DAILY_FILE, DATA_FILE, DB_FILE, DEPUTY_AS_LEVEL,
    DEPUTY_LEVEL, ECONOMY_FILE,
    err_text, LOGS_DIR, OWNER_ID, PLAYER_LEVELS, PROMO_TTL, PUNISH_FILE, STATS_FILE,
    STATS_SAVE_INTERVAL, VIP_DAYS, VIP_PREFIX,
)


# ---------- Хранилища ----------
def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path, obj, indent=2):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)

# ---------- База данных (SQLite) ----------
# Данные по-прежнему лежат в памяти в тех же словарях (data, stats, economy, punish, daily), чтобы
# логика бота не менялась, но хранятся в базе bot.db: каждая сущность — отдельная строка таблицы.
# При сохранении записываются ТОЛЬКО изменившиеся строки, одной транзакцией (WAL), поэтому
# обрыв питания или сбой не портят файл целиком, как это бывало с JSON.
DB_LOCK = threading.RLock()
db = None
_MAX_INT = 2 ** 63 - 1

def _i(v):
    return None if v is None else max(-_MAX_INT, min(_MAX_INT, int(v)))

def _r(v):
    return None if v is None else float(v)

def _t(v):
    return None if v is None else str(v)

def _b(v):
    return None if v is None else int(bool(v))

def _j(v):
    return None if v is None else json.dumps(v, ensure_ascii=False)

# вид поля: (в базу, из базы)
_CONV = {
    "i": (_i, int),
    "r": (_r, float),
    "t": (_t, str),
    "b": (_b, bool),
    "j": (_j, json.loads),
}

class Table:
    def __init__(self, name, group, keys, vals, flatten, load):
        self.name, self.group = name, group
        self.keys, self.vals = keys, vals       # [(колонка, тип SQL)]
        self.flatten, self.load = flatten, load  # память → строки, строки → память
        self.snapshot = {}                       # что уже записано в базу

    def create_sql(self):
        cols = ", ".join(f"{c} {t}" for c, t in self.keys + self.vals)
        pk = ", ".join(c for c, _ in self.keys)
        return f"CREATE TABLE IF NOT EXISTS {self.name} ({cols}, PRIMARY KEY ({pk}))"

def _entity(name, group, store, key_col, key_int, fields, skip=(), key_field=None):
    """Таблица «одна запись = одна строка»: известные поля — колонки, остальные — в JSON-колонке extra."""
    known = {f[0] for f in fields} | set(skip) | ({key_field} if key_field else set())
    vals = [(col, typ) for _, col, typ, _ in fields] + [("extra", "TEXT")]

    def flatten():
        rows = {}
        for k, rec in store().items():
            key = (int(k) if key_int else str(k),)
            row = tuple(_CONV[kind][0](rec.get(dk)) for dk, _, _, kind in fields)
            extra = {x: y for x, y in rec.items() if x not in known}
            rows[key] = row + (_j(extra) if extra else None,)
        return rows

    def load(rows):
        st = store()
        for r in rows:
            rec = {}
            for (dk, _, _, kind), v in zip(fields, r[1:-1]):
                if v is not None:
                    rec[dk] = _CONV[kind][1](v)
            if r[-1]:
                rec.update(json.loads(r[-1]))
            if key_field:
                rec[key_field] = r[0]
            st[str(r[0])] = rec

    return Table(name, group, [(key_col, "INTEGER" if key_int else "TEXT")], vals, flatten, load)
def _pairs(name, group, store, vals, to_row, from_row):
    """Двухуровневый словарь {беседа: {пользователь: значение}} → строки (peer_id, user_id, ...)."""
    def flatten():
        rows = {}
        for p, d in store().items():
            for u, v in d.items():
                rows[(int(p), int(u))] = to_row(v)
        return rows

    def load(rows):
        st = store()
        for r in rows:
            st.setdefault(str(r[0]), {})[str(r[1])] = from_row(r[2:])

    return Table(name, group, [("peer_id", "INTEGER"), ("user_id", "INTEGER")], vals, flatten, load)

def _singles(name, group, store, key_col, key_type, val_col, val_type, to_db, from_db):
    """Словарь {ключ: значение} → строки (ключ, значение)."""
    def flatten():
        return {((int(k) if key_type == "INTEGER" else str(k)),): (to_db(v),) for k, v in store().items()}

    def load(rows):
        st = store()
        for r in rows:
            st[str(r[0])] = from_db(r[1])

    return Table(name, group, [(key_col, key_type)], [(val_col, val_type)], flatten, load)

def _build_tables():
    users_f = [("money", "money", "INTEGER", "i"), ("exp", "exp", "INTEGER", "i"),
               ("last_bonus", "last_bonus", "REAL", "r"), ("vip", "vip", "INTEGER", "b"),
               ("vip_until", "vip_until", "REAL", "r"), ("prefix", "prefix", "TEXT", "t"),
               ("last_transfer", "last_transfer", "REAL", "r"), ("last_report", "last_report", "REAL", "r"),
               ("last_fish", "last_fish", "REAL", "r"), ("fish_n", "fish_n", "INTEGER", "i"),
               ("fish_sum", "fish_sum", "INTEGER", "i"), ("reg", "registered", "REAL", "r"),
               ("rep", "reputation", "INTEGER", "i"), ("last_rep", "last_rep", "REAL", "r")]
    promos_f = [("name", "name", "TEXT", "t"), ("amount", "amount", "INTEGER", "i"),
                ("uses", "uses", "INTEGER", "i"), ("by", "by_user", "INTEGER", "i"), ("t", "created", "INTEGER", "i"),
                ("exp", "expires", "REAL", "r")]
    games_f = [("owner", "owner", "INTEGER", "i"), ("bet", "bet", "INTEGER", "i"), ("m", "mines_count", "INTEGER", "i"),
               ("mines", "mines_json", "TEXT", "j"), ("opened", "opened_json", "TEXT", "j"),
               ("done", "done", "INTEGER", "b"), ("t", "created", "REAL", "r"), ("peer", "peer", "INTEGER", "i"),
               ("cmid", "cmid", "INTEGER", "i"), ("shown", "shown", "INTEGER", "b"), ("v", "version", "INTEGER", "i")]
    duels_f = [("a", "a_user", "INTEGER", "i"), ("b", "b_user", "INTEGER", "i"), ("bet", "bet", "INTEGER", "i"),
               ("status", "status", "TEXT", "t"), ("t", "created", "REAL", "r"), ("peer", "peer", "INTEGER", "i"),
               ("cmid", "cmid", "INTEGER", "i"), ("barrel", "barrel_json", "TEXT", "j"), ("pos", "pos", "INTEGER", "i"),
               ("bullets", "bullets", "INTEGER", "i"), ("turn", "turn", "INTEGER", "i"),
               ("deadline", "deadline", "REAL", "r"), ("acc_t", "accepted", "REAL", "r"),
               ("shown", "shown", "INTEGER", "b")]
    reports_f = [("uid", "user_id", "INTEGER", "i"), ("text", "text", "TEXT", "t"), ("t", "created", "INTEGER", "i"),
                 ("status", "status", "TEXT", "t"), ("reward", "reward_json", "TEXT", "j")]
    appr_f = [("kind", "kind", "TEXT", "t"), ("peer", "peer", "INTEGER", "i"), ("actor", "actor", "INTEGER", "i"),
              ("data", "data_json", "TEXT", "j"), ("summary", "summary", "TEXT", "t"),
              ("status", "status", "TEXT", "t"), ("t", "created", "INTEGER", "i")]
    roul_f = [("peer", "peer", "INTEGER", "i"), ("cmid", "cmid", "INTEGER", "i"), ("uid", "user_id", "INTEGER", "i"),
              ("bet", "bet", "INTEGER", "i"), ("t", "bet_type", "TEXT", "t"), ("n", "number", "INTEGER", "i"),
              ("att", "attachment", "TEXT", "t"), ("reveal_at", "reveal_at", "REAL", "r"),
              ("done", "done", "INTEGER", "b"), ("ts", "created", "INTEGER", "i"),
              ("shown", "shown", "INTEGER", "b"), ("paid", "paid", "INTEGER", "b"),
              ("tries", "tries", "INTEGER", "i"), ("win", "win", "INTEGER", "b"),
              ("payout", "payout", "INTEGER", "i"), ("retry_at", "retry_at", "REAL", "r")]
    rmode_f = [("until", "until", "REAL", "r"), ("left", "uses_left", "INTEGER", "i")]
    auction_f = [("kind", "kind", "TEXT", "t"), ("item", "item", "TEXT", "t"), ("seller", "seller", "INTEGER", "i"),
                 ("price", "price", "INTEGER", "i"), ("t", "created", "REAL", "r")]
    refs_f = [("ref", "referrer", "INTEGER", "i"), ("peer", "peer", "INTEGER", "i"),
              ("t", "created", "REAL", "r"), ("paid", "paid", "INTEGER", "b"),
              ("paid_t", "paid_at", "REAL", "r"), ("amount", "amount", "INTEGER", "i")]

    donate_f = [("uid", "user_id", "INTEGER", "i"), ("item", "item", "TEXT", "t"), ("price", "price", "INTEGER", "i"),
                ("status", "status", "TEXT", "t"), ("t", "created", "REAL", "r"), ("peer", "peer", "INTEGER", "i"),
                ("cmid", "cmid", "INTEGER", "i"), ("data", "data", "TEXT", "t")]

    def econ(key):
        return lambda: economy.setdefault(key, {})

    def punished(key):
        return lambda: punish.setdefault(key, {})

    # --- списки внутри словарей ---
    def warns_flatten():
        rows = {}
        for p, d in punish.setdefault("warns", {}).items():
            for u, lst in d.items():
                for i, w in enumerate(lst):
                    rows[(int(p), int(u), i)] = (_i(w.get("by")), w.get("reason"), _i(w.get("t")))
        return rows

    def warns_load(rows):
        st = punish.setdefault("warns", {})
        for r in rows:
            st.setdefault(str(r[0]), {}).setdefault(str(r[1]), []).append({"by": r[3], "reason": r[4], "t": r[5]})

    def glog_flatten():
        return {(int(u), i): (_r(t),) for u, lst in punish.setdefault("grant_log", {}).items()
                for i, t in enumerate(lst)}

    def glog_load(rows):
        st = punish.setdefault("grant_log", {})
        for r in rows:
            st.setdefault(str(r[0]), []).append(r[2])
    def hist_flatten():
        return {(int(p), i): (h.get("day"), _j(h.get("top")))
                for p, lst in daily.setdefault("history", {}).items() for i, h in enumerate(lst)}

    def hist_load(rows):
        st = daily.setdefault("history", {})
        for r in rows:
            st.setdefault(str(r[0]), []).append({"day": r[2], "top": json.loads(r[3])})

    def puses_flatten():
        return {(pk, i): (_i(u),) for pk, pr in economy.setdefault("promos", {}).items()
                for i, u in enumerate(pr.get("used_by", []))}

    def puses_load(rows):
        st = economy.setdefault("promos", {})
        for r in rows:
            if r[0] in st:
                st[r[0]].setdefault("used_by", []).append(r[2])

    # --- одиночные значения ---
    def dmeta_flatten():
        return {("day",): (daily["day"],)} if daily.get("day") else {}

    def dmeta_load(rows):
        for r in rows:
            if r[0] == "day":
                daily["day"] = r[1]

    def emeta_flatten():
        rows = {}
        if economy.get("report_wait"):
            rows[("report_wait",)] = (_j(economy["report_wait"]),)
        if economy.get("btc"):
            rows[("btc",)] = (_j(economy["btc"]),)
        if economy.get("settings"):
            rows[("settings",)] = (_j(economy["settings"]),)
        if economy.get("wall_posts"):
            rows[("wall_posts",)] = (_j(economy["wall_posts"]),)
        return rows

    def emeta_load(rows):
        for r in rows:
            if r[0] == "report_wait":
                economy["report_wait"] = json.loads(r[1])
            elif r[0] == "btc":
                economy["btc"] = json.loads(r[1])
            elif r[0] == "settings":
                economy["settings"] = json.loads(r[1])
            elif r[0] == "wall_posts":
                economy["wall_posts"] = json.loads(r[1])

    def inv_flatten():
        return {(int(u), i): (item,) for u, rec in economy.setdefault("users", {}).items()
                for i, item in enumerate(rec.get("items", []))}

    def inv_load(rows):
        users = economy.setdefault("users", {})
        for r in rows:
            if str(r[0]) in users:
                users[str(r[0])].setdefault("items", []).append(r[2])

    def equip_flatten():
        return {(int(u), slot): (item,) for u, rec in economy.setdefault("users", {}).items()
                for slot, item in rec.get("equip", {}).items()}

    def equip_load(rows):
        users = economy.setdefault("users", {})
        for r in rows:
            if str(r[0]) in users:
                users[str(r[0])].setdefault("equip", {})[r[1]] = r[2]

    def bank_flatten():
        return {(int(u), i): (_i(l.get("a")), _r(l.get("t")))
                for u, lots in economy.setdefault("bank", {}).items() for i, l in enumerate(lots)}

    def bank_load(rows):
        st = economy.setdefault("bank", {})
        for r in rows:
            st.setdefault(str(r[0]), []).append({"a": r[2], "t": r[3]})

    T = [
        _pairs("roles", "roles", lambda: data, [("level", "INTEGER")],
               lambda v: (_i(v),), lambda r: int(r[0])),
        _pairs("chat_stats", "stats", lambda: stats,
               [("n", "INTEGER"), ("first_ts", "INTEGER"), ("last_ts", "INTEGER")],
               lambda v: (_i(v.get("n")), _i(v.get("first")), _i(v.get("last"))),
               lambda r: {"n": r[0], "first": r[1], "last": r[2]}),
        _pairs("daily_counts", "stats", lambda: daily.setdefault("counts", {}), [("n", "INTEGER")],
               lambda v: (_i(v),), lambda r: int(r[0])),
        Table("daily_history", "stats", [("peer_id", "INTEGER"), ("seq", "INTEGER")],
              [("day", "TEXT"), ("top_json", "TEXT")], hist_flatten, hist_load),
        Table("daily_meta", "stats", [("meta_key", "TEXT")], [("value", "TEXT")], dmeta_flatten, dmeta_load),

        _entity("users", "economy", econ("users"), "user_id", True, users_f, skip=("items", "equip")),
        Table("inventory", "economy", [("user_id", "INTEGER"), ("seq", "INTEGER")], [("item_id", "TEXT")],
              inv_flatten, inv_load),
        Table("equipment", "economy", [("user_id", "INTEGER"), ("slot", "TEXT")], [("item_id", "TEXT")],
              equip_flatten, equip_load),
        Table("bank_lots", "economy", [("user_id", "INTEGER"), ("seq", "INTEGER")],
              [("amount", "INTEGER"), ("t", "REAL")], bank_flatten, bank_load),
        _entity("promos", "economy", econ("promos"), "promo_key", False, promos_f, skip=("used_by",)),
        Table("promo_uses", "economy", [("promo_key", "TEXT"), ("seq", "INTEGER")], [("user_id", "INTEGER")],
              puses_flatten, puses_load),
        _entity("games", "economy", econ("games"), "game_key", False, games_f),
        _entity("duels", "economy", econ("duels"), "duel_id", True, duels_f, key_field="id"),
        _entity("reports", "economy", econ("reports"), "report_id", True, reports_f),
        _entity("approvals", "economy", econ("approvals"), "approval_id", True, appr_f, key_field="id"),
        _entity("roulette", "economy", econ("roulette"), "roulette_id", True, roul_f),
        _entity("report_mode", "economy", econ("report_mode"), "user_id", True, rmode_f),
        _entity("refs", "economy", econ("refs"), "invitee_id", True, refs_f),
        _entity("auction", "economy", econ("auction"), "lot_id", True, auction_f, key_field="id"),
        _entity("donate_orders", "economy", econ("donate_orders"), "order_id", True, donate_f, key_field="id"),
        _singles("donate_blocked", "economy", econ("donate_blocked"), "user_id", "INTEGER", "blocked", "INTEGER",
                 lambda v: 1, lambda v: True),
        _singles("report_blocked", "economy", econ("report_blocked"), "user_id", "INTEGER", "blocked", "INTEGER",
                 lambda v: 1, lambda v: True),
        _singles("report_staff", "economy", econ("report_staff"), "user_id", "INTEGER", "since", "INTEGER", _i, int),
        _singles("seq", "economy", econ("seq"), "name", "TEXT", "value", "INTEGER", _i, int),
        _singles("media", "economy", econ("media"), "media_key", "TEXT", "attachment", "TEXT", _t, str),
        Table("econ_meta", "economy", [("meta_key", "TEXT")], [("value", "TEXT")], emeta_flatten, emeta_load),

        _pairs("mutes", "punish", punished("mutes"), [("until", "REAL")],
               lambda v: (_r(v),), lambda r: float(r[0])),
        _pairs("bans", "punish", punished("bans"),
               [("by_user", "INTEGER"), ("reason", "TEXT"), ("created", "INTEGER")],
               lambda v: (_i(v.get("by")), v.get("reason"), _i(v.get("t"))),
               lambda r: {"by": r[0], "reason": r[1], "t": r[2]}),
        Table("warns", "punish", [("peer_id", "INTEGER"), ("user_id", "INTEGER"), ("seq", "INTEGER")],
              [("by_user", "INTEGER"), ("reason", "TEXT"), ("created", "INTEGER")], warns_flatten, warns_load),
        _entity("gbans", "punish", punished("gbans"), "user_id", True,
                [("by", "by_user", "INTEGER", "i"), ("reason", "reason", "TEXT", "t"), ("t", "created", "INTEGER", "i")]),
        _singles("timeouts", "punish", punished("timeouts"), "peer_id", "INTEGER", "until", "REAL", _r, float),
        _singles("freezes", "punish", punished("freezes"), "user_id", "INTEGER", "until", "REAL", _r, float),
        Table("grant_log", "punish", [("user_id", "INTEGER"), ("seq", "INTEGER")], [("t", "REAL")],
              glog_flatten, glog_load),
    ]
    return T

TABLES = _build_tables()

def db_load_all():
    with DB_LOCK:
        for t in TABLES:
            cols = ", ".join(c for c, _ in t.keys + t.vals)
            order = ", ".join(c for c, _ in t.keys)
            rows = db.execute(f"SELECT {cols} FROM {t.name} ORDER BY {order}").fetchall()
            t.load(rows)
            t.snapshot = t.flatten()

def db_save(group):
    """Записывает в базу только изменившиеся строки таблиц группы — одной транзакцией."""
    with DB_LOCK:
        pending = []
        db.execute("BEGIN")
        try:
            for t in TABLES:
                if t.group != group:
                    continue
                new, old = t.flatten(), t.snapshot
                cols = [c for c, _ in t.keys + t.vals]
                nk = len(t.keys)
                upsert = (f"INSERT OR REPLACE INTO {t.name} ({', '.join(cols)}) "
                          f"VALUES ({', '.join('?' * len(cols))})")
                changed = [k + v for k, v in new.items() if old.get(k) != v]
                if changed:
                    db.executemany(upsert, changed)
                gone = [k for k in old if k not in new]
                if gone:
                    where = " AND ".join(f"{c} = ?" for c, _ in t.keys)
                    db.executemany(f"DELETE FROM {t.name} WHERE {where}", gone)
                pending.append((t, new))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        for t, new in pending:
            t.snapshot = new

def ensure_defaults():
    for key in ("users", "promos", "games", "duels", "reports", "report_mode", "report_blocked",
                "report_staff", "approvals", "roulette", "refs", "auction", "donate_orders", "donate_blocked", "bank"):
        economy.setdefault(key, {})
    economy.setdefault("seq", {})
    economy.setdefault("media", {})
    economy.setdefault("settings", {})
    economy.setdefault("wall_posts", {})
    economy.setdefault("btc", {"rate": BTC_START_RATE, "prev": BTC_START_RATE, "t": 0})
    for _k, _v in (("auto", True), ("hist", []), ("mood", "flat"), ("mood_left", 0), ("tick_t", 0)):
        economy["btc"].setdefault(_k, _v)
    for key in ("duel", "report", "approval", "roulette", "auction", "donate"):
        economy["seq"].setdefault(key, 0)
    for key in ("mutes", "bans", "warns", "timeouts", "freezes", "grant_log", "gbans"):
        punish.setdefault(key, {})
    daily.setdefault("counts", {})
    daily.setdefault("history", {})

def migrate_from_json():
    """Один раз переносит старые JSON-файлы и логи в базу. Исходные файлы переименовываются в *.migrated."""
    sources = ((DATA_FILE, data), (STATS_FILE, stats), (ECONOMY_FILE, economy),
               (PUNISH_FILE, punish), (DAILY_FILE, daily))
    found = [(p, d) for p, d in sources if os.path.exists(p)]
    log_files = []
    if os.path.isdir(LOGS_DIR):
        log_files = sorted(os.path.join(LOGS_DIR, f) for f in os.listdir(LOGS_DIR) if f.endswith(".jsonl"))

    ok = True
    if found or log_files:
        print("🔄 Перенос данных из JSON в базу данных...")
        for path, target in found:
            try:
                target.update(load_json(path))
            except Exception as e:
                ok = False
                print(f"❌ Не удалось прочитать {path}: {err_text(e)}")
        ensure_defaults()
        for group in ("roles", "stats", "economy", "punish"):
            db_save(group)

        imported = 0
        for path in log_files:
            rows = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        rows.append((int(e["t"]), e.get("k"), int(e.get("p", 0)), int(e.get("u", 0)), e.get("x", "")))
                    except (ValueError, KeyError, TypeError):
                        continue
            with DB_LOCK:
                db.executemany("INSERT INTO logs (t, kind, peer_id, user_id, text) VALUES (?, ?, ?, ?, ?)", rows)
            imported += len(rows)

        if ok:
            for path in [p for p, _ in found] + log_files:
                os.replace(path, path + ".migrated")
        print(f"✅ Перенесено: файлов {len(found)}, записей логов {imported}. "
              f"Старые файлы сохранены с суффиксом .migrated")
    if ok:
        with DB_LOCK:
            db.execute("INSERT OR REPLACE INTO app_meta (meta_key, value) VALUES ('json_migrated', '1')")

def restore_latest_backup_if_needed():
    """Файла базы нет, но рядом лежат ежедневные копии — поднимаем самую свежую."""
    if os.path.exists(DB_FILE) or not os.path.isdir(BACKUP_DIR):
        return
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("bot-") and f.endswith(".db"))
    if files:
        shutil.copy(os.path.join(BACKUP_DIR, files[-1]), DB_FILE)
        print(f"♻ Файла базы не было — восстановлена последняя копия: {files[-1]}")

def init_db():
    global db
    restore_latest_backup_if_needed()
    db = sqlite3.connect(DB_FILE, check_same_thread=False, isolation_level=None)
    with DB_LOCK:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        for t in TABLES:
            db.execute(t.create_sql())
            have = {r[1] for r in db.execute(f"PRAGMA table_info({t.name})")}
            for col, typ in t.vals:  # база от прошлой версии: добавляем новые колонки
                if col not in have:
                    db.execute(f"ALTER TABLE {t.name} ADD COLUMN {col} {typ}")
        db.execute("CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER NOT NULL, "
                   "kind TEXT, peer_id INTEGER, user_id INTEGER, text TEXT)")
        db.execute("CREATE INDEX IF NOT EXISTS logs_t ON logs (t)")
        db.execute("CREATE INDEX IF NOT EXISTS logs_user ON logs (user_id, t)")
    db_load_all()
    with DB_LOCK:
        migrated = db.execute("SELECT value FROM app_meta WHERE meta_key = 'json_migrated'").fetchone()
    if not migrated or not (economy.get("users") or data or stats):  # пустая база + старые файлы рядом — переносим
        migrate_from_json()
    ensure_defaults()

def backup_db():
    """Копия базы раз в сутки в папку backups/ (хранятся последние BACKUP_KEEP штук)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"bot-{today_str()}.db")
        with DB_LOCK:
            dst = sqlite3.connect(path)
            db.backup(dst)
            dst.close()
        files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("bot-") and f.endswith(".db"))
        for old in files[:-BACKUP_KEEP]:
            os.remove(os.path.join(BACKUP_DIR, old))
    except Exception as e:
        print(f"Не удалось сделать копию базы: {err_text(e)}")

data, stats, economy, punish, daily = {}, {}, {}, {}, {}
stats_state = {"dirty": False, "last_save": time.time()}

def save_data():
    db_save("roles")

def save_economy():
    db_save("economy")

def save_punish():
    db_save("punish")

def save_stats(force=False):
    if not stats_state["dirty"]:
        return
    if not force and time.time() - stats_state["last_save"] < STATS_SAVE_INTERVAL:
        return
    db_save("stats")
    stats_state["dirty"] = False
    stats_state["last_save"] = time.time()

# ---------- роли ----------
def raw_level(peer_id, user_id):
    """Роль так, как она записана в базе (у «Зама чата» это 6)."""
    if user_id == OWNER_ID:
        return 5
    return data.get(str(peer_id), {}).get(str(user_id), 0)

def get_level(peer_id, user_id):
    """Уровень для проверок прав. «Зам чата» считается Администратором (DEPUTY_AS_LEVEL),
    поэтому ни одна старая проверка не примет его за Владельца."""
    lvl = raw_level(peer_id, user_id)
    return DEPUTY_AS_LEVEL if lvl == DEPUTY_LEVEL else lvl

def is_deputy(peer_id, user_id):
    return user_id != OWNER_ID and raw_level(peer_id, user_id) == DEPUTY_LEVEL

def set_level(peer_id, user_id, level):
    chat = data.setdefault(str(peer_id), {})
    if level == 0:
        chat.pop(str(user_id), None)
    else:
        chat[str(user_id)] = level
    save_data()

def users_with_level(peer_id, level):
    if level == 5:
        return [OWNER_ID]
    chat = data.get(str(peer_id), {})
    return [int(uid) for uid, lvl in chat.items() if lvl == level]

# ---------- статистика сообщений ----------
def count_message(msg):
    uid = msg["from_id"]
    if uid <= 0 or msg.get("action"):
        return
    chat = stats.setdefault(str(msg["peer_id"]), {})
    s = chat.setdefault(str(uid), {"n": 0, "first": msg["date"], "last": msg["date"]})
    s["n"] += 1
    s["last"] = msg["date"]
    day_counts = daily["counts"].setdefault(str(msg["peer_id"]), {})
    day_counts[str(uid)] = day_counts.get(str(uid), 0) + 1
    stats_state["dirty"] = True
    save_stats()

# ---------- экономика ----------
def get_user(uid):
    return economy["users"].setdefault(str(uid), {"money": 0, "exp": 0, "last_bonus": 0, "reg": time.time()})
def player_level(exp):
    """(номер, название, exp от, exp до). После последнего порога уровень не растёт."""
    for lvl, name, lo, hi in PLAYER_LEVELS:
        if exp < hi:
            return lvl, name, lo, hi
    return PLAYER_LEVELS[-1]

def exp_text(exp):
    if exp >= PLAYER_LEVELS[-1][2]:
        return f"{exp} (максимальный уровень)"
    return f"{exp}/{player_level(exp)[3]}"

# ---------- муты и баны ----------
def mute_user(peer_id, uid, seconds):
    until = time.time() + seconds
    punish["mutes"].setdefault(str(peer_id), {})[str(uid)] = until
    save_punish()
    return until

def unmute_user(peer_id, uid):
    removed = punish["mutes"].get(str(peer_id), {}).pop(str(uid), None)
    if removed is not None:
        save_punish()
    return removed is not None

def mute_left(peer_id, uid):
    """Сколько секунд мута осталось (0 — не в муте). Просроченные муты снимаются сами."""
    chat = punish["mutes"].get(str(peer_id), {})
    until = chat.get(str(uid))
    if until is None:
        return 0
    left = until - time.time()
    if left <= 0:
        del chat[str(uid)]
        save_punish()
        return 0
    return left

# ---------- Опыт, VIP, префикс ----------
def get_prefix(uid):
    user = economy["users"].get(str(uid))
    if not user:
        return ""
    vip_active(user)  # заодно снимет просроченный VIP-префикс
    return user.get("prefix", "")

# ---------- Предупреждения (варны) ----------
def get_warns(peer_id, uid):
    return punish["warns"].get(str(peer_id), {}).get(str(uid), [])

# ---------- Топ дня, итоги и история ----------
def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def fmt_day(day):
    y, m, d = day.split("-")
    return f"{d}.{m}.{y}"

def promo_expired(p):
    return time.time() >= (p.get("exp") or p.get("t", 0) + PROMO_TTL)

# ---------- VIP: срок действия и коэффициент ----------
def vip_active(user):
    """VIP действует VIP_DAYS дней. Просроченный VIP снимается вместе с VIP-префиксом."""
    now = time.time()
    if user.get("vip") and "vip_until" not in user:   # VIP из старой версии бота
        user["vip_until"] = now + VIP_DAYS * 86400
    if user.get("vip_until", 0) > now:
        if user.get("prefix") == "VIP✨":             # старый вид префикса
            user["prefix"] = VIP_PREFIX
        return True
    if user.get("vip"):
        user["vip"] = False
        if user.get("prefix") in (VIP_PREFIX, "VIP✨"):
            user.pop("prefix", None)
    return False

# ---------- Заморозка Тех специалистов за частые выдачи ----------
def freeze_left(uid):
    until = punish["freezes"].get(str(uid))
    if not until:
        return 0
    left = until - time.time()
    if left <= 0:
        del punish["freezes"][str(uid)]
        save_punish()
        return 0
    return left

# ---------- выполняется при запуске ----------
init_db()  # открывает bot.db, загружает данные; при первом запуске переносит старые JSON-файлы
