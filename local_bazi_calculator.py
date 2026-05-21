import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class LocalBaziError(RuntimeError):
    pass


def _parse_bazi_result(raw_result: Any) -> Dict[str, Any]:
    if isinstance(raw_result, str):
        try:
            result_data = json.loads(raw_result)
        except json.JSONDecodeError:
            result_data = {"text_result": raw_result}
    elif isinstance(raw_result, dict):
        result_data = raw_result
    else:
        result_data = {"text_result": str(raw_result)}

    return {
        "birth_time": result_data.get("birth_time", ""),
        "four_pillars": result_data.get("four_pillars", {}),
        "five_elements": result_data.get("five_elements", {}),
        "ten_gods": result_data.get("ten_gods", {}),
        "lunar_info": result_data.get("lunar_info", {}),
        "solar_terms": result_data.get("solar_terms", {}),
        "text_result": result_data.get("text_result", json.dumps(result_data, ensure_ascii=False)),
        "raw_data": result_data,
        "parsed_time": datetime.now().isoformat(),
    }


def calculate_bazi_local(arguments: Dict[str, Any], timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
    script_path = Path(__file__).with_name("bazi_local_node.mjs")
    if not script_path.exists():
        raise LocalBaziError(f"Local bazi node script not found: {script_path}")

    timeout = timeout_seconds or float(os.getenv("BAZI_LOCAL_TIMEOUT_SECONDS", "8"))
    command = [os.getenv("NODE_BINARY", "node"), str(script_path)]
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(arguments, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalBaziError(f"Local bazi calculation timed out after {timeout:.1f}s") from exc
    except OSError as exc:
        raise LocalBaziError(f"Unable to start local bazi calculator: {exc}") from exc

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if completed.returncode != 0:
        detail = stderr or stdout or f"exit code {completed.returncode}"
        try:
            error_payload = json.loads(detail)
            detail = error_payload.get("error") or detail
        except Exception:
            pass
        raise LocalBaziError(f"Local bazi calculation failed: {detail}")

    if not stdout:
        raise LocalBaziError("Local bazi calculation returned no output")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise LocalBaziError(f"Local bazi calculation returned invalid JSON: {stdout[:300]}") from exc

    if not payload.get("success"):
        raise LocalBaziError(payload.get("error") or "Local bazi calculation failed")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise LocalBaziError("Local bazi calculation returned invalid data")

    return _parse_bazi_result(data)
