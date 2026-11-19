# -*- coding: utf-8 -*-
"""Список бесед, которые знает бот (для рассылки, конкурса и глобального бана)."""
import time

from config import CHAT_OFFSET
from database import daily, data, punish, stats


def known_chats(active_days=None):
    """peer_id всех бесед, где бот что-то записал. active_days — только те, где писали за последние N дней."""
    peers = set()
    if active_days is None:
        sources = (stats, data, daily.get("counts", {}), punish.get("bans", {}), punish.get("mutes", {}))
        for src in sources:
            for p in src:
                if str(p).lstrip("-").isdigit() and int(p) >= CHAT_OFFSET:
                    peers.add(int(p))
    else:
        border = time.time() - active_days * 86400
        for p, users in stats.items():
            if str(p).isdigit() and int(p) >= CHAT_OFFSET:
                if max((u.get("last") or 0 for u in users.values()), default=0) >= border:
                    peers.add(int(p))
    return sorted(peers)
