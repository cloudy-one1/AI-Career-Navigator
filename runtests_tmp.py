import subprocess, os, re

os.chdir(r"F:\Desktop\AI模拟面试官")
r = subprocess.run(
    ["python", "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"],
    capture_output=True,
)
text = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
# 只保留汇总行（passed/failed/error）与失败明细
lines = text.splitlines()
summary = [l for l in lines if re.search(r"passed|failed|error|warning summary|FAILED|ERROR", l, re.I)]
print("\n".join(summary[-25:]))
print("returncode:", r.returncode)
