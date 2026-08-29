"""
test_share.py —— v7.0 报告分享（招聘端只读入口）

安全模型上要守住的四条：
1. token 是随机高熵串，且**库里只存摘要**（明文只在签发响应中出现一次）
2. 免登录只读；但"不存在 / 已撤销 / 已过期"对外一律 404，防止枚举有效令牌
3. 撤销/列举必须校验归属 —— 别人的链接既看不到也撤不掉
4. 输出侧强制脱敏：手机号 / 邮箱 / 身份证 / QQ 微信不得出现在分享内容里

另有一条产品口径：include_detail 默认为 False —— 逐字回答默认不公开。
"""

import json
import uuid

import pytest
import pytest_asyncio

from backend import share_access
from backend.config import config as cfg
from backend.db import get_report, init_db, save_report, save_session

SAMPLE_REPORT = {
    "session_id": "sess1",
    "overall_avg": 3.8,
    "dimension_averages": {
        "star_completeness": 4.0,
        "quantification": 3.0,
        "logic_coherence": 4.0,
        "job_relevance": 3.5,
        "professional_depth": 4.5,
    },
    "rounds": [
        {"round_index": 0, "round_name": "技术一面",
         "questions_count": 3, "answers_count": 3, "avg_score": 3.8},
    ],
    "strengths": ["项目描述有数据支撑"],
    "weaknesses": ["缺少量化结果"],
    "suggestions": "建议补充关键数字。联系我 13812345678 或 alice@example.com",
    "qa_breakdown": [
        {
            "index": 1, "round_name": "技术一面",
            "question": "请介绍你做过的项目，可加我 QQ:12345678",
            "overall_score": 3.8,
            "overall_comment": "结构完整，电话 13900001111",
            "weakest_dimension_name": "量化程度",
            "risk_points": ["未给出指标"],
            "real_interview_impact": "大概率被追问细节",
            "assisted": False,
        },
    ],
}


@pytest.fixture(autouse=True)
def _restore_auth_config():
    """防止 AUTH_ENABLED 在测试间泄漏（部分用例会临时开启认证）。"""
    original = cfg.AUTH_ENABLED
    yield
    cfg.AUTH_ENABLED = original


@pytest_asyncio.fixture(autouse=True)
async def setup_db(tmp_path):
    original = cfg.DB_PATH
    cfg.DB_PATH = str(tmp_path / f"share{uuid.uuid4().hex}.db")
    await init_db()
    await save_session("sess1", style="friendly", jd_text="JD", resume_text="简历")
    # save_report 内部会 json.dumps —— 这里必须传 dict，传字符串会造成双重编码
    await save_report("sess1", SAMPLE_REPORT)
    # 一个"有会话但没报告"的场景，用于区分 404（会话不存在）与"报告未生成"
    await save_session("no-report", jd_text="", resume_text="")
    yield
    cfg.DB_PATH = original


# ===== 1. 令牌 =====

class TestToken:
    def test_token_is_high_entropy(self):
        tokens = {share_access.generate_token() for _ in range(100)}
        assert len(tokens) == 100           # 不重复
        assert all(len(t) >= 24 for t in tokens)

    def test_hash_is_stable_and_oneway(self):
        t = share_access.generate_token()
        h1 = share_access.hash_token(t)
        assert h1 == share_access.hash_token(t)
        assert t not in h1                  # 摘要不含原文
        assert len(h1) == 64                # sha256 hex

    @pytest.mark.asyncio
    async def test_database_stores_hash_not_plaintext(self):
        """库里只能存摘要 —— 这是"库泄露"不等于"链接泄露"的前提。"""
        link = await share_access.create_share_link("sess1")
        row = await share_access.get_share_link(link["token"])
        assert row is not None
        assert row["token"] == share_access.hash_token(link["token"])
        assert row["token"] != link["token"]


# ===== 2. 访问与失效 =====

