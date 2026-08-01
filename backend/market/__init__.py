"""
[v3.0] 市场数据子包：从 job-crawler 导入真实岗位 → 清洗 → 存储 → 服务。

模块划分：
- importer.py  导入适配层：读取 job-crawler data.db → 字段映射（无需 Playwright）
- cleaner.py   清洗层：薪资/经验/学历标准化 + 技能标签提取（纯函数，可单测）
- store.py     存储层：独立 data/market.db（与面试库分离，生命周期独立）
- service.py   服务层：导入调度 + 岗位画像快照集成
"""
