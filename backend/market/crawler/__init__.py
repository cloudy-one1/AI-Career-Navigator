"""
[AI模拟面试官][B档内嵌] job-crawler 实时采集子包。

从开源项目 job-crawler (https://github.com/cloudy-one1/job-crawler) 内嵌整合，
提供 51job 实时采集能力：

- ``python_job_scraper``  采集器本体（Playwright + Stealth 过 WAF，原样保留）
- ``salary_parser``       薪资解析（千元/月，原样保留）
- ``adapters``            采集原始数据 → 标准岗位 dict（对齐 store.upsert_jobs 契约）
- ``tasks``               后台任务管理器（互斥、进度回调、线程安全）

分层约定（见 CHARTER.md）：本子包随 ``backend.market`` 位于 L2 层，
只允许依赖 ``backend.config / backend.logger / backend.market.*``，
不得 import ``backend.main``（L4）或 L3 业务模块。
"""
