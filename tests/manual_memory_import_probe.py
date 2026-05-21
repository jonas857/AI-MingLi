"""
Manual real-model import probe for memory organizer.

Run from the repo root with the project virtualenv:
    .\\.venv\\Scripts\\python.exe tests\\manual_memory_import_probe.py

The probe loads .env, disables vector memory, writes only to a temporary
directory, and prints the event status flow plus imported memory summaries.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


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


def sample_bazi_payload() -> Dict[str, Any]:
    return {
        "raw_data": {
            "\u6027\u522b": "\u5973",
            "\u9633\u5386": "1992-08-16 09:30:00",
            "\u516b\u5b57": "\u58ec\u7533 \u620a\u7533 \u7532\u5bc5 \u5df1\u5df3",
            "\u65e5\u4e3b": "\u7532\u6728",
            "\u751f\u8096": "\u7334",
            "\u5927\u8fd0": [
                {"\u5e72\u652f": "\u5df1\u9149", "\u8d77\u59cb\u5e74\u4efd": 2001, "\u7ed3\u675f\u5e74\u4efd": 2010},
                {"\u5e72\u652f": "\u5e9a\u620c", "\u8d77\u59cb\u5e74\u4efd": 2011, "\u7ed3\u675f\u5e74\u4efd": 2020},
                {"\u5e72\u652f": "\u8f9b\u4ea5", "\u8d77\u59cb\u5e74\u4efd": 2021, "\u7ed3\u675f\u5e74\u4efd": 2030},
            ],
        }
    }


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    os.environ.setdefault("ENABLE_VECTOR_MEMORY", "false")
    os.environ.setdefault("ENABLE_SHARED_MEMORY", "true")
    os.environ.setdefault("ENABLE_ASYNC_ORGANIZER", "true")
    os.environ.setdefault("MEMORY_ORGANIZER_TIMEOUT_S", "30")

    from memory_manager import BaziMemoryManager

    chat_dimension = "\u516d\u723b\u5360\u535c"
    analysis_dimension = "\u4e8b\u4e1a\u8fd0\u52bf\u5206\u6790"
    chat_content = (
        "User: \u6211\u6700\u8fd1\u4e00\u76f4\u62c5\u5fc3\u4e8b\u4e1a\u65b9\u5411\uff0c"
        "\u60f3\u77e5\u9053\u8981\u4e0d\u8981\u6362\u57ce\u5e02\u53d1\u5c55\uff0c"
        "\u4e5f\u6015\u73b0\u91d1\u6d41\u65ad\u6389\u3002"
        "\u8bf7\u8bb0\u4f4f\u6211\u504f\u597d\u7a33\u5065\u3001\u53ef\u6267\u884c\u7684\u5efa\u8bae\u3002\n"
        "Assistant: \u5efa\u8bae\u5148\u7a33\u4f4f\u4e3b\u7ebf\u6536\u5165\uff0c"
        "\u518d\u6bd4\u8f83\u57ce\u5e02\u673a\u4f1a\u7684\u957f\u671f\u6536\u76ca\uff0c"
        "\u4e0d\u8981\u53ea\u770b\u77ed\u671f\u7126\u8651\u3002"
    )
    analysis_content = (
        "\u7ed3\u8bba\uff1a\u4e8b\u4e1a\u9002\u5408\u4ee5\u7a33\u5b9a\u5e73\u53f0"
        "\u548c\u4e13\u4e1a\u80fd\u529b\u4e3a\u4e3b\u7ebf\u3002\n"
        "\u4f9d\u636e\uff1a\u547d\u76d8\u91cc\u5b98\u6740\u538b\u529b\u660e\u663e\uff0c"
        "\u9002\u5408\u628a\u538b\u529b\u8f6c\u6210\u89c4\u5219\u5185\u7684\u664b\u5347\u8def\u5f84\uff1b"
        "\u8d22\u661f\u865a\u6d6e\u65f6\u4e0d\u5b9c\u77ed\u671f\u51b2\u52a8\u8df3\u69fd\u3002\n"
        "\u5efa\u8bae\uff1a\u672a\u6765\u534a\u5e74\u5148\u79ef\u7d2f\u4f5c\u54c1\u4e0e"
        "\u53ef\u8fc1\u79fb\u80fd\u529b\uff0c\u518d\u8bc4\u4f30\u57ce\u5e02\u673a\u4f1a\u3002"
    )

    with tempfile.TemporaryDirectory(prefix="memory-import-probe-") as tmp:
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            manager = BaziMemoryManager(user_data_dir="user_data_probe")
            user_id = "real_model_import_probe"
            manager.update_chart_facts_from_bazi_payload(
                user_id=user_id,
                user_info={"name": "probe", "gender": 0, "birth_time": "1992-08-16T09:30:00+08:00"},
                bazi_info=sample_bazi_payload(),
            )
            event_ids = [
                manager.append_raw_event(
                    user_id=user_id,
                    event_type="liuyao_chat",
                    dimension=chat_dimension,
                    version="professional",
                    content=chat_content,
                    model_used=os.getenv("DEEPSEEK_DIALOG_MODEL") or "manual",
                    user_background={"job": "product manager"},
                    importance=5,
                    extra={"source": "manual_import_probe"},
                ),
                manager.append_raw_event(
                    user_id=user_id,
                    event_type="analysis",
                    dimension=analysis_dimension,
                    version="classic",
                    content=analysis_content,
                    model_used=os.getenv("DEEPSEEK_ANALYSIS_MODEL") or "manual",
                    user_background={"job": "product manager"},
                    importance=8,
                    extra={"source": "manual_import_probe"},
                ),
            ]
            before = manager.get_memory_status(user_id)
            process_runs = [manager.process_pending_events(user_id=user_id, max_events=5)]
            after = manager.get_memory_status(user_id)
            for _attempt in range(2):
                retryable = [
                    item.get("event_id")
                    for item in (after.get("latest") or [])
                    if item.get("status") == "failed_retryable" and item.get("event_id")
                ]
                if not retryable:
                    break
                for event_id in retryable:
                    manager.retry_memory_event(user_id, str(event_id))
                process_runs.append(manager.process_pending_events(user_id=user_id, max_events=5))
                after = manager.get_memory_status(user_id)
            items = manager.get_memory_items(user_id, include_disabled=True, allow_legacy_backfill=False)
            insights = manager.get_insights_doc(user_id)
            profile = manager.get_profile_doc(user_id)
            analysis_context = manager.build_shared_memory_context(
                user_id=user_id,
                dimension=analysis_dimension,
                query="\u662f\u5426\u6362\u57ce\u5e02\u53d1\u5c55",
            )
            chat_context = manager.build_shared_memory_context(
                user_id=user_id,
                dimension=chat_dimension,
                query="\u4e8b\u4e1a\u65b9\u5411\u548c\u7a33\u5065\u5efa\u8bae",
            )

            output = {
                "interpreter": sys.executable,
                "model": os.getenv("MEMORY_ORGANIZER_MODEL") or "deepseek-v4-flash",
                "event_ids": event_ids,
                "before_counts": before.get("counts"),
                "process_runs": process_runs,
                "after_counts": after.get("counts"),
                "latest_status": after.get("latest"),
                "memory_items": [
                    {
                        "id": item.get("id"),
                        "type": item.get("type"),
                        "domain": item.get("domain"),
                        "dimension": item.get("dimension"),
                        "confidence": item.get("confidence"),
                        "content_preview": (item.get("content") or "")[:220],
                        "evidence_refs": item.get("evidence_refs"),
                        "model": item.get("model"),
                    }
                    for item in items
                ],
                "insight_dimensions": sorted((insights.get("dimensions") or {}).keys()),
                "profile": {
                    "background": profile.get("background") or {},
                    "preferences": profile.get("preferences") or {},
                    "tags": profile.get("tags") or [],
                    "feedback_count": len(profile.get("feedback") or []),
                },
                "analysis_context_chars": len(analysis_context),
                "analysis_context_sections": [
                    section
                    for section in (
                        "<pinned_memories>",
                        "<chart_facts>",
                        "<support_profile>",
                        "<domain_insights>",
                        "<episodes>",
                        "<vector_supplement>",
                    )
                    if section in analysis_context
                ],
                "analysis_context_preview": analysis_context[:900],
                "chat_context_chars": len(chat_context),
                "chat_context_sections": [
                    section
                    for section in (
                        "<pinned_memories>",
                        "<chart_facts>",
                        "<support_profile>",
                        "<domain_insights>",
                        "<episodes>",
                        "<vector_supplement>",
                    )
                    if section in chat_context
                ],
                "chat_context_preview": chat_context[:900],
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    main()
