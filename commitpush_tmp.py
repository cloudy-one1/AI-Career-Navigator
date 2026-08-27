import subprocess, os

os.chdir(r"F:\Desktop\AI模拟面试官")

def run(cmd, input_bytes=None):
    return subprocess.run(cmd, input=input_bytes, capture_output=True)

def w(s):
    with open("_cp_result.txt", "a", encoding="utf-8") as f:
        f.write(s + "\n")

open("_cp_result.txt", "w", encoding="utf-8").close()

# 1) 暂存全部改动，但显式排除不应入库的二进制产品文档
r0 = run(["git", "add", "-A"])
w("add rc: %s" % r0.returncode)
# 将 .docx 从索引中移除（若被加入），保持仓库干净
r_rm = run(["git", "reset", "HEAD", "AI模拟面试官产品介绍_V1.0.docx"], )
w("reset docx rc: %s" % r_rm.returncode)

# 确认最终将提交的文件清单（排除 .docx）
st = run(["git", "status", "--short"]).stdout.decode("utf-8", "replace")
w("staged status:\n" + st)

msg = (
    "v4.0: 前端 Vite 工程化迁移 + 职业规划模块 + 分层契约加固\n"
    "\n"
    "改了什么:\n"
    "1) 前端从原生 ES Module 迁移到 Vite 构建：js/css 移入 frontend/src，新增 vite.config.js、"
    "package.json、package-lock.json、frontend/src/main.js 与拆分后的 CSS（tokens/base/components/pages）。\n"
    "2) 新增职业规划模块 backend/career_planner.py（L3 业务逻辑）及对应测试，"
    "与 gap_analyzer 分工：前者做纵向路径推理、后者做横截面匹配，遵守双 Agent 不可合并的分离精神。\n"
    "3) 引入 import-linter 分层依赖契约（.importlinter），将 career_planner 纳入 L3 层，"
    "与 CHARTER.md 分层约束同步；新增 run.py lint 入口。\n"
    "4) 更新 .gitignore（node_modules/、frontend/dist/）、requirements.txt、run.py、"
    "CODEBUDDY.md/README.md/CHANGELOG.md/CHARTER.md 及 week6/week7 等多份文档。\n"
    "\n"
    "为什么改:\n"
    "这是一次面向工程化与功能扩展的大版本迭代：前端引入构建工具以支持模块化与可维护性，"
    "后端新增职业规划能力补全'诊断-匹配-规划'闭环，并以 import-linter 把分层约束落到 CI 可执行契约。"
    "测试套件由 223 增至 268 用例且全绿，未破坏既有功能。\n"
    "注意：AI模拟面试官产品介绍_V1.0.docx 为二进制产品文档，按约定不入库，已从本次提交排除。\n"
)

r1 = run(["git", "commit", "-F", "-"], input_bytes=msg.encode("utf-8"))
w("commit rc: %s" % r1.returncode)
w(r1.stdout.decode("utf-8", "replace"))
w(r1.stderr.decode("utf-8", "replace"))

if r1.returncode == 0:
    r2 = run(["git", "push", "origin", "master"])
    w("push rc: %s" % r2.returncode)
    w(r2.stdout.decode("utf-8", "replace"))
    w(r2.stderr.decode("utf-8", "replace"))

print("DONE")
