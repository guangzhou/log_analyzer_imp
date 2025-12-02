import logging
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

def get_logger(
    name: str = "app",
    level=logging.INFO,
    log_dir="logs",
    rotate="day",        # day / size / none
    max_bytes=50*1024*1024,  # 50MB
    backup_count=7,
):
    """
    通用生产级 logger
    """

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 日志格式
    fmt = logging.Formatter(
        "[%(asctime)s][%(levelname)s][%(filename)s:%(lineno)d] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    # === 控制台输出 ===
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    # === 文件输出 ===
    log_file = os.path.join(log_dir, f"{name}.log")

    if rotate == "day":
        # 按天自动滚动
        file_handler = TimedRotatingFileHandler(
            log_file, when="midnight", interval=1, backupCount=backup_count,
            encoding="utf-8"
        )

    elif rotate == "size":
        # 按大小滚动
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count,
            encoding="utf-8"
        )

    else:
        # 不滚动
        file_handler = logging.FileHandler(log_file, encoding="utf-8")

    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
