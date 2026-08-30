"""
黄金样本回归（v7.1 新增，测试策略 v2）—— 补齐「诊断准不准」的测试缺口。

背景与口径（与 docs/测试用例审计与精简方案.md 的评估结论一致）：
  诊断打分由 LLM 完成、非确定性，无法在单测里用 FakeLLM 断言「分数准不准」。
  因此黄金样本分两层：
    1) 确定性回归（默认运行）：固定答案 + 人工标注诊断 JSON → 断言
       run_diagnosis → normalize_result 全链路的分数 / 最弱维度 / 加扣分项
       与人工标注一致。验证「prompt 构建 → JSON 解析 → 规整」没有回退。
    2) live-LLM 抽检（默认 deselect）：真实模型跑同样样本，对 fixtures 的
       baseline（deepseek-chat 当前实然快照）做回归守护——总分 / 最弱维度
       跌出基线即告警；同时打印与人工 expected（应然质量线）的对照供人工评估。
       需 GOLDEN_LIVE_LLM=1 + 真实 Key 显式开启（烧 token，仅 CI 手动触发）。

样本标注口径：四类典型回答——量化充分但 STAR 欠缺 / 全篇口号 /
STAR 完整且量化充分 / 甩锅避答。期望值由规则化加减分（确定性信号）+ 人工
对五维的理解给出。
"""
import asyncio
import json
import os

import pytest

from backend.diagnosis_engine import normalize_result, run_diagnosis
from backend.dimension_weights import DIM_KEYS

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "golden_answers.json")

# normalize_result 合法的 next_action 取值（v6.0 三态 + complete 兼容）
NEXT_ACTIONS = {"follow_up", "next_question", "complete"}


def _load_samples() -> list[dict]:
    with open(_FIXTURES, encoding="utf-8") as f:
        return json.load(f)["samples"]


class FakeDiagnosisLLM:
    """固定返回「人工标注诊断 JSON」的假 LLM，让整条诊断链路完全确定性。"""

    def __init__(self, diagnosis: dict, rewrite: dict):
        self._diagnosis = json.dumps(diagnosis, ensure_ascii=False)
        self._rewrite = json.dumps(rewrite, ensure_ascii=False)
        self.calls = []

    def chat(self, system, user, temperature, max_tokens, response_format=None, task=None):
        self.calls.append({"task": task})
        return self._rewrite if task == "rewrite" else self._diagnosis


@pytest.mark.parametrize("sample", _load_samples(), ids=lambda s: s["id"])
def test_golden_diagnosis_reproduces_annotation(sample):
    """确定性回归：固定输入 → 全链路输出必须落在人工标注区间。"""
    llm = FakeDiagnosisLLM(sample["diagnosis"], sample["rewrite"])
    q, a = sample["question"], sample["answer"]
    exp = sample["expected"]

    result = asyncio.run(run_diagnosis(
        llm, question=q, answer=a, resume_text="", jd_text="",
    ))
    normalized = normalize_result(
        result["diagnosis"], result["rewrite"],
        weights=None, question=q, answer=a,
    )

    # 1) 总分落在人工区间（容忍加扣分项组合的合理波动）
    assert exp["overall_min"] <= normalized["overall_score"] <= exp["overall_max"], (
        f"总分 {normalized['overall_score']} 不在人工区间 "
        f"[{exp['overall_min']}, {exp['overall_max']}]"
    )

    # 2) 最弱维度与人工标注一致（追问打点的关键）
    assert normalized["weakest_dimension"] == exp["weakest_dimension"], (
        f"最弱维度 {normalized['weakest_dimension']} != 人工标注 {exp['weakest_dimension']}"
    )

    # 3) 五维齐备且在量纲内
    assert set(normalized["dimensions"]) == set(DIM_KEYS)
    for k in DIM_KEYS:
        assert 1.0 <= normalized["dimensions"][k] <= 5.0, f"{k} 分数出量纲"

    # 4) 规则化加扣分命中人工标注的信号（子集断言，允许模型额外命中）
    keys = {adj["key"] for adj in normalized["score_adjustments"]}
    assert set(exp["evidence_keys"]) <= keys, (
        f"期望信号 {exp['evidence_keys']} 未全部命中，实际 {keys}"
    )

    # 5) 结构不变量：next_action 合法、追问非空
    assert normalized["next_action"] in NEXT_ACTIONS
    assert normalized["follow_up_question"]


