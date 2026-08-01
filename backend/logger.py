"""
v3.1 集中日志配置：RotatingFileHandler（5MB × 3 备份）+ 控制台输出。

用法：在 main.py 入口处调用 setup_logging()，其余模块沿用
    logger = logging.getLogger(__name__)
"""
import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(
    log_dir: str = "data",
    log_file: str = "app.log",
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,   # 5 MB
    backup_count: int = 3,
) -> None:
    """配置日志：文件旋转 + 控制台双输出。"""

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    # 根 logger
    root = logging.getLogger()
    root.setLevel(level)

    # 避免重复添加（uvicorn --reload 会重新导入）
    if root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s:%(lineno)d: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件旋转输出
    fh = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 控制台输出
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # 抑制过于啰嗦的第三方
    for noisy in ("httpx", "httpcore", "urllib3", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root.info("日志系统已初始化: %s (max %d MB × %d 备份)", log_path, max_bytes // (1024 * 1024), backup_count)
