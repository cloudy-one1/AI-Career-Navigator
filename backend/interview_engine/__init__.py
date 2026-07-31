"""
面试引擎包 v2.5
双模式面试（拟真6阶段 / 传统5轮次）+ 多面试官自动切换。
拆分为 session + report 子模块。
"""

from .session import InterviewSession
from .report import build_report, analyze_trends, generate_suggestions

__all__ = ["InterviewSession", "build_report", "analyze_trends", "generate_suggestions"]
