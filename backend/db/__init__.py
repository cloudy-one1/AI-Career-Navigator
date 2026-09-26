"""
数据库 v2.5：SQLite 多表操作 (aiosqlite)
v2.2: 新增 question_bank 表
v2.5: 新增 diagnosis_feedback 表

v8.11 拆分：原单文件 1370 行按领域切成子模块。本文件显式 re-export 全部顶层名字，
`from backend.db import X` 与 `backend.db.X` 两种写法都不受影响。
"""

from .connection import (
    get_db,
)
from .feedback import (
    get_feedback_stats,
    get_session_feedback,
    save_feedback,
)
from .jd_weights import (
    lookup_jd_weights,
    save_jd_weights,
)
from .questions import (
    add_question,
    delete_question,
    get_question,
    import_questions_from_session,
    increment_usage,
    list_questions,
    toggle_favorite,
    update_question,
)
from .resources import (
    delete_position,
    delete_resume,
    find_position_by_market_job,
    get_position,
    get_resume,
    list_positions,
    list_resumes,
    save_position,
    save_resume,
    update_position,
    update_resume,
)
from .schema import (
    init_db,
)
from .sessions import (
    get_report,
    get_session,
    get_session_qas,
    list_journey_marks,
    list_recent_reports,
    list_sessions,
    mark_journey_step,
    save_qa,
    save_report,
    save_session,
    update_session_flow,
    update_session_status,
)
from .weakness import (
    delete_weakness,
    get_global_weakness_profile,
    get_latest_risk_points,
    get_weakness_profile,
    list_unresolved_weaknesses,
    list_weakness_points,
    mark_weakness_resolved,
    save_weakness_profile,
)
from .weakness_state import (
    delete_weakness_memory,
    get_weakness_memory,
    list_active_weakness_memory,
    prune_expired_weakness_memory,
    upsert_weakness_memory,
)

__all__ = [
    "add_question",
    "delete_position",
    "delete_question",
    "delete_resume",
    "delete_weakness",
    "delete_weakness_memory",
    "find_position_by_market_job",
    "get_db",
    "get_feedback_stats",
    "get_global_weakness_profile",
    "get_latest_risk_points",
    "get_position",
    "get_question",
    "get_report",
    "get_resume",
    "get_session",
    "get_session_feedback",
    "get_session_qas",
    "get_weakness_memory",
    "get_weakness_profile",
    "import_questions_from_session",
    "increment_usage",
    "init_db",
    "list_active_weakness_memory",
    "list_journey_marks",
    "list_positions",
    "list_questions",
    "list_recent_reports",
    "list_resumes",
    "list_sessions",
    "list_unresolved_weaknesses",
    "list_weakness_points",
    "lookup_jd_weights",
    "mark_journey_step",
    "mark_weakness_resolved",
    "prune_expired_weakness_memory",
    "save_feedback",
    "save_jd_weights",
    "save_position",
    "save_qa",
    "save_report",
    "save_resume",
    "save_session",
    "save_weakness_profile",
    "toggle_favorite",
    "update_position",
    "update_question",
    "update_resume",
    "update_session_flow",
    "update_session_status",
    "upsert_weakness_memory",
]
