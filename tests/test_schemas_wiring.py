"""schemas 接线门禁（v8.21，防回潮）。

存在理由：schemas.py 曾长期堆积"文档型 schema"——定义后从未被任何路由/引擎
import 的模型（v8.18 审查逐一核实 18 个全后端零引用）。这类模型的危害不是
"占行数"而是"接回即炸"：其中 DimensionScore.score 曾钉 int(ge=1,le=5)，与
诊断引擎实际 float 输出已漂移，后人把它当响应模型接回路由即 ValidationError。

本门禁要求：backend.schemas 的每个公开模型都必须"被消费"——
  1. 在 backend 源码（schemas.py 之外）被 import/引用；或
  2. 作为某个已消费模型的嵌套字段类型（FastAPI 对 request/response_model
     是递归校验/序列化的，嵌套类型随父模型一起被消费）。
两条都不满足的模型进不了仓库。有效性自测见文件末尾的反向用例。
"""
import inspect
import re
from pathlib import Path

from pydantic import BaseModel

import backend.schemas as schemas_mod

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"


def _public_models() -> list[str]:
    return [
        name
        for name in dir(schemas_mod)
        if not name.startswith("_")
        and isinstance(getattr(schemas_mod, name), type)
        and issubclass(getattr(schemas_mod, name), BaseModel)
    ]


def _externally_referenced(models: list[str]) -> set[str]:
    """在 backend 源码（schemas.py 之外）出现过的模型名集合。

    按原文出现即算（含注释）——本门禁针对的是"从未有人记得它存在"的死模型，
    不是精确的静态分析；宁可漏报也不误伤文档注释里的正当提及。
    """
    pattern = {name: re.compile(r"\b" + name + r"\b") for name in models}
    referenced: set[str] = set()
    for p in BACKEND_ROOT.rglob("*.py"):
        if p.name == "schemas.py":
            continue
        text = p.read_text(encoding="utf-8")
        for name, pat in pattern.items():
            if name not in referenced and pat.search(text):
                referenced.add(name)
    return referenced


def _unwired_models() -> list[str]:
    models = _public_models()
    wired = _externally_referenced(models)
    # 传递闭包：被已消费模型的类体（字段注解）引用的嵌套类型也算已消费。
    changed = True
    while changed:
        changed = False
        for name in models:
            if name in wired:
                continue
            pat = re.compile(r"\b" + name + r"\b")
            for w in wired:
                if pat.search(inspect.getsource(getattr(schemas_mod, w))):
                    wired.add(name)
                    changed = True
                    break
    return sorted(set(models) - wired)


def test_every_public_schema_is_wired():
    unwired = _unwired_models()
    assert not unwired, (
        "以下 schema 模型在 backend 中零消费（文档型 schema，接线门禁）："
        f"{', '.join(unwired)}。要么接进路由/引擎实际使用，要么删除；"
        "不要让'看似以后有用'的模型留在 schemas.py——未接线的模型与引擎真实"
        "输出漂移后，接回即 ValidationError。"
    )


def test_gate_goes_red_on_unwired_model(monkeypatch):
    """注入一个从未接线的僵尸模型必须让门禁变红——否则上面的绿毫无意义。"""
    zombie = type(
        "ZombieDocModel",
        (BaseModel,),
        {"__annotations__": {"field": str}, "field": "x"},
    )
    monkeypatch.setattr(schemas_mod, "ZombieDocModel", zombie, raising=False)
    unwired = _unwired_models()
    assert "ZombieDocModel" in unwired, "门禁无法识别零消费模型，说明它没有在检查"
