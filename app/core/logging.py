"""
应用日志约定（摘要）：

- 使用 ``get_logger(__name__)`` 获取与模块绑定的记录器名称，便于在聚合日志中按 ``name`` 过滤。
- 消息优先使用结构化占位符：``logger.info("order id=%s status=%s", oid, st)``，避免 ``f-string`` 在无输出时仍求值。
- 异常用 ``logger.exception("context")`` 或 ``logger.error("...", exc_info=True)``。
- HTTP 请求内会自动注入 ``user``、``req``（请求 ID）；客户端可传 ``X-Request-ID`` 便于链路追踪。
- **单价等敏感变更**请使用 ``log_price_change()``，写入独立按日滚动的 ``price_audit.log``。

环境变量：
``LOG_LEVEL``、``LOG_DIR``、``LOG_ENABLE_CONSOLE``（默认 1）、``LOG_ENABLE_FILE``（默认 1）、
``LOG_RETENTION_DAYS``（按天滚动的历史文件保留份数，默认 30，对应约 30 天）。
"""

from __future__ import annotations

import contextvars
import logging
import os
import uuid
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Mapping, Optional

_current_user = contextvars.ContextVar("current_user", default="-")
_request_id = contextvars.ContextVar("request_id", default="-")

PRICE_AUDIT_LOGGER_NAME = "audit.price"


def set_log_user(user: Optional[str]) -> contextvars.Token:
    return _current_user.set(user or "-")


def reset_log_user(token: contextvars.Token) -> None:
    _current_user.reset(token)


def set_log_request_id(header_value: Optional[str] = None) -> contextvars.Token:
    """绑定当前协程/线程的请求 ID。若传入非空 header（如 X-Request-ID），则规范化后使用，否则生成 UUID。"""
    if header_value:
        clean = header_value.strip()[:64]
        if clean:
            return _request_id.set(clean)
    return _request_id.set(str(uuid.uuid4()))


def reset_log_request_id(token: contextvars.Token) -> None:
    _request_id.reset(token)


class _ContextFilter(logging.Filter):
    """为每条记录注入 user、request_id，供 Formatter 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.user = _current_user.get()
        record.request_id = _request_id.get()
        return True


class _AppFormatter(logging.Formatter):
    """统一时间格式到毫秒，便于排序与检索。"""

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        ct = datetime.fromtimestamp(record.created)
        return f"{ct.strftime('%Y-%m-%d %H:%M:%S')}.{int(record.msecs):03d}"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _retention_days() -> int:
    raw = os.getenv("LOG_RETENTION_DAYS", "30")
    try:
        n = int(raw)
        return max(1, min(n, 3650))
    except ValueError:
        return 30


def _get_log_dir() -> Path:
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _get_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _get_formatter() -> logging.Formatter:
    return _AppFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | req=%(request_id)s | user=%(user)s | %(message)s",
    )


def _quiet_noisy_libraries(root_level: int) -> None:
    """在非 DEBUG 下压低常见 HTTP 客户端库的日志音量。"""
    if root_level <= logging.DEBUG:
        return
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _attach_timed_file(
    log_dir: Path,
    filename: str,
    level: int,
    formatter: logging.Formatter,
    ctx_filter: _ContextFilter,
    backup_count: int,
) -> TimedRotatingFileHandler:
    h = TimedRotatingFileHandler(
        log_dir / filename,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        utc=False,
    )
    h.setLevel(level)
    h.setFormatter(formatter)
    h.addFilter(ctx_filter)
    return h


def _configure_price_audit_logger(
    log_dir: Path,
    formatter: logging.Formatter,
    ctx_filter: _ContextFilter,
    backup_count: int,
    force: bool,
) -> None:
    log = logging.getLogger(PRICE_AUDIT_LOGGER_NAME)
    log.setLevel(logging.INFO)
    if force:
        for h in log.handlers[:]:
            log.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
    if log.handlers:
        return
    log.propagate = False
    log.addHandler(
        _attach_timed_file(
            log_dir,
            "price_audit.log",
            logging.INFO,
            formatter,
            ctx_filter,
            backup_count,
        )
    )


def setup_logging(force: bool = False) -> None:
    """
    配置根记录器：控制台 + app.log + error.log（均按**自然日**午夜滚动）。
    单价审计写入 ``price_audit.log``（按日滚动、不向上冒泡到根）。

    :param force: 为 True 时清空已有根 handler 后重新配置（多用于测试）。
    """
    log_dir = _get_log_dir()
    level = _get_log_level()
    backup_count = _retention_days()

    root = logging.getLogger()
    if root.handlers and not force:
        _configure_price_audit_logger(
            log_dir,
            _get_formatter(),
            _ContextFilter(),
            backup_count,
            force=False,
        )
        return

    if force:
        for h in root.handlers[:]:
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

    root.setLevel(level)

    formatter = _get_formatter()
    ctx_filter = _ContextFilter()

    enable_console = _env_bool("LOG_ENABLE_CONSOLE", True)
    enable_file = _env_bool("LOG_ENABLE_FILE", True)

    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(ctx_filter)
        root.addHandler(console_handler)

    if enable_file:
        app_file = _attach_timed_file(
            log_dir,
            "app.log",
            level,
            formatter,
            ctx_filter,
            backup_count,
        )
        error_file = _attach_timed_file(
            log_dir,
            "error.log",
            logging.ERROR,
            formatter,
            ctx_filter,
            backup_count,
        )
        root.addHandler(app_file)
        root.addHandler(error_file)

    _configure_price_audit_logger(log_dir, formatter, ctx_filter, backup_count, force=True)
    _quiet_noisy_libraries(level)


def log_price_change(action: str, details: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> None:
    """
    写入 ``price_audit.log``（与根日志相同的 user / req 上下文）。

    ``action`` 为短枚举名；其余字段以 ``key=value`` 追加，便于检索。
    """
    parts: list[str] = [f"action={action}"]
    merged: dict[str, Any] = {}
    if details:
        merged.update(dict(details))
    merged.update(kwargs)
    for k in sorted(merged.keys()):
        v = merged[k]
        if v is None:
            continue
        parts.append(f"{k}={v!r}")
    logging.getLogger(PRICE_AUDIT_LOGGER_NAME).info("%s", " ".join(parts))


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    返回标准库 ``Logger``，名称建议传入 ``__name__``。
    日志仅通过根记录器的 handler 输出（含 ``name`` 字段），不再附加按名称分文件。
    """
    logger_name = name if name is not None else "app"
    return logging.getLogger(logger_name)
