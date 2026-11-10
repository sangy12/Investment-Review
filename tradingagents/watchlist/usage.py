"""Record returned token counts, without prompts, credentials or quota guesses."""

import json
import os
import re
import threading
import uuid
from contextlib import suppress
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

from tradingagents.llm_clients.plan_errors import is_subscription_usage_limit

usage_context = ContextVar("watchlist_usage", default=None)
register_configure_hook(usage_context, inheritable=True)


def _number(value):
    return value if type(value) is int and value >= 0 else 0


def _model(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", value) else "unknown"


class UsageTracker(BaseCallbackHandler):
    """One process attempt, including parallel analysts and the final review.

    Counts logical LLM calls. SDK-internal HTTP retries, previous checkpoint
    attempts and the subscription's weighted quota are not observable here.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.phase = "graph"
        self.resumed_from_step = None
        self._lock = threading.RLock()
        self._starts = {}
        self._seen = set()
        self._rows = {}
        self._status = "running"
        self._error_counts = {}
        self._write()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        params = kwargs.get("invocation_params") or {}
        metadata = kwargs.get("metadata") or {}
        model = _model(metadata.get("ls_model_name") or params.get("model") or params.get("model_name"))
        with self._lock:
            self._starts[str(run_id)] = (model, self.phase)

    def on_llm_end(self, response, *, run_id, **kwargs):
        try:
            message = response.generations[0][0].message
        except (IndexError, AttributeError, TypeError):
            message = None
        usage = getattr(message, "usage_metadata", None)
        metadata = getattr(message, "response_metadata", {}) or {}
        with self._lock:
            model, phase = self._starts.pop(str(run_id), ("unknown", self.phase))
            model = _model(metadata.get("model_name") or metadata.get("model") or model)
            self._record(run_id, model, phase, usage, failed=False)

    def on_llm_error(self, error, *, run_id, **kwargs):
        with self._lock:
            if str(run_id) not in self._seen and is_subscription_usage_limit(error):
                code = "subscription_usage_limit"
                self._error_counts[code] = self._error_counts.get(code, 0) + 1
            model, phase = self._starts.pop(str(run_id), ("unknown", self.phase))
            self._record(run_id, model, phase, None, failed=True)

    def _record(self, run_id, model, phase, usage, *, failed):
        key = str(run_id)
        if key in self._seen:
            return
        self._seen.add(key)
        row = self._rows.setdefault((model, phase), {
            "model": model, "phase": phase, "completed_calls": 0, "failed_calls": 0,
            "calls_with_usage": 0, "calls_without_usage": 0,
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "cached_input_tokens": 0, "reasoning_tokens": 0,
        })
        row["failed_calls" if failed else "completed_calls"] += 1
        valid = isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0
                                               for k in ("input_tokens", "output_tokens", "total_tokens"))
        if valid:
            row["calls_with_usage"] += 1
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                row[field] += usage[field]
            row["cached_input_tokens"] += _number((usage.get("input_token_details") or {}).get("cache_read"))
            row["reasoning_tokens"] += _number((usage.get("output_token_details") or {}).get("reasoning"))
        elif not failed:
            row["calls_without_usage"] += 1
        self._write()

    def snapshot(self):
        with self._lock:
            rows = deepcopy(list(self._rows.values()))
            fields = ("completed_calls", "failed_calls", "calls_with_usage", "calls_without_usage",
                      "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_tokens")
            totals = {field: sum(row[field] for row in rows) for field in fields}
            return {"schema": 1, "status": self._status, "coverage": "current_process_attempt",
                    "resumed_from_step": self.resumed_from_step, "error_counts": dict(self._error_counts),
                    "quota_percentage": None, "totals": totals, "by_model_and_phase": rows,
                    "notes": ["缓存输入包含在输入 token 中；推理 token 包含在输出 token 中，不重复相加。",
                              "仅统计接口返回的 token；SDK 内部重试和断点恢复前的调用不回算。",
                              "Token 数不能换算 ChatGPT 订阅额度百分比或 API 账单金额。"]}

    def finish(self, status):
        with self._lock:
            self._status = status
            self._write()

    def _write(self):
        # A telemetry I/O failure must not discard a completed research report.
        temp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
        except OSError:
            pass
        finally:
            with suppress(OSError):
                temp.unlink(missing_ok=True)


def usage_markdown(data):
    total = data["totals"]
    lines = ["## ChatGPT 用量（本次执行）", "",
             f"完成调用 {total['completed_calls']} 次；失败调用 {total['failed_calls']} 次；"
             f"未返回 token 用量的完成调用 {total['calls_without_usage']} 次。", "",
             "| 模型 / 阶段 | 完成调用 | 输入 token | 输出 token | 合计 token | 缓存输入（已含） | 推理（已含） |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for row in data["by_model_and_phase"]:
        lines.append(f"| {row['model']} / {row['phase']} | {row['completed_calls']} | "
                     f"{row['input_tokens']:,} | {row['output_tokens']:,} | {row['total_tokens']:,} | "
                     f"{row['cached_input_tokens']:,} | {row['reasoning_tokens']:,} |")
    lines.extend(["", f"已记录合计：**{total['total_tokens']:,} token**。", "", *data["notes"]])
    return "\n".join(lines) + "\n"
