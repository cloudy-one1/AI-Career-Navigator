"""
market/crawler/tasks.py 测试：参数校验 / 任务注册 / 单实例互斥 /
状态查询 / 终态任务 TTL 惰性清理。

说明：真实采集需 playwright + 浏览器，这里用假线程替换 threading.Thread，
只验证任务状态机与并发约束，不触发 scrape_jobs。
"""

import time

from backend.market.crawler import tasks
from backend.market.crawler.tasks import CrawlTask


class _FakeThread:
    """假线程：记录是否 start，不真正执行采集。"""

    def __init__(self, *args, **kwargs):
        self.started = False

    def start(self):
        self.started = True


class TestValidate:
    """validate() 参数校验"""

    def test_valid(self):
        assert tasks.validate("python", ["北京", "上海"], 2) is None

    def test_empty_keyword(self):
        assert tasks.validate("  ", ["北京"], 2) is not None

    def test_city_limit_exceeded(self):
        cities = [f"城市{i}" for i in range(6)]  # 超过 5 上限
        assert tasks.validate("python", cities, 2) is not None

    def test_pages_range(self):
        assert tasks.validate("python", ["北京"], 0) is not None
        assert tasks.validate("python", ["北京"], 6) is not None
        assert tasks.validate("python", ["北京"], "x") is not None


class TestStartCrawl:
    """start_crawl() 任务注册与单实例互斥"""

    def setup_method(self):
        tasks._tasks.clear()

    def teardown_method(self):
        tasks._tasks.clear()

    def test_start_returns_task(self, monkeypatch):
        monkeypatch.setattr("threading.Thread", _FakeThread)
        task, err = tasks.start_crawl("python", ["北京"], 2)
        assert err == ""
        assert task is not None
        assert task.status == "running"
        assert task.keyword == "python"
        assert task.cities == ["北京"]
        assert task.pages == 2
        assert task.id in tasks._tasks

    def test_mutex_single_running(self, monkeypatch):
        monkeypatch.setattr("threading.Thread", _FakeThread)
        t1, _ = tasks.start_crawl("python", ["北京"], 2)
        assert t1 is not None
        # 第二个任务应被互斥拒绝
        t2, err = tasks.start_crawl("java", ["上海"], 2)
        assert t2 is None
        assert "进行中" in err

    def test_validation_error_returns_none(self):
        task, err = tasks.start_crawl("", ["北京"], 2)
        assert task is None
        assert err


class TestGetStatus:
    """get_status() 状态查询与 TTL 清理"""

    def setup_method(self):
        tasks._tasks.clear()

    def teardown_method(self):
        tasks._tasks.clear()

    def test_missing_task(self):
        assert tasks.get_status("nope") is None

    def test_running_task_kept(self):
        task = CrawlTask(id="t1", keyword="python", cities=["北京"], pages=2, sort_type="0")
        tasks._tasks[task.id] = task
        got = tasks.get_status("t1")
        assert got is not None
        assert got.status == "running"

    def test_expired_done_task_cleaned(self):
        """v8.18: TTL 以 finished_at（终态时刻）计，不再按 created_at——
        运行超 10 分钟的任务完成后第一次轮询即被弹出是原缺陷。"""
        task = CrawlTask(id="old", keyword="python", cities=["北京"], pages=2, sort_type="0")
        task.status = "done"
        task.finished_at = time.time() - 700  # 超过 TTL(600s)
        tasks._tasks[task.id] = task
        assert tasks.get_status("old") is None
        assert "old" not in tasks._tasks

    def test_long_running_task_not_ttl_cleaned(self):
        """v8.18: running 任务不因 created_at 过旧被误清——此前 5城×5页的任务
        运行超 10 分钟后，完成状态第一次轮询就被弹出，前端永远看不到结果。"""
        task = CrawlTask(id="slow", keyword="python", cities=["北京"], pages=5, sort_type="0")
        task.status = "running"
        task.created_at = time.time() - 700
        tasks._tasks[task.id] = task
        got = tasks.get_status("slow")
        assert got is not None and got.status == "running"

    def test_hard_timeout_forces_failed_and_releases_slot(self, monkeypatch):
        """v8.18: running 任务超过硬超时+缓冲 → 强置 failed，采集槽随之释放
        （采集线程僵死在 page.evaluate 时唯一的自动恢复手段）。"""
        task = CrawlTask(id="stuck", keyword="python", cities=["北京"], pages=5, sort_type="0")
        task.status = "running"
        task.created_at = time.time() - (tasks._HARD_DEADLINE + 120)
        tasks._tasks[task.id] = task
        got = tasks.get_status("stuck")
        assert got is not None and got.status == "failed"
        assert got.finished_at is not None
        # 强置 failed 后互斥解除：start_crawl 不再被"已有任务进行中"拒绝
        monkeypatch.setattr("threading.Thread", _FakeThread)
        task2, err2 = tasks.start_crawl("java", ["上海"], 2)
        assert task2 is not None and err2 == ""


class TestCancel:
    """v8.18: 协作式取消"""

    def setup_method(self):
        tasks._tasks.clear()

    def teardown_method(self):
        tasks._tasks.clear()

    def test_cancel_sets_flag_only_for_running(self):
        task = CrawlTask(id="c1", keyword="python", cities=["北京"], pages=2, sort_type="0")
        tasks._tasks[task.id] = task
        got = tasks.cancel("c1")
        assert got is not None and got.cancel_requested is True

    def test_cancel_terminal_task_is_noop(self):
        task = CrawlTask(id="c2", keyword="python", cities=["北京"], pages=2, sort_type="0")
        task.status = "done"
        tasks._tasks[task.id] = task
        got = tasks.cancel("c2")
        assert got is not None and got.cancel_requested is False

    def test_cancel_missing_task_returns_none(self):
        assert tasks.cancel("ghost") is None

    def test_should_cancel_sees_flag_and_deadline(self):
        task = CrawlTask(id="c3", keyword="python", cities=["北京"], pages=2, sort_type="0")
        tasks._tasks[task.id] = task
        assert tasks._should_cancel("c3") is False
        task.cancel_requested = True
        assert tasks._should_cancel("c3") is True
        task.cancel_requested = False
        task.created_at = time.time() - (tasks._HARD_DEADLINE + 1)
        assert tasks._should_cancel("c3") is True

    def test_fresh_done_task_returned(self):
        task = CrawlTask(id="fresh", keyword="python", cities=["北京"], pages=2, sort_type="0")
        task.status = "done"
        tasks._tasks[task.id] = task
        got = tasks.get_status("fresh")
        assert got is not None
        assert got.status == "done"


class TestCrawlTaskModel:
    """CrawlTask dataclass 契约（前端轮询依赖字段）"""

    def test_to_dict_contains_expected_fields(self):
        task = CrawlTask(id="t", keyword="python", cities=["北京"], pages=2, sort_type="1")
        task.collected = 18
        task.pages_collected = {"北京": 2}
        task.message = "[北京] 第2页 +18条（累计 18）"
        task.status = "running"
        d = task.to_dict()
        for key in ("id", "keyword", "cities", "pages", "sort_type", "status",
                    "message", "collected", "pages_collected", "error", "created_at"):
            assert key in d
        assert d["collected"] == 18
        assert d["pages_collected"] == {"北京": 2}
        assert d["cities"] == ["北京"]