class TestAccess:
    @pytest.mark.asyncio
    async def test_read_without_login(self):
        """免登录可读 —— 拿链接的是外部 HR，不该被要求注册。"""
        link = await share_access.create_share_link("sess1")
        payload = await share_access.resolve_shared_report(link["token"])
        assert payload["overall_score"] == 3.8
        assert payload["candidate_name"] == "候选人"   # 不泄露真实姓名

    @pytest.mark.asyncio
    async def test_detail_hidden_by_default(self):
        link = await share_access.create_share_link("sess1")
        payload = await share_access.resolve_shared_report(link["token"])
        assert payload["include_detail"] is False
        assert "qa_details" not in payload

    @pytest.mark.asyncio
    async def test_detail_included_when_requested(self):
        link = await share_access.create_share_link("sess1", include_detail=True)
        payload = await share_access.resolve_shared_report(link["token"])
        assert payload["include_detail"] is True
        assert len(payload["qa_details"]) == 1

    @pytest.mark.asyncio
    async def test_access_count_increments(self):
        link = await share_access.create_share_link("sess1")
        await share_access.resolve_shared_report(link["token"])
        await share_access.resolve_shared_report(link["token"])
        row = await share_access.get_share_link(link["token"])
        assert row["access_count"] == 2
        assert row["last_access_at"] is not None

    @pytest.mark.asyncio
    async def test_revoked_link_unreadable(self):
        link = await share_access.create_share_link("sess1")
        await share_access.revoke_share_link(link["token"], None)
        with pytest.raises(share_access.ShareAccessError) as e:
            await share_access.resolve_shared_report(link["token"])
        assert e.value.status_code == 404

    @pytest.mark.asyncio
    async def test_expired_link_unreadable(self):
        """过期链接不可读。过期用负天数构造，无需等待真实时间流逝。"""
        link = await share_access.create_share_link("sess1", expires_days=-1)
        with pytest.raises(share_access.ShareAccessError):
            await share_access.resolve_shared_report(link["token"])

    @pytest.mark.asyncio
    async def test_permanent_link_has_no_expiry(self):
        link = await share_access.create_share_link("sess1", expires_days=0)
        row = await share_access.get_share_link(link["token"])
        assert row["expires_at"] is None
        payload = await share_access.resolve_shared_report(link["token"])
        assert payload["expires_at"] is None

    @pytest.mark.asyncio
    async def test_unknown_token_same_error_as_revoked(self):
        """不存在 / 已撤销 / 已过期 必须是同一个错误，否则可被用来枚举令牌。"""
        link = await share_access.create_share_link("sess1")
        await share_access.revoke_share_link(link["token"], None)

        errors = []
        for token in (link["token"], "definitely-not-a-token", ""):
            with pytest.raises(share_access.ShareAccessError) as e:
                await share_access.resolve_shared_report(token)
            errors.append(str(e.value))
        assert len(set(errors)) == 1

    @pytest.mark.asyncio
    async def test_missing_report_is_error(self):
        """会话存在但还没出报告 → 不可分享。

        这里在模块层断言，不在 HTTP 层：HTTP 层是 400（"请先完成面试"的用法错误，
        与 404 的"无权/不存在"区分开），但        那需要在同步测试里造异步数据，收益不足以抵消测试脆弱性。
        """
        link = await share_access.create_share_link("no-report")
        with pytest.raises(share_access.ShareAccessError):
            await share_access.resolve_shared_report(link["token"])


# ===== 3. 脱敏 =====

class TestRedaction:
    @pytest.mark.parametrize("text,expect_absent", [
        ("联系我 13812345678", "13812345678"),
        ("邮箱 alice@example.com", "alice@example.com"),
        ("身份证 11010519491231002X", "11010519491231002X"),
        ("加我 QQ:12345678", "12345678"),
        ("微信：87654321", "87654321"),
    ])
    def test_pii_removed(self, text, expect_absent):
        out = share_access.redact_pii(text)
        assert expect_absent not in out
        assert "脱敏" in out

    def test_normal_text_untouched(self):
        t = "我负责订单系统的重构，QPS 从 2000 提升到 8000。"
        assert share_access.redact_pii(t) == t

    def test_none_and_empty_safe(self):
        assert share_access.redact_pii(None) == ""
        assert share_access.redact_pii("") == ""

    @pytest.mark.asyncio
    async def test_payload_is_redacted(self):
        """端到端：报告里夹带的 PII 不得出现在分享载荷中。"""
        link = await share_access.create_share_link("sess1", include_detail=True)
        payload = await share_access.resolve_shared_report(link["token"])
        blob = json.dumps(payload, ensure_ascii=False)
        for secret in ("13812345678", "alice@example.com", "13900001111", "12345678"):
            assert secret not in blob

    @pytest.mark.asyncio
    async def test_disclaimer_present(self):
        link = await share_access.create_share_link("sess1")
        payload = await share_access.resolve_shared_report(link["token"])
        assert "不构成录用建议" in payload["disclaimer"]


