"""Returned usage is counted across parallel agents and structured review calls."""

import json
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import RunnableParallel

from tradingagents.watchlist.usage import UsageTracker, usage_context


def message(model="gpt-6.1-terra", usage=True):
    return AIMessage(content="private prompt/response must never be persisted",
                     response_metadata={"model_name": model, "secret": "must-not-persist"},
                     usage_metadata={"input_tokens": 100, "output_tokens": 30, "total_tokens": 130,
                                     "input_token_details": {"cache_read": 60},
                                     "output_token_details": {"reasoning": 20}} if usage else None)


def result(msg):
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


def test_parallel_context_capture_review_and_cleanup(tmp_path):
    tracker = UsageTracker(tmp_path / "usage.json")
    token = usage_context.set(tracker)
    try:
        RunnableParallel(
            analyst=GenericFakeChatModel(messages=iter([message()])),
            manager=GenericFakeChatModel(messages=iter([message("gpt-6.1-sol")])),
        ).invoke("fixture")
        tracker.phase = "review"
        GenericFakeChatModel(messages=iter([message()])).invoke("fixture")
    finally:
        usage_context.reset(token)
    tracker.finish("completed")
    data = tracker.snapshot()
    assert data["totals"] == {"completed_calls": 3, "failed_calls": 0, "calls_with_usage": 3,
                              "calls_without_usage": 0, "input_tokens": 300, "output_tokens": 90,
                              "total_tokens": 390, "cached_input_tokens": 180, "reasoning_tokens": 60}
    assert {(r["model"], r["phase"]) for r in data["by_model_and_phase"]} == {
        ("gpt-6.1-terra", "graph"), ("gpt-6.1-sol", "graph"), ("gpt-6.1-terra", "review")}
    GenericFakeChatModel(messages=iter([message()])).invoke("outside tracker")
    assert tracker.snapshot() == data
    raw = (tmp_path / "usage.json").read_text()
    assert "private" not in raw and "must-not-persist" not in raw
    assert json.loads(raw)["quota_percentage"] is None


def test_dedup_missing_usage_and_private_errors(tmp_path):
    tracker = UsageTracker(tmp_path / "usage.json")
    run = uuid4()
    tracker.on_llm_end(result(message()), run_id=run)
    tracker.on_llm_end(result(message()), run_id=run)
    tracker.on_llm_end(result(message(usage=False)), run_id=uuid4())
    failed = uuid4()
    tracker.on_chat_model_start({}, [], run_id=failed,
                                invocation_params={"model": "gpt-6.1-sol", "api_key": "sensitive"})
    tracker.on_llm_error(RuntimeError("Authorization: sensitive"), run_id=failed)
    tracker.finish("failed")
    data = tracker.snapshot()
    assert data["totals"]["completed_calls"] == 2
    assert data["totals"]["failed_calls"] == 1
    assert data["totals"]["calls_without_usage"] == 1
    assert data["totals"]["total_tokens"] == 130
    assert "sensitive" not in (tmp_path / "usage.json").read_text()


def test_usage_write_failure_is_nonfatal(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("fixture")
    tracker = UsageTracker(blocked / "usage.json")
    tracker.on_llm_end(result(message()), run_id=uuid4())
    assert tracker.snapshot()["totals"]["total_tokens"] == 130


def test_usage_keeps_only_safe_subscription_error_code(tmp_path):
    import httpx
    from openai import APIError

    tracker = UsageTracker(tmp_path / "usage.json")
    error = APIError("The ChatGPT user has reached their Subscription Sharing usage limit. sensitive",
                     request=httpx.Request("POST", "https://api.openai.com/v1/responses"), body=None)
    run_id = uuid4()
    tracker.on_llm_error(error, run_id=run_id)
    tracker.on_llm_error(error, run_id=run_id)
    assert tracker.snapshot()["error_counts"] == {"subscription_usage_limit": 1}
    assert "sensitive" not in (tmp_path / "usage.json").read_text()