@pytest.mark.parametrize("sample", _load_samples(), ids=lambda s: s["id"])
def test_golden_quotes_are_literal_answer_substrings(sample):
    """诊断引用必须是原回答的字面子串（v6.3 起「证据引用」的产品承诺）。"""
    llm = FakeDiagnosisLLM(sample["diagnosis"], sample["rewrite"])
    q, a = sample["question"], sample["answer"]

    result = asyncio.run(run_diagnosis(
        llm, question=q, answer=a, resume_text="", jd_text="",
    ))
    normalized = normalize_result(
        result["diagnosis"], result["rewrite"],
        weights=None, question=q, answer=a,
    )

    for k in DIM_KEYS:
        quote = (normalized["dimension_details"][k].get("quote") or "").strip()
        if quote:
            assert quote in a, f"{k} 的引用不在原回答中: {quote!r}"


# ===== live-LLM 抽检（默认 deselect，需显式开启） =====
# 真实模型非确定性，对 fixtures 的 baseline（deepseek-chat 当前实然快照）做
# 回归守护：总分 / 最弱维度跌出基线即断言失败（回归告警）；同时打印与人工
# expected（应然质量线）的对照，便于评估「模型离质量目标还差多少」。
# 运行方式：
#   $env:GOLDEN_LIVE_LLM="1"; $env:GOLDEN_LIVE_LLM_API_KEY="sk-..."; pytest tests/test_diagnosis_golden.py -v

@pytest.mark.live_llm
@pytest.mark.skipif(os.environ.get("GOLDEN_LIVE_LLM") != "1",
                    reason="真实 LLM 抽检需 GOLDEN_LIVE_LLM=1 显式开启（烧 token）")
def test_live_llm_snapshot_on_golden_samples():
    key = os.environ.get("GOLDEN_LIVE_LLM_API_KEY", "").strip()
    if not key:
        pytest.skip("未提供 GOLDEN_LIVE_LLM_API_KEY")
    os.environ["LLM_API_KEY"] = key
    base = os.environ.get("GOLDEN_LIVE_LLM_BASE_URL", "").strip()
    if base:
        os.environ["LLM_BASE_URL"] = base

    from backend.llm_client import LLMClient
    client = LLMClient()

    for sample in _load_samples():
        q, a = sample["question"], sample["answer"]
        result = asyncio.run(run_diagnosis(
            client, question=q, answer=a, resume_text="", jd_text="",
        ))
        normalized = normalize_result(
            result["diagnosis"], result["rewrite"],
            weights=None, question=q, answer=a,
        )
        # 结构软断言
        assert set(normalized["dimensions"]) == set(DIM_KEYS)
        assert 0 <= normalized["overall_score"] <= 5
        assert normalized["next_action"] in NEXT_ACTIONS
        for k in DIM_KEYS:
            quote = normalized["dimension_details"][k].get("quote") or ""
            if quote:
                assert quote in a, f"{k} 引用不在原回答中: {quote!r}"

        # 第 2 层基线守护：对 deepseek-chat 当前实然快照做回归断言
        base_cfg = sample["baseline"]
        bmin, bmax = base_cfg["overall_min"], base_cfg["overall_max"]
        score = normalized["overall_score"]
        wd = normalized["weakest_dimension"]
        assert bmin <= score <= bmax, (
            f"{sample['id']} 总分 {score:.2f} 跌出基线区间 "
            f"[{bmin}, {bmax}]（deepseek-chat 当前快照）"
        )
        assert wd == base_cfg["weakest_dimension"], (
            f"{sample['id']} 最弱维度 {wd} != 基线 {base_cfg['weakest_dimension']}"
        )
        # 同时保留与人工「应然」区间的对照（仅供参考，不硬断言）
        exp = sample["expected"]
        print(f"[live_llm:{sample['id']}] overall={score:.2f} weakest={wd} "
              f"baseline=[{bmin}, {bmax}] OK | "
              f"human-annotation=[{exp['overall_min']}, {exp['overall_max']}]")
