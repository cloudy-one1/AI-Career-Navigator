## 改了什么

<!-- 一句话到几句话，说清这次的实质改动 -->

## 为什么改

<!-- 动机 / 关联的 Issue / 不做会怎样 -->

## 类型

- [ ] 缺陷修复（不改变既有行为契约）
- [ ] 新功能 / 行为变更
- [ ] 重构（外部行为不变）
- [ ] 文档 / 工程配置（CI、依赖、仓库卫生）

## 提交前自查

- [ ] `python run.py lint` 分层契约通过
- [ ] `pytest tests/ -q` 全量通过
- [ ] 改动前端：`cd frontend && npm run test` 与 `npm run build` 通过
- [ ] 用户可见变化已同步 `README.md`；版本迭代已追加 `CHANGELOG.md`
- [ ] 涉及架构约束 / 产品命题 / 有争议取舍：已更新 `CHARTER.md` 并补决策记录卡
- [ ] 新增根目录文件或目录：已在 `tests/test_repo_hygiene.py` 的白名单登记并写明用途
- [ ] 公开 Markdown 未链向未入库文件（`pytest tests/test_repo_hygiene.py -q` 可验）

## 遗留与风险

<!-- 没有就删掉这一节 -->
