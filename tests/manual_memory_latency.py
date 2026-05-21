"""
Manual latency probe for the memory organizer.

Run from the repo root:
    .\\.venv\\Scripts\\python.exe tests\\manual_memory_latency.py

This script intentionally uses the real organizer model configured by env vars.
It prints timing JSON and writes all benchmark data into a temporary directory.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def timed(name: str, fn: Callable[[], Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        value = fn()
        ok = True
        error = None
    except Exception as exc:  # pragma: no cover - manual script
        value = None
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    return {
        "name": name,
        "ok": ok,
        "seconds": round(time.perf_counter() - start, 3),
        "result": value,
        "error": error,
    }


def sample_bazi_payload() -> Dict[str, Any]:
    return {
        "raw_data": {
            "性别": "女",
            "阳历": "1992-08-16 09:30:00",
            "八字": "壬申 戊申 甲寅 己巳",
            "日主": "甲木",
            "生肖": "猴",
            "大运": [
                {"干支": "己酉", "起始年份": 2001, "结束年份": 2010},
                {"干支": "庚戌", "起始年份": 2011, "结束年份": 2020},
                {"干支": "辛亥", "起始年份": 2021, "结束年份": 2030},
            ],
        }
    }


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    os.environ.setdefault("ENABLE_VECTOR_MEMORY", "false")
    os.environ.setdefault("ENABLE_SHARED_MEMORY", "true")
    os.environ.setdefault("MEMORY_ORGANIZER_TIMEOUT_S", "45")

    from memory_manager import BaziMemoryManager

    results = []
    with tempfile.TemporaryDirectory(prefix="memory-latency-") as tmp:
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            manager = BaziMemoryManager(user_data_dir="user_data_latency")
            user_id = "latency_probe_user"
            manager.update_chart_facts_from_bazi_payload(
                user_id=user_id,
                user_info={"name": "latency", "gender": 0, "birth_time": "1992-08-16T09:30:00+08:00"},
                bazi_info=sample_bazi_payload(),
            )

            chat_event = {
                "event_id": "bench_chat_1",
                "type": "liuyao_chat",
                "dimension": "六爻占卜",
                "version": "professional",
                "content": "User: 我担心事业方向，不知道要不要换城市。\nAssistant: 建议先稳住现金流，再比较城市机会的长期收益。",
                "model_used": os.getenv("DEEPSEEK_DIALOG_MODEL") or "manual",
                "user_background": {"job": "产品经理"},
                "importance": 5,
                "extra": {"source": "manual_latency"},
            }
            analysis_event = {
                "event_id": "bench_analysis_1",
                "type": "analysis",
                "dimension": "事业运势分析",
                "version": "classic",
                "content": "结论：事业适合以专业能力和稳定平台为主线。依据：官杀透出，印星可用。建议：避免短期冲动跳槽。",
                "model_used": os.getenv("DEEPSEEK_ANALYSIS_MODEL") or "manual",
                "user_background": {"job": "产品经理"},
                "importance": 8,
                "extra": {"source": "manual_latency"},
            }

            results.append(
                timed(
                    "build_shared_memory_context",
                    lambda: {"chars": len(manager.build_shared_memory_context(user_id, "事业运势分析", "事业"))},
                )
            )
            results.append(
                timed(
                    "summarize_event_memory_chat",
                    lambda: {
                        "memory_type": manager.summarize_event_memory(user_id, chat_event).get("memory_type"),
                    },
                )
            )
            results.append(
                timed(
                    "summarize_dimension_insight",
                    lambda: {
                        "keys": sorted(
                            manager.summarize_dimension_insight(
                                user_id=user_id,
                                dimension="事业运势分析",
                                version="classic",
                                analysis_content=analysis_event["content"],
                                model_used=analysis_event["model_used"],
                            ).keys()
                        )
                    },
                )
            )
            results.append(
                timed(
                    "organize_analysis_event_memory_combined",
                    lambda: {
                        "keys": sorted(manager.organize_analysis_event_memory(user_id, analysis_event).keys()),
                    },
                )
            )
            for idx in range(3):
                manager.append_raw_event(
                    user_id=user_id,
                    event_type="liuyao_chat" if idx == 0 else "analysis",
                    dimension="六爻占卜" if idx == 0 else "事业运势分析",
                    version="professional" if idx == 0 else "classic",
                    content=chat_event["content"] if idx == 0 else analysis_event["content"],
                    model_used="manual",
                    user_background={"job": "产品经理"},
                    importance=5 if idx == 0 else 8,
                    extra={"source": "manual_latency", "idx": idx},
                )
            results.append(
                timed(
                    "process_pending_events_batch_3",
                    lambda: manager.process_pending_events(user_id=user_id, max_events=3),
                )
            )
            results.append(
                timed(
                    "get_memory_status",
                    lambda: manager.get_memory_status(user_id),
                )
            )
        finally:
            os.chdir(old_cwd)

    print(
        json.dumps(
            {
                "model": os.getenv("MEMORY_ORGANIZER_MODEL") or os.getenv("DEEPSEEK_FAST_MODEL") or os.getenv("DEEPSEEK_MODEL"),
                "base_url": os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE"),
                "vector_memory": os.getenv("ENABLE_VECTOR_MEMORY"),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
