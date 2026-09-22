# 文档索引

> `docs/` 只放**对外公开**的文档：外部读者需要看懂、上手、复用的部分。
> 课程过程稿、竞品调研、答辩与验收材料属于本地资料，由 `.gitignore` 的 `docs/*`
> 规则排除（本地保留、不入库），需要公开时在 `.gitignore` 里补一条 `!` 白名单。

## 公开文档

| 文件 | 说明 |
|---|---|
| [architecture.md](architecture.md) | 技术栈、L1–L4 分层契约、**全量代码地图**、诊断体系与面试模式、API 概览 |
| [testing.md](testing.md) | 测试五层分工、常用命令、CI 与 dependabot 口径 |
| [API.md](API.md) | 后端接口全量参考：59 个 HTTP 端点 + 1 个 WebSocket，含限流档位与 WS 消息协议 |
| [LIMITATIONS.md](LIMITATIONS.md) | 已知局限与架构取舍全文（含可选演进方向） |
| [changelog-archive.md](changelog-archive.md) | v7.x 及更早的完整迭代叙事（v8.9 自 CHANGELOG.md 拆出） |

## 仓库根的对外文档

| 文件 | 说明 |
|---|---|
| `../README.md` | 面向使用者的入口：是什么、怎么跑起来 |
| `../CHANGELOG.md` | 近期版本迭代叙事（v8.x 起） |
| `../CHARTER.md` | 项目宪章：产品命题、不变的架构约束、决策记录卡 DC-01 ~ DC-10、范围纪律 |
| `../.github/CONTRIBUTING.md` | 开发环境、提交规范、推送前必做清单 |
| `../.github/SECURITY.md` | 内容护栏的真实边界与漏洞披露方式 |

## 文档约定

1. **新增文档先问一句"外部读者需要它吗"**：需要 → 放本目录并在 `.gitignore` 登记白名单、
   更新本索引；不需要 → 放 `docs/archive/` 或 `docs/research/`，自动不公开。
2. **公开文档里不要链到未入库的文件**——那些链接在 GitHub 上会 404（本地一切正常）。
   需要提及时用纯文本写文件名并注明「本地文档」。这条由
   `../tests/test_repo_hygiene.py` 在 CI 断言兜底。
3. 二进制产物（docx / pdf / pptx）不放本目录，受 `.gitignore` 扩展名规则约束。
4. 文档里的数字（用例数、端点数）必须实测后写入，改动代码时同步复核。
