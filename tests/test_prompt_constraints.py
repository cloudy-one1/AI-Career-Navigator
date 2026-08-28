"""
出题 Prompt 硬约束测试（v6.0，对标 career-copilot interview.system 的工程化约束）。
"""

from backend.question_gen import get_question_gen_system_prompt
from backend.diagnosis_engine import DIAGNOSTICIAN_SYSTEM_PROMPT


def test_question_gen_prompt_constraints():
    p = get_question_gen_system_prompt()
    # 题型枚举（与 type_mix / _QUESTION_TYPE_GUIDANCE 的取值一致）
    assert "knowledge" in p and "project" in p and "behavior" in p
    # 只出题不替答（career-copilot 核心原则）
    assert "绝不替候选人回答" in p
    # 难度递进（easy → mid → hard）
    assert "难度递进" in p
    # 整场 5-8 轮约束
    assert "5-8 轮" in p
    # 禁止提示性答案
    assert "JSON" in p


def test_diagnostician_prompt_next_action_schema():
    p = DIAGNOSTICIAN_SYSTEM_PROMPT
    # 三态 next_action 已写入 schema
    assert "follow_up" in p and "next_question" in p and "complete" in p
    # 追问次数硬约束（与 FOLLOW_UP_MAX_COUNT=2 呼应）
    assert "不得超过 2 次" in p