# ===== 4. 归属与撤销权限 =====

class TestRevocationOwnership:
    @pytest.mark.asyncio
    async def test_creator_can_revoke(self):
        cfg.AUTH_ENABLED = True
        link = await share_access.create_share_link("sess1", created_by="u1")
        await share_access.revoke_share_link(link["token"], "u1")
        assert (await share_access.get_share_link(link["token"]))["revoked"] == 1

    @pytest.mark.asyncio
    async def test_other_user_cannot_revoke(self):
        cfg.AUTH_ENABLED = True
        link = await share_access.create_share_link("sess1", created_by="u1")
        with pytest.raises(share_access.ShareAccessError) as e:
            await share_access.revoke_share_link(link["token"], "u2")
        assert e.value.status_code == 404          # 表现为"不存在"
        assert (await share_access.get_share_link(link["token"]))["revoked"] == 0

    @pytest.mark.asyncio
    async def test_anonymous_revoke_skips_ownership_check(self):
        """认证关闭时 actor=None，不校验归属（否则匿名模式无法管理自己的链接）。"""
        cfg.AUTH_ENABLED = False
        link = await share_access.create_share_link("sess1", created_by=None)
        await share_access.revoke_share_link(link["token"], None)
        assert (await share_access.get_share_link(link["token"]))["revoked"] == 1

    @pytest.mark.asyncio
    async def test_list_hides_token(self):
        """列表不得把 token（哪怕是摘要）返回给前端 —— 凭据不进列表接口。"""
        await share_access.create_share_link("sess1", created_by="u1")
        rows = await share_access.list_share_links("sess1")
        assert len(rows) == 1
        assert rows[0]["token"] is None


# ===== 5. HTTP 层 =====

class TestShareEndpoints:
    @pytest_asyncio.fixture
    async def client(self, tmp_path):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as c:
            yield c

    def test_shared_endpoint_needs_no_login(self, client):
        """免登录只读 —— 这是分享链接存在的全部意义。"""
        cfg.AUTH_ENABLED = True
        # 先由"会话主人"签发（认证关闭时签发，避免构造登录态的噪音）
        cfg.AUTH_ENABLED = False
        created = client.post("/api/sessions/sess1/share",
                              json={"include_detail": False, "expires_days": 30})
        assert created.status_code == 201
        token = created.json()["share"]["token"]

        cfg.AUTH_ENABLED = True      # 开启认证后，外部访问仍应可读
        resp = client.get(f"/api/shared/{token}")
        assert resp.status_code == 200
        assert resp.json()["overall_score"] == 3.8

    def test_revoked_link_returns_404(self, client):
        cfg.AUTH_ENABLED = False
        token = client.post("/api/sessions/sess1/share", json={}).json()["share"]["token"]
        assert client.delete(f"/api/shares/{token}").status_code == 200
        assert client.get(f"/api/shared/{token}").status_code == 404

    def test_bad_token_returns_404(self, client):
        cfg.AUTH_ENABLED = False
        assert client.get("/api/shared/nope-not-a-token").status_code == 404

    def test_share_nonexistent_session_404(self, client):
        """会话不存在 → 404（与会话归属同一口径，不泄露存在性）。"""
        cfg.AUTH_ENABLED = False
        assert client.post("/api/sessions/does-not-exist/share", json={}).status_code == 404



    def test_shared_endpoint_is_readonly(self, client):
        """只读是硬约束：分享 token 不能用来改任何数据。

        这里用"分享端点只接受 GET"来体现——POST/PATCH/DELETE 一律 405，
        意味着不存在"拿 token 改数据"的路径。
        """
        cfg.AUTH_ENABLED = False
        token = client.post("/api/sessions/sess1/share", json={}).json()["share"]["token"]
        assert client.post(f"/api/shared/{token}", json={}).status_code == 405
        assert client.patch(f"/api/shared/{token}", json={}).status_code == 405
        assert client.delete(f"/api/shared/{token}").status_code == 405
