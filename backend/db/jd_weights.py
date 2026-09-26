"""按 JD 缓存的维度权重读写。"""

import json
import logging

from .connection import get_db

logger = logging.getLogger(__name__)


# ===== v3.1: JD 权重缓存 =====

async def lookup_jd_weights(jd_hash: str) -> dict | None:
    """根据 JD 哈希查找缓存的权重结果，若有则返回解析后的 dict，否则返回 None"""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT weights_json FROM jd_weights_cache WHERE jd_hash = ?", (jd_hash,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                try:
                    cached = json.loads(row[0])
                    if isinstance(cached, dict) and "weights" in cached:
                        cached["source"] = "cache"  # 覆盖标记
                        return cached
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"JD 权重缓存数据损坏 (hash={jd_hash[:12]}...)，忽略")
                    return None
        return None
    finally:
        await db.close()


async def save_jd_weights(jd_hash: str, jd_preview: str, weights: dict) -> None:
    """保存 JD 权重分析结果到缓存"""
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO jd_weights_cache (jd_hash, jd_preview, weights_json) VALUES (?, ?, ?)",
            (jd_hash, jd_preview[:100], json.dumps(weights, ensure_ascii=False)),
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"JD 权重缓存写入失败: {e}")
    finally:
        await db.close()
