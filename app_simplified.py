#!/usr/bin/env python3
"""
鍏瓧鍛界悊鍒嗘瀽绯荤粺 - 绠€鍖栫増鏈?
鏈湴璁板繂涓庢枃浠跺瓨鍌ㄧ増鏈?
鏀寔涓夌増鏈垎鏋愭ā寮忥細缁忓吀鐗堛€佹櫤鎱х増銆佸ぇ甯堢増
"""

from flask import Flask, request, jsonify, render_template_string, send_from_directory, session, redirect, url_for, make_response
from flask_cors import CORS
import sys
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import uuid
import os
import json
import logging
import hashlib
import secrets
import uuid
import time
from datetime import datetime, timedelta
from urllib.parse import quote
import portalocker
from bazi_client import BaziClient
from local_bazi_calculator import LocalBaziError, calculate_bazi_local
from pdf_report import build_pdf_report, make_pdf_filename
from ziwei_client import ZiweiClient
from solar_time import calculate_true_solar_time
try:
    from china_locations import get_coordinates as get_offline_coordinates
except ImportError:
    def get_offline_coordinates(*args, **kwargs):
        return None
# 寮曞叆鍐滃巻杞崲搴擄紙濡傛灉娌℃湁瀹夎锛岄渶娣诲姞锛?
try:
    from lunardate import LunarDate
except ImportError:
    LunarDate = None

import asyncio
from typing import Dict, List, Optional, Any
import requests

# 杈呭姪鍑芥暟锛氭瀯寤轰綅缃煡璇㈠瓧绗︿覆
def _build_location_query(location: Dict[str, Any]) -> str:
    parts = []
    # 浼樺厛椤哄簭锛氳缁嗗湴鍧€ > 鍖哄幙 > 鍩庡競 > 鐪佷唤
    # 浼樺寲绛栫暐锛?
    # 1. 閬垮厤鍦板潃瀛楁鍖呭惈鍐椾綑鐨勭渷甯傚尯淇℃伅
    # 2. 濡傛灉鏈夎缁嗗湴鍧€锛屽皾璇曟彁鍙栧叧閿儴鍒嗘垨鐩存帴浣跨敤缁勫悎鏌ヨ
    
    address = (location.get("address") or "").strip()
    district = (location.get("district") or "").strip()
    city = (location.get("city") or "").strip()
    province = (location.get("province") or "").strip()
    
    # 濡傛灉鍦板潃宸茬粡闈炲父璇︾粏锛堝寘鍚渷甯傦級锛屽垯浼樺厛浣跨敤鍦板潃
    if address and (province in address or city in address):
        query = address
    else:
        # 鍚﹀垯鎸夊眰绾ф瀯寤?
        components = []
        if province: components.append(province)
        if city and city != province: components.append(city)
        if district and district != city: components.append(district)
        if address: components.append(address)
        query = " ".join(components)
        
    if not query:
        return ""
        
    # Nominatim 瀵圭粨鏋勫寲鏌ヨ鏀寔鏇村ソ锛屼絾杩欓噷鎴戜滑鏋勫缓涓€涓€氱敤鐨勬悳绱㈠瓧绗︿覆
    # 绉婚櫎鍙兘瀵艰嚧娣锋穯鐨勯噸澶嶈瘝
    # 纭繚 "涓浗" 鍦ㄦ渶鍚?
    if "涓浗" not in query and "China" not in query:
        query = f"{query} 涓浗"
        
    return query

# 杈呭姪鍑芥暟锛氬湪绾垮湴鐞嗙紪鐮?
def _geocode_location(query: str) -> Optional[Dict[str, Any]]:
    if not query:
        return None
    
    # 浣跨敤澶氫釜婧愭垨閲嶈瘯鏈哄埗
    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        "User-Agent": "bazi-mcp-client/1.0",
        "Referer": "https://github.com/your-repo/bazi-mcp" # 绀艰矊鎬eader
    }
    
    # 灏濊瘯绠€鍖栨煡璇㈠鏋滅涓€娆″け璐?
    queries_to_try = [query]
    
    # 濡傛灉鏌ヨ寰堥暱锛屽皾璇曠Щ闄ゆ渶鍚庝竴閮ㄥ垎锛堥€氬父鏄缁嗗湴鍧€锛?
    parts = query.split()
    if len(parts) > 3:
        queries_to_try.append(" ".join(parts[:-2] + [parts[-1]])) # 淇濈暀鏈€鍚庨儴鍒嗙殑"涓浗"
        
    for q in queries_to_try:
        params = {
            "q": q,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": "cn",  # 闄愬埗鍦ㄤ腑鍥?
        }
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    item = data[0] if isinstance(data, list) else data
                    try:
                        lat = float(item.get("lat"))
                        lon = float(item.get("lon"))
                        return {"latitude": lat, "longitude": lon}
                    except (ValueError, TypeError):
                        continue
        except Exception:
            continue
            
    # 濡傛灉鎵€鏈夊皾璇曢兘澶辫触锛岃繑鍥為粯璁ゅ潗鏍囷紙鍙€夛紝鎴栬€呰繑鍥濶one鐢变笂灞傚鐞嗭級
    # 鍖椾含鍧愭爣浣滀负鍏滃簳锛熸垨鑰呰繑鍥濶one
    return None

from dataclasses import asdict
from functools import wraps

import liuyao_logic
import qimen_logic

# 瀵煎叆鏍稿績妯″潡
from ai_analyzer import AIAnalyzer, AnalysisResult
from prompt_templates import PromptBuilder, AnalysisStyle
from auth_manager import AuthManager
from user_manager import UserManager
from feature_flags import ASYNC_ORGANIZER_ENABLED, MCP_ZIWEI_ENABLED
from memory_manager import BaziMemoryManager
from memory_organizer import start_memory_organizer

# 鍔犺浇鐜鍙橀噺
from dotenv import load_dotenv
LOCAL_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(LOCAL_ENV_PATH, override=False)

def reload_local_env() -> None:
    load_dotenv(LOCAL_ENV_PATH, override=True)

def get_deepseek_dialog_model() -> str:
    return os.getenv("DEEPSEEK_DIALOG_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-pro"

def get_optional_timeout(env_name: str) -> Optional[float]:
    raw = os.getenv(env_name)
    if raw in (None, ""):
        return None
    value = float(raw)
    return value if value > 0 else None

def get_optional_int(env_name: str) -> Optional[int]:
    raw = os.getenv(env_name)
    if raw in (None, ""):
        return None
    value = int(raw)
    return value if value > 0 else None

def get_deepseek_analysis_options() -> Dict[str, Any]:
    reload_local_env()
    model = (
        os.getenv("DEEPSEEK_ANALYSIS_MODEL")
        or os.getenv("DEEPSEEK_FAST_MODEL")
        or os.getenv("DEEPSEEK_DIALOG_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or "deepseek-v4-flash"
    )
    return {
        "model": model,
        "max_tokens": get_optional_int("DEEPSEEK_ANALYSIS_MAX_TOKENS"),
        "temperature": float(os.getenv("DEEPSEEK_ANALYSIS_TEMPERATURE") or 0.35),
        "timeout": get_optional_timeout("DEEPSEEK_ANALYSIS_TIMEOUT"),
    }

def get_deepseek_followup_options() -> Dict[str, Any]:
    analysis_options = get_deepseek_analysis_options()
    return {
        "model": os.getenv("DEEPSEEK_FOLLOWUP_MODEL") or analysis_options["model"],
        "max_tokens": get_optional_int("DEEPSEEK_FOLLOWUP_MAX_TOKENS"),
        "temperature": float(os.getenv("DEEPSEEK_FOLLOWUP_TEMPERATURE") or analysis_options["temperature"]),
        "timeout": get_optional_timeout("DEEPSEEK_FOLLOWUP_TIMEOUT"),
    }

def get_deepseek_interpretation_options(version: str) -> Dict[str, Any]:
    model = (
        os.getenv("DEEPSEEK_INTERPRETATION_MODEL")
        or os.getenv("DEEPSEEK_FAST_MODEL")
        or "deepseek-v4-flash"
    )
    version = (version or "wisdom").strip().lower()
    default_temperature = 0.45 if version == "wisdom" else 0.3
    return {
        "model": model,
        "max_tokens": get_optional_int("DEEPSEEK_INTERPRETATION_MAX_TOKENS"),
        "temperature": float(os.getenv("DEEPSEEK_INTERPRETATION_TEMPERATURE") or default_temperature),
        "timeout": get_optional_timeout("DEEPSEEK_INTERPRETATION_TIMEOUT"),
    }

def get_gemini_master_options() -> Dict[str, Any]:
    reload_local_env()
    return {
        "model": os.getenv("GEMINI_MASTER_MODEL") or "gemini-3.1-pro",
        "max_tokens": get_optional_int("GEMINI_MASTER_MAX_TOKENS"),
        "temperature": float(os.getenv("GEMINI_MASTER_TEMPERATURE") or 0.35),
        "timeout": get_optional_timeout("GEMINI_MASTER_TIMEOUT"),
    }

def ensure_gemini_client_ready() -> bool:
    reload_local_env()
    if ai_analyzer.gemini_model or ai_analyzer.gemini_openai_client:
        return True
    try:
        ai_analyzer._init_clients()
    except Exception as e:
        logger.warning("Gemini瀹㈡埛绔噸寤哄け璐? %s", e)
    return bool(ai_analyzer.gemini_model or ai_analyzer.gemini_openai_client)

# 閰嶇疆鏃ュ織
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or secrets.token_hex(32)

# 鍏ㄥ眬鍙橀噺
bazi_client = None
user_sessions = {}

# 鏍稿績缁勪欢鍒濆鍖?
ai_analyzer = AIAnalyzer()
prompt_builder = PromptBuilder()
user_manager = UserManager()
auth_manager = AuthManager()
bazi_memory_manager = BaziMemoryManager()
memory_organizer = start_memory_organizer(bazi_memory_manager) if ASYNC_ORGANIZER_ENABLED else None

# 鏈湴瀛樺偍鐩綍
DATA_DIR = "local_data"
BAZI_DATA_DIR = os.path.join(DATA_DIR, "bazi_data")
ANALYSIS_DATA_DIR = os.path.join(DATA_DIR, "analysis_data")
SESSION_DATA_DIR = os.path.join(DATA_DIR, "sessions")
ZIWEI_CHAT_DIR = os.path.join(DATA_DIR, "ziwei_chat")
LIUYAO_CHAT_DIR = os.path.join(DATA_DIR, "liuyao_chat")
QIMEN_CHAT_DIR = os.path.join(DATA_DIR, "qimen_chat")

# 鍒涘缓瀛樺偍鐩綍
for dir_path in [DATA_DIR, BAZI_DATA_DIR, ANALYSIS_DATA_DIR, SESSION_DATA_DIR, ZIWEI_CHAT_DIR, LIUYAO_CHAT_DIR, QIMEN_CHAT_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# 鏈湴鏁版嵁瀛樺偍鍑芥暟
def _json_lock_path(file_path: str) -> str:
    return f"{file_path}.lock"

def _load_from_local_file_unlocked(file_path: str) -> dict:
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def _save_to_local_file_unlocked(file_path: str, data: dict):
    directory = os.path.dirname(file_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = f"{file_path}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, file_path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

def save_to_local_file(file_path: str, data: dict):
    """淇濆瓨鏁版嵁鍒版湰鍦版枃浠讹紙跨线程/进程锁 + 原子替换）"""
    try:
        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with portalocker.Lock(_json_lock_path(file_path), timeout=30):
            _save_to_local_file_unlocked(file_path, data)
        return True
    except Exception as e:
        logger.error(f"淇濆瓨鏂囦欢澶辫触 {file_path}: {e}")
        return False

def load_from_local_file(file_path: str) -> dict:
    """浠庢湰鍦版枃浠跺姞杞芥暟鎹紙与写入共享同一文件锁）"""
    try:
        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with portalocker.Lock(_json_lock_path(file_path), timeout=30):
            return _load_from_local_file_unlocked(file_path)
    except Exception as e:
        logger.error(f"鍔犺浇鏂囦欢澶辫触 {file_path}: {e}")
        return {}

def update_local_json_file(file_path: str, updater, default_factory=dict):
    """在同一把文件锁内完成读-改-写，避免并发追加互相覆盖。"""
    try:
        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with portalocker.Lock(_json_lock_path(file_path), timeout=30):
            try:
                current = _load_from_local_file_unlocked(file_path)
            except Exception:
                logger.warning(f"读取JSON失败，将使用默认结构重建: {file_path}", exc_info=True)
                current = {}
            if not current and default_factory:
                current = default_factory()
            updated = updater(current)
            _save_to_local_file_unlocked(file_path, updated)
            return updated
    except Exception as e:
        logger.error(f"更新JSON文件失败 {file_path}: {e}", exc_info=True)
        return None

def append_analysis_records(file_path: str, records: List[Dict[str, Any]]):
    records = [record for record in records if isinstance(record, dict)]
    if not records:
        return None

    def updater(existing: Dict[str, Any]):
        if not isinstance(existing, dict):
            existing = {}
        if not isinstance(existing.get("analyses"), list):
            existing["analyses"] = []
        existing["analyses"].extend(records)
        return existing

    return update_local_json_file(file_path, updater, default_factory=lambda: {"analyses": []})

def upsert_followup_record(
    file_path: str,
    followup_data: Dict[str, Any],
    dimension: str,
    reanalyze_followup_id: str,
):
    state = {"updated_existing": False}

    def updater(existing: Dict[str, Any]):
        if not isinstance(existing, dict):
            existing = {}
        if not isinstance(existing.get("analyses"), list):
            existing["analyses"] = []

        if reanalyze_followup_id:
            for index, item in enumerate(existing["analyses"]):
                if (
                    isinstance(item, dict)
                    and item.get("analysis_id") == reanalyze_followup_id
                    and item.get("dimension") == dimension
                ):
                    updated_record = dict(followup_data)
                    previous_timestamps = item.get("reanalyze_history") if isinstance(item.get("reanalyze_history"), list) else []
                    previous_timestamps.append(item.get("timestamp"))
                    updated_record["created_at"] = item.get("created_at") or item.get("timestamp")
                    updated_record["reanalyze_history"] = [ts for ts in previous_timestamps if ts]
                    existing["analyses"][index] = updated_record
                    state["updated_existing"] = True
                    return existing

        new_record = dict(followup_data)
        new_record.pop("reanalyzed_at", None)
        existing["analyses"].append(new_record)
        return existing

    updated = update_local_json_file(file_path, updater, default_factory=lambda: {"analyses": []})
    return updated is not None, state["updated_existing"]

def _normalize_gender_value(gender: Any) -> Optional[int]:
    try:
        if gender is None:
            return None
        if isinstance(gender, bool):
            return 1 if gender else 0
        g = int(str(gender).strip())
        if g in (0, 1):
            return g
        return None
    except Exception:
        return None

def _normalize_boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")

def _extract_birth_date_from_iso(birth_time: Optional[str]) -> Optional[str]:
    if not birth_time:
        return None
    s = str(birth_time).strip()
    if "T" in s and len(s) >= 10:
        return s[:10]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None

def resolve_or_create_user_id_by_chart(
    name: str,
    gender: Any,
    birth_time_iso: Optional[str],
    calendar_type: Optional[str] = None,
    birth_date: Optional[str] = None,
    lunar_is_leap_month: Any = None,
) -> str:
    n = (name or "").strip() or "鍖垮悕鐢ㄦ埛"
    g = _normalize_gender_value(gender)
    g_str = str(g) if g is not None else ""
    cal = (calendar_type or "solar").strip() or "solar"
    lunar_leap = cal == "lunar" and _normalize_boolish(lunar_is_leap_month)

    bd = (birth_date or "").strip() or (_extract_birth_date_from_iso(birth_time_iso) or "")
    bt = (birth_time_iso or "").strip()

    legacy_identifier = f"{n}_{bd}_{g_str}" if bd and g_str else ""
    v2_identifier = f"{n}_{bt}_{g_str}_{cal}{'_leap' if lunar_leap else ''}" if bt and g_str else legacy_identifier or f"{n}_{g_str}"

    if legacy_identifier and not lunar_leap:
        legacy_user_id = user_manager.generate_user_id(legacy_identifier)
        if user_manager.get_user(legacy_user_id):
            try:
                user_manager.update_user(legacy_user_id, username=n)
            except Exception:
                pass
            return legacy_user_id

    user = user_manager.create_user(
        identifier=v2_identifier,
        username=n,
        metadata={
            "gender": g,
            "birth_date": bd,
            "birth_time": bt,
            "calendar_type": cal,
            "lunar_is_leap_month": lunar_leap,
            "identifier_v2": v2_identifier,
            "identifier_legacy": legacy_identifier,
        },
    )
    return user.user_id

def get_user_bazi_file(user_id: str) -> str:
    """鑾峰彇鐢ㄦ埛鍏瓧鏁版嵁鏂囦欢璺緞"""
    return os.path.join(BAZI_DATA_DIR, f"{user_id}_bazi.json")

def load_user_bazi_info(user_id: str):
    try:
        bazi_file = get_user_bazi_file(user_id)
        if not os.path.exists(bazi_file):
            return None
        with open(bazi_file, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        bazi_info = data.get("bazi_info")
        return bazi_info if isinstance(bazi_info, dict) and bazi_info else None
    except Exception:
        return None

def get_user_analysis_file(user_id: str) -> str:
    """鑾峰彇鐢ㄦ埛鍒嗘瀽鏁版嵁鏂囦欢璺緞"""
    return os.path.join(ANALYSIS_DATA_DIR, f"{user_id}_analysis.json")

def get_session_file(session_id: str) -> str:
    """鑾峰彇浼氳瘽鏁版嵁鏂囦欢璺緞"""
    return os.path.join(SESSION_DATA_DIR, f"{session_id}_session.json")

def get_user_ziwei_chat_file(user_id: str) -> str:
    return os.path.join(ZIWEI_CHAT_DIR, f"{user_id}_ziwei_chat.json")

def get_user_liuyao_chat_file(user_id: str) -> str:
    return os.path.join(LIUYAO_CHAT_DIR, f"{user_id}_liuyao_chat.json")

def get_user_qimen_chat_file(user_id: str) -> str:
    return os.path.join(QIMEN_CHAT_DIR, f"{user_id}_qimen_chat.json")

def _safe_iso_now() -> str:
    return datetime.now().isoformat()

def _normalize_text_value(value: Any) -> str:
    return str(value or "").strip().lower()

def _short_time(value: Any) -> str:
    s = str(value or "").strip()
    if "T" in s:
        tail = s.split("T", 1)[1]
        if len(tail) >= 5:
            return tail[:5]
    if len(s) >= 5 and s[2] == ":":
        return s[:5]
    return s

def _pillar_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    direct = str(value.get("干支") or value.get("ganzhi") or "").strip()
    if direct:
        return direct
    stem = value.get("天干")
    branch = value.get("地支")
    if isinstance(stem, dict):
        stem = stem.get("天干") or stem.get("name") or stem.get("value")
    if isinstance(branch, dict):
        branch = branch.get("地支") or branch.get("name") or branch.get("value")
    stem = str(stem or "").strip()
    branch = str(branch or "").strip()
    return f"{stem}{branch}" if stem and branch else ""

def _four_pillars_from_mapping(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    pillars = []
    for key in ("年柱", "月柱", "日柱", "时柱"):
        pillar = _pillar_text(value.get(key))
        if pillar:
            pillars.append(pillar)
    return " ".join(pillars) if len(pillars) == 4 else ""

def _extract_four_pillars(bazi_info: Dict[str, Any]) -> Optional[str]:
    if not isinstance(bazi_info, dict):
        return None
    for key in ("four_pillars", "baziFourPillars", "fourPillars", "pillars"):
        value = bazi_info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        mapped = _four_pillars_from_mapping(value)
        if mapped:
            return mapped

    raw_data = bazi_info.get("raw_data") if isinstance(bazi_info.get("raw_data"), dict) else {}
    for key in ("八字", "bazi", "bazi_text", "four_pillars", "baziFourPillars", "fourPillars", "鍏瓧"):
        value = raw_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    mapped = _four_pillars_from_mapping(raw_data)
    if mapped:
        return mapped

    text_result = bazi_info.get("text_result")
    if isinstance(text_result, str) and text_result.strip():
        try:
            parsed = json.loads(text_result)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            for key in ("八字", "bazi", "bazi_text", "four_pillars", "baziFourPillars", "fourPillars"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            mapped = _four_pillars_from_mapping(parsed)
            if mapped:
                return mapped
    return None

def _user_profile_to_dict(user_id: str) -> Dict[str, Any]:
    user = user_manager.get_user(user_id)
    if not user:
        return {"user_id": user_id}
    data = asdict(user)
    status = data.get("status")
    data["status"] = status.value if hasattr(status, "value") else str(status)
    return data

def _load_bazi_payload(user_id: str) -> Dict[str, Any]:
    data = load_from_local_file(get_user_bazi_file(user_id))
    return data if isinstance(data, dict) else {}

def _chart_signature_from_bazi_info(
    bazi_info: Optional[Dict[str, Any]],
    user_info: Optional[Dict[str, Any]] = None,
) -> str:
    if not isinstance(bazi_info, dict):
        return ""
    raw = bazi_info.get("raw_data") if isinstance(bazi_info.get("raw_data"), dict) else {}
    dayun = raw.get("大运") if isinstance(raw.get("大运"), dict) else {}
    dayun_rows = []
    rows = dayun.get("大运") if isinstance(dayun, dict) else []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            dayun_rows.append(
                {
                    "干支": row.get("干支"),
                    "开始年份": row.get("开始年份"),
                    "结束": row.get("结束"),
                    "开始年龄": row.get("开始年龄"),
                    "结束年龄": row.get("结束年龄"),
                }
            )

    ui = user_info if isinstance(user_info, dict) else {}
    payload = {
        "birth_time": raw.get("阳历") or ui.get("birth_time"),
        "gender": raw.get("性别") or _normalize_gender_value(ui.get("gender")),
        "calendar_type": ui.get("calendar_type") if not raw else None,
        "八字": raw.get("八字"),
        "阳历": raw.get("阳历"),
        "农历": raw.get("农历"),
        "起运日期": dayun.get("起运日期") if isinstance(dayun, dict) else None,
        "起运年龄": dayun.get("起运年龄") if isinstance(dayun, dict) else None,
        "大运": dayun_rows,
    }
    if not any(v not in (None, "", [], {}) for v in payload.values()):
        return ""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]

def _chart_signature_from_bazi_payload(payload: Optional[Dict[str, Any]]) -> str:
    if not isinstance(payload, dict):
        return ""
    return _chart_signature_from_bazi_info(
        payload.get("bazi_info") if isinstance(payload.get("bazi_info"), dict) else {},
        payload.get("user_info") if isinstance(payload.get("user_info"), dict) else {},
    )

def _analysis_chart_signature(entry: Dict[str, Any]) -> str:
    if not isinstance(entry, dict):
        return ""
    explicit = str(entry.get("chart_signature") or "").strip()
    if explicit:
        return explicit
    return _chart_signature_from_bazi_info(
        entry.get("bazi_info") if isinstance(entry.get("bazi_info"), dict) else {},
        entry.get("user_background") if isinstance(entry.get("user_background"), dict) else {},
    )

def _filter_analysis_doc_for_chart(user_id: str, analysis_doc: Dict[str, Any]) -> Dict[str, Any]:
    current_signature = _chart_signature_from_bazi_payload(_load_bazi_payload(user_id))
    analyses = analysis_doc.get("analyses") if isinstance(analysis_doc, dict) else []
    if not current_signature or not isinstance(analyses, list):
        return analysis_doc if isinstance(analysis_doc, dict) else {"analyses": []}

    kept = []
    stale = []
    for entry in analyses:
        if not isinstance(entry, dict):
            continue
        sig = _analysis_chart_signature(entry)
        if sig == current_signature:
            if not entry.get("chart_signature"):
                entry["chart_signature"] = sig
            kept.append(entry)
        else:
            stale.append(entry)

    if not stale:
        return analysis_doc

    updated = dict(analysis_doc)
    updated["analyses"] = kept
    invalidations = list(updated.get("invalidations") or [])
    invalidations.append(
        {
            "reason": "chart_signature_mismatch",
            "current_chart_signature": current_signature,
            "stale_count": len(stale),
            "at": datetime.now().isoformat(),
        }
    )
    updated["invalidations"] = invalidations[-10:]
    return updated

def _archive_json_payload(path: str, payload: Dict[str, Any], suffix: str) -> Optional[str]:
    try:
        if not isinstance(payload, dict):
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = f"{path}.{suffix}.{stamp}.bak"
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return archive_path
    except Exception:
        return None

def _invalidate_analysis_file_for_chart_change(user_id: str, old_signature: str, new_signature: str, reason: str) -> Dict[str, Any]:
    path = get_user_analysis_file(user_id)
    existing = load_from_local_file(path)
    analyses = existing.get("analyses") if isinstance(existing, dict) else []
    count = len(analyses) if isinstance(analyses, list) else 0
    archive_path = _archive_json_payload(path, existing, "chart_invalidated") if count else None
    replacement = {
        "analyses": [],
        "invalidations": [
            {
                "reason": reason,
                "old_chart_signature": old_signature,
                "new_chart_signature": new_signature,
                "stale_count": count,
                "archive": archive_path,
                "at": datetime.now().isoformat(),
            }
        ],
    }
    save_to_local_file(path, replacement)
    return {"stale_analysis_count": count, "analysis_archive": archive_path}

def _handle_chart_change_if_needed(user_id: str, new_payload: Dict[str, Any], reason: str) -> Dict[str, Any]:
    old_payload = _load_bazi_payload(user_id)
    old_signature = _chart_signature_from_bazi_payload(old_payload)
    new_signature = _chart_signature_from_bazi_payload(new_payload)
    if not new_signature:
        return {"changed": False, "old_signature": old_signature, "new_signature": new_signature}
    new_payload["chart_signature"] = new_signature
    if isinstance(new_payload.get("user_info"), dict):
        new_payload["user_info"]["chart_signature"] = new_signature

    if old_signature and old_signature != new_signature:
        analysis_result = _invalidate_analysis_file_for_chart_change(user_id, old_signature, new_signature, reason)
        memory_result = bazi_memory_manager.invalidate_chart_dependent_memory(
            user_id=user_id,
            reason=reason,
            old_chart_signature=old_signature,
            new_chart_signature=new_signature,
        )
        return {
            "changed": True,
            "old_signature": old_signature,
            "new_signature": new_signature,
            **analysis_result,
            "memory": memory_result,
        }
    return {"changed": False, "old_signature": old_signature, "new_signature": new_signature}

def _sync_user_birth_metadata(user_id: str, user_info: Dict[str, Any]) -> None:
    if not user_id or not isinstance(user_info, dict):
        return
    try:
        user = user_manager.get_user(user_id)
        metadata = dict(user.metadata) if user and isinstance(user.metadata, dict) else {}
        name = user_info.get("name") or (user.username if user else user_id)
        birth_date = user_info.get("birth_date") or _extract_birth_date_from_iso(user_info.get("birth_time"))
        gender = user_info.get("gender")
        calendar_type = user_info.get("calendar_type") or metadata.get("calendar_type") or "solar"
        lunar_is_leap_month = _normalize_boolish(user_info.get("lunar_is_leap_month"))
        birth_time = user_info.get("birth_time")
        metadata.update(
            {
                "gender": gender,
                "birth_date": birth_date,
                "birth_time": birth_time,
                "calendar_type": calendar_type,
                "lunar_is_leap_month": lunar_is_leap_month,
                "chart_signature": user_info.get("chart_signature"),
                "identifier_v2": f"{name}_{birth_time}_{gender}_{calendar_type}{'_leap' if calendar_type == 'lunar' and lunar_is_leap_month else ''}" if name and birth_time and gender is not None else metadata.get("identifier_v2"),
                "identifier_legacy": f"{name}_{birth_date}_{gender}" if name and birth_date and gender is not None else metadata.get("identifier_legacy"),
                "profile_source": user_info.get("updated_from") or "bazi_get",
            }
        )
        user_manager.update_user(user_id, username=name, metadata=metadata)
    except Exception:
        pass

def _sync_profile_doc_to_chart(user_id: str, user_info: Dict[str, Any], reset_tags: bool = False) -> None:
    if not user_id or not isinstance(user_info, dict):
        return
    try:
        profile_doc = bazi_memory_manager.get_profile_doc(user_id)
        profile_doc["background"] = {
            "name": user_info.get("name"),
            "gender": user_info.get("gender"),
            "birth_date": user_info.get("birth_date") or _extract_birth_date_from_iso(user_info.get("birth_time")),
            "birth_time": user_info.get("birth_time"),
            "calendar_type": user_info.get("calendar_type"),
            "lunar_is_leap_month": _normalize_boolish(user_info.get("lunar_is_leap_month")),
            "user_id": user_id,
            "chart_signature": user_info.get("chart_signature"),
        }
        if reset_tags:
            profile_doc["tags"] = []
        profile_doc["updated_at"] = datetime.now().isoformat()
        bazi_memory_manager.save_profile_doc(user_id, profile_doc)
    except Exception:
        pass

def _profile_complete(user_id: Optional[str]) -> bool:
    if not user_id:
        return False
    if os.path.exists(get_user_bazi_file(user_id)):
        return True
    user = user_manager.get_user(user_id)
    metadata = user.metadata if user and isinstance(user.metadata, dict) else {}
    registration_profile = metadata.get("registration_birth_profile") if isinstance(metadata.get("registration_birth_profile"), dict) else {}
    return bool(
        metadata.get("birth_date")
        or metadata.get("birth_time")
        or registration_profile.get("birth_date")
        or registration_profile.get("birth_time")
    )

def _account_birth_profile(account: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    metadata = account.get("metadata") if account and isinstance(account.get("metadata"), dict) else {}
    profile = metadata.get("registration_birth_profile") if isinstance(metadata.get("registration_birth_profile"), dict) else {}
    return profile

def _account_profile_complete(account: Optional[Dict[str, Any]]) -> bool:
    profile = _account_birth_profile(account)
    return bool(profile.get("birth_date") or profile.get("birth_time"))

def _analysis_summary(user_id: str, limit: int = 5) -> Dict[str, Any]:
    data = load_from_local_file(get_user_analysis_file(user_id))
    analyses = data.get("analyses") if isinstance(data, dict) else []
    if not isinstance(analyses, list):
        analyses = []
    items = []
    for item in analyses[-limit:][::-1]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        items.append({
            "analysis_id": item.get("analysis_id"),
            "version": item.get("version"),
            "dimension": item.get("dimension"),
            "question": item.get("question"),
            "timestamp": item.get("timestamp"),
            "preview": content[:160],
        })
    return {"total_count": len(analyses), "recent": items}

def _chat_summary_for_file(path: str, kind: str) -> Dict[str, Any]:
    data = load_from_local_file(path)
    if kind == "ziwei":
        messages = data.get("messages") if isinstance(data, dict) else []
        updated_at = data.get("updated_at") if isinstance(data, dict) else None
    else:
        messages = data if isinstance(data, list) else []
        updated_at = None
    if not isinstance(messages, list):
        messages = []
    last = messages[-1] if messages and isinstance(messages[-1], dict) else {}
    return {
        "exists": os.path.exists(path),
        "message_count": len(messages),
        "updated_at": updated_at or last.get("timestamp"),
        "last_role": last.get("role"),
        "last_preview": str(last.get("content") or "")[:120],
    }

def _chat_summaries(user_id: str) -> Dict[str, Any]:
    return {
        "ziwei": _chat_summary_for_file(get_user_ziwei_chat_file(user_id), "ziwei"),
        "liuyao": _chat_summary_for_file(get_user_liuyao_chat_file(user_id), "liuyao"),
        "qimen": _chat_summary_for_file(get_user_qimen_chat_file(user_id), "qimen"),
    }

def _bazi_summary(user_id: str) -> Dict[str, Any]:
    payload = _load_bazi_payload(user_id)
    user = user_manager.get_user(user_id)
    metadata = user.metadata if user and isinstance(user.metadata, dict) else {}
    registration_profile = metadata.get("registration_birth_profile") if isinstance(metadata.get("registration_birth_profile"), dict) else {}
    profile_info = {
        "name": metadata.get("name") or registration_profile.get("name") or (user.username if user else None),
        "gender": metadata.get("gender", registration_profile.get("gender")),
        "birth_date": metadata.get("birth_date") or registration_profile.get("birth_date"),
        "birth_time": metadata.get("birth_time") or registration_profile.get("birth_time"),
        "calendar_type": metadata.get("calendar_type") or registration_profile.get("calendar_type"),
        "lunar_is_leap_month": _normalize_boolish(
            metadata.get("lunar_is_leap_month")
            if "lunar_is_leap_month" in metadata
            else registration_profile.get("lunar_is_leap_month")
        ),
        "chart_signature": metadata.get("chart_signature"),
    }
    profile_info = {key: value for key, value in profile_info.items() if value not in (None, "")}
    payload_user_info = payload.get("user_info") if isinstance(payload.get("user_info"), dict) else {}
    user_info = {**profile_info, **payload_user_info}
    bazi_info = payload.get("bazi_info") if isinstance(payload.get("bazi_info"), dict) else {}
    pillars = _extract_four_pillars(bazi_info)
    has_birth_profile = bool(user_info.get("birth_date") or user_info.get("birth_time"))
    return {
        "exists": bool(payload) or has_birth_profile,
        "has_chart": bool(payload),
        "source": "bazi_file" if payload else ("profile_metadata" if has_birth_profile else None),
        "user_info": user_info,
        "timestamp": payload.get("timestamp") or metadata.get("updated_at") or (user.last_active if user else None),
        "four_pillars": pillars,
        "bazi_keys": list(bazi_info.keys()) if isinstance(bazi_info, dict) else [],
    }

def _bazi_summary_from_account(account: Dict[str, Any]) -> Dict[str, Any]:
    birth_profile = _account_birth_profile(account)
    user_info = {
        "name": birth_profile.get("name") or birth_profile.get("display_name") or account.get("display_name"),
        "gender": birth_profile.get("gender"),
        "birth_date": birth_profile.get("birth_date"),
        "birth_time": birth_profile.get("birth_time"),
        "calendar_type": birth_profile.get("calendar_type"),
        "lunar_is_leap_month": _normalize_boolish(birth_profile.get("lunar_is_leap_month")),
        "location": birth_profile.get("location"),
    }
    user_info = {key: value for key, value in user_info.items() if value not in (None, "", {})}
    metadata = account.get("metadata") if isinstance(account.get("metadata"), dict) else {}
    return {
        "exists": bool(user_info.get("birth_date") or user_info.get("birth_time")),
        "has_chart": False,
        "source": "account_metadata" if user_info else None,
        "user_info": user_info,
        "timestamp": metadata.get("bound_at") or metadata.get("conflict_updated_at") or account.get("updated_at") or account.get("created_at"),
        "four_pillars": None,
        "bazi_keys": [],
    }

def _home_payload_for_user(user_id: Optional[str]) -> Dict[str, Any]:
    if not user_id:
        return {
            "needs_profile": True,
            "profile_complete": False,
            "user_id": None,
            "profile": None,
            "bazi": None,
            "analysis": {"total_count": 0, "recent": []},
            "chats": {},
        }
    return {
        "needs_profile": not _profile_complete(user_id),
        "profile_complete": _profile_complete(user_id),
        "user_id": user_id,
        "profile": _user_profile_to_dict(user_id),
        "bazi": _bazi_summary(user_id),
        "analysis": _analysis_summary(user_id),
        "chats": _chat_summaries(user_id),
    }

def _public_account(account: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return auth_manager.public_account(account) if account else None

def _get_current_account() -> Optional[Dict[str, Any]]:
    account_id = session.get("account_id")
    return auth_manager.get_account(account_id) if account_id else None

def _apply_account_session(account: Dict[str, Any]) -> None:
    session["account_id"] = account.get("account_id")
    session["auth_role"] = account.get("role") or "user"
    session["login_id"] = account.get("login_id")
    linked_user_id = account.get("linked_user_id")
    if linked_user_id:
        session["user_id"] = linked_user_id
        profile = user_manager.get_user(linked_user_id)
        session["username"] = (
            (profile.username if profile else None)
            or account.get("display_name")
            or account.get("login_id")
        )
        session["login_time"] = session.get("login_time") or _safe_iso_now()
    else:
        session.pop("user_id", None)
        session["username"] = account.get("display_name") or account.get("login_id")

def _bind_current_account_to_user(user_id: str) -> None:
    account_id = session.get("account_id")
    if not account_id or not user_id:
        return
    account = auth_manager.get_account(account_id)
    if not account or account.get("linked_user_id") == user_id:
        return
    if not account.get("linked_user_id"):
        account = auth_manager.bind_user(account_id, user_id)
        if account:
            _apply_account_session(account)

def _candidate_names_from_request(payload: Dict[str, Any]) -> List[str]:
    names = [
        payload.get("display_name"),
        payload.get("name"),
        payload.get("nickname"),
        payload.get("login_id"),
    ]
    seen = set()
    out = []
    for name in names:
        key = _normalize_text_value(name)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out

def _profile_match_source(user_id: str) -> Dict[str, Any]:
    user = user_manager.get_user(user_id)
    metadata = user.metadata if user and isinstance(user.metadata, dict) else {}
    bazi_payload = _load_bazi_payload(user_id)
    bazi_user_info = bazi_payload.get("user_info") if isinstance(bazi_payload.get("user_info"), dict) else {}
    return {
        "user_id": user_id,
        "username": user.username if user else None,
        "name": bazi_user_info.get("name") or (user.username if user else None),
        "gender": metadata.get("gender", bazi_user_info.get("gender")),
        "birth_date": metadata.get("birth_date") or bazi_user_info.get("birth_date") or _extract_birth_date_from_iso(bazi_user_info.get("birth_time")),
        "birth_time": metadata.get("birth_time") or bazi_user_info.get("birth_time"),
        "calendar_type": metadata.get("calendar_type") or bazi_user_info.get("calendar_type"),
        "lunar_is_leap_month": _normalize_boolish(metadata.get("lunar_is_leap_month") or bazi_user_info.get("lunar_is_leap_month")),
        "has_bazi": bool(bazi_payload),
    }

def _find_user_match_candidates(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    names = _candidate_names_from_request(payload)
    birth_date = str(payload.get("birth_date") or "").strip()
    gender = _normalize_gender_value(payload.get("gender"))
    birth_time = _short_time(payload.get("birth_time"))
    calendar_type = str(payload.get("calendar_type") or "").strip()
    lunar_is_leap_month = _normalize_boolish(
        payload.get("lunar_is_leap_month")
        if "lunar_is_leap_month" in payload
        else payload.get("lunarIsLeapMonth")
    )
    provided_fields = {
        "birth_date": birth_date,
        "gender": "" if gender is None else str(gender),
        "birth_time": birth_time,
        "calendar_type": calendar_type,
        "lunar_is_leap_month": "1" if lunar_is_leap_month else "",
    }
    provided_fields = {k: v for k, v in provided_fields.items() if v not in ("", None)}
    candidates = []

    for user_id in user_manager.users.keys():
        source = _profile_match_source(user_id)
        profile_names = {
            _normalize_text_value(source.get("username")),
            _normalize_text_value(source.get("name")),
        }
        if names and not any(name in profile_names for name in names):
            continue

        matched_fields = 0
        contradictions = 0
        if birth_date:
            if birth_date == str(source.get("birth_date") or "").strip() or birth_date == _extract_birth_date_from_iso(source.get("birth_time")):
                matched_fields += 1
            else:
                contradictions += 1
        if gender is not None:
            source_gender = _normalize_gender_value(source.get("gender"))
            if source_gender == gender:
                matched_fields += 1
            elif source_gender is not None:
                contradictions += 1
        if birth_time:
            if birth_time == _short_time(source.get("birth_time")):
                matched_fields += 1
            else:
                source_short = _short_time(source.get("birth_time"))
                if source_short:
                    contradictions += 1
        if calendar_type:
            source_cal = str(source.get("calendar_type") or "").strip()
            if not source_cal or source_cal == calendar_type:
                matched_fields += 1
            else:
                contradictions += 1
        if calendar_type == "lunar" and lunar_is_leap_month:
            if _normalize_boolish(source.get("lunar_is_leap_month")):
                matched_fields += 1
            else:
                contradictions += 1

        if contradictions:
            continue
        high_confidence = bool(names) and matched_fields >= 2
        candidates.append({
            "user_id": user_id,
            "username": source.get("username"),
            "name": source.get("name"),
            "birth_date": source.get("birth_date"),
            "birth_time": source.get("birth_time"),
            "gender": source.get("gender"),
            "calendar_type": source.get("calendar_type"),
            "lunar_is_leap_month": source.get("lunar_is_leap_month"),
            "has_bazi": source.get("has_bazi"),
            "matched_fields": matched_fields,
            "provided_fields": list(provided_fields.keys()),
            "confidence": "high" if high_confidence else "candidate",
        })
    return candidates

def _try_auto_bind_account(account: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    if account.get("linked_user_id"):
        return {"account": account, "candidates": [], "auto_bound": False}
    match_payload = dict(payload or {})
    match_payload.setdefault("login_id", account.get("login_id"))
    match_payload.setdefault("display_name", account.get("display_name"))
    candidates = _find_user_match_candidates(match_payload)
    high = [c for c in candidates if c.get("confidence") == "high"]
    if len(high) == 1:
        account = auth_manager.bind_user(account["account_id"], high[0]["user_id"]) or account
        return {"account": account, "candidates": [], "auto_bound": True}
    if len(candidates) > 1:
        auth_manager.set_conflict_candidates(account["account_id"], candidates)
    else:
        auth_manager.set_conflict_candidates(account["account_id"], [])
    return {"account": auth_manager.get_account(account["account_id"]) or account, "candidates": candidates, "auto_bound": False}

def _registration_birth_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    metadata = {"register_source": "web", "created_from": "api_auth_register"}
    birth_profile: Dict[str, Any] = {}
    for key in ("name", "display_name", "birth_date", "birth_time", "calendar_type", "gender", "lunar_is_leap_month", "location"):
        value = (payload or {}).get(key)
        if value not in (None, ""):
            birth_profile[key] = value
    if birth_profile:
        metadata["registration_birth_profile"] = birth_profile
    return metadata

def _has_complete_birth_profile(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    name = str(payload.get("name") or payload.get("display_name") or payload.get("nickname") or payload.get("login_id") or "").strip()
    birth_date = str(payload.get("birth_date") or "").strip()
    birth_time = str(payload.get("birth_time") or "").strip()
    gender = _normalize_gender_value(payload.get("gender"))
    return bool(name and birth_date and birth_time and gender is not None)

def _ensure_account_bazi_from_birth_profile(account: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    if not account or not _has_complete_birth_profile(payload):
        return {"account": account, "profile_created": False, "bazi_provider": None, "bazi_duration_ms": None}

    profile_payload = dict(payload or {})
    profile_payload["name"] = str(
        profile_payload.get("name")
        or profile_payload.get("display_name")
        or profile_payload.get("nickname")
        or profile_payload.get("login_id")
        or account.get("display_name")
        or account.get("login_id")
        or ""
    ).strip()
    profile_payload["gender"] = _normalize_gender_value(profile_payload.get("gender"))
    profile_payload["calendar_type"] = str(profile_payload.get("calendar_type") or "solar").strip() or "solar"

    request_info = _build_bazi_calculation_args(profile_payload)
    provider_payload = _calculate_bazi_with_provider(request_info["arguments"])
    bazi_result = provider_payload["result"]
    if not isinstance(bazi_result, dict) or not bazi_result:
        raise ValueError("bazi calculation returned empty result")

    user_id = account.get("linked_user_id") or resolve_or_create_user_id_by_chart(
        name=profile_payload["name"],
        gender=request_info["gender"],
        birth_time_iso=request_info["actual_birth_time"],
        calendar_type=request_info["calendar_type"],
        birth_date=request_info["birth_date"],
        lunar_is_leap_month=request_info["lunar_is_leap_month"],
    )

    now = datetime.now().isoformat()
    user_info = {
        "name": profile_payload["name"],
        "gender": request_info["gender"],
        "birth_time": request_info["actual_birth_time"],
        "birth_date": request_info["birth_date"],
        "calendar_type": request_info["calendar_type"],
        "input_type": request_info["input_type"],
        "lunar_is_leap_month": request_info["lunar_is_leap_month"],
        "user_id": user_id,
        "created_at": now,
        "updated_from": "auth_register",
    }
    if isinstance(profile_payload.get("location"), dict):
        user_info["location"] = profile_payload.get("location")

    user_data = {
        "user_info": user_info,
        "bazi_info": bazi_result,
        "bazi_provider": provider_payload["provider"],
        "bazi_duration_ms": provider_payload["duration_ms"],
        "bazi_fallback_reason": provider_payload["fallback_reason"],
        "timestamp": now,
    }
    chart_invalidation = _handle_chart_change_if_needed(
        user_id,
        user_data,
        reason="auth_register_birth_profile_changed",
    )
    user_data["chart_invalidation"] = chart_invalidation

    bazi_file = get_user_bazi_file(user_id)
    if not save_to_local_file(bazi_file, user_data):
        raise RuntimeError("failed to save bazi profile")

    try:
        user = user_manager.get_user(user_id)
        metadata = dict(user.metadata if user and isinstance(user.metadata, dict) else {})
        metadata.update({
            "gender": request_info["gender"],
            "birth_date": request_info["birth_date"],
            "birth_time": request_info["actual_birth_time"],
            "calendar_type": request_info["calendar_type"],
            "chart_signature": user_data.get("chart_signature"),
            "profile_source": "auth_register",
        })
        user_manager.update_user(user_id, username=profile_payload["name"], metadata=metadata)
    except Exception:
        pass
    _sync_profile_doc_to_chart(user_id, user_info, reset_tags=bool(chart_invalidation.get("changed")))

    try:
        bazi_memory_manager.update_chart_facts_from_bazi_payload(
            user_id=user_id,
            user_info=user_info,
            bazi_info=bazi_result,
            raw_file_path=bazi_file,
            parsed_time=bazi_result.get("parsed_time") if isinstance(bazi_result, dict) else None,
        )
    except Exception as e:
        logger.warning(f"[AuthRegister] failed to update chart facts: {e}")

    if not account.get("linked_user_id"):
        account = auth_manager.bind_user(account["account_id"], user_id) or account

    return {
        "account": account,
        "profile_created": True,
        "bazi_provider": provider_payload["provider"],
        "bazi_duration_ms": provider_payload["duration_ms"],
    }

# 绠€鍖栫殑浼氳瘽绠＄悊绫?
class SimpleSession:
    def __init__(self, user_id: str, session_id: str = None):
        self.user_id = user_id
        self.session_id = session_id or str(uuid.uuid4())
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.conversation_history = []
        self.context = {}
        
    def add_message(self, role: str, content: str, analysis_type: str = None):
        """娣诲姞娑堟伅鍒颁細璇濆巻鍙?"""
        message = {
            "role": role,
            "content": content,
            "analysis_type": analysis_type,
            "timestamp": datetime.now().isoformat()
        }
        self.conversation_history.append(message)
        self.last_activity = datetime.now()
        self.save_to_file()
        return message
    
    def save_to_file(self):
        """淇濆瓨浼氳瘽鍒版枃浠?"""
        session_data = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "conversation_history": self.conversation_history,
            "context": self.context
        }
        save_to_local_file(get_session_file(self.session_id), session_data)
    
    @classmethod
    def load_from_file(cls, session_id: str):
        """浠庢枃浠跺姞杞戒細璇?"""
        session_data = load_from_local_file(get_session_file(session_id))
        if session_data:
            session = cls(session_data["user_id"], session_id)
            session.created_at = datetime.fromisoformat(session_data["created_at"])
            session.last_activity = datetime.fromisoformat(session_data["last_activity"])
            session.conversation_history = session_data.get("conversation_history", [])
            session.context = session_data.get("context", {})
            return session
        return None

def get_or_create_session(user_id: str, session_id: str = None) -> SimpleSession:
    """鑾峰彇鎴栧垱寤虹敤鎴蜂細璇?"""
    if session_id:
        session = SimpleSession.load_from_file(session_id)
        if session and session.user_id == user_id:
            return session
    
    # 鍒涘缓鏂颁細璇?
    session = SimpleSession(user_id, session_id)
    session.save_to_file()
    return session

# 瑁呴グ鍣?
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # 寮哄埗瀵规墍鏈?api/璺緞杩斿洖JSON鍝嶅簲
            if request.path.startswith('/api/'):
                logger.warning(f"馃敀 [鐧诲綍妫€鏌 API璇锋眰鏈巿鏉? {request.path}")
                response = jsonify({
                    "error": "鐢ㄦ埛鏈櫥褰曪紝璇峰厛鐧诲綍",
                    "error_type": "unauthorized", 
                    "redirect_url": "/login",
                    "timestamp": datetime.now().isoformat()
                })
                response.status_code = 401
                response.headers['Content-Type'] = 'application/json'
                return response
            else:
                logger.info(f"馃攧 [鐧诲綍妫€鏌 閲嶅畾鍚戞湭鐧诲綍鐢ㄦ埛鍒扮櫥褰曢〉闈?")
                return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def account_or_legacy_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        has_account = bool(session.get("account_id") and auth_manager.get_account(session.get("account_id")))
        if session.get("account_id") and not has_account:
            session.pop("account_id", None)
        if not has_account and "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": "Authentication required",
                    "redirect_url": "/login",
                }), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

def _html_response_no_cache(html: str):
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

def _json_response_no_cache(payload: Dict[str, Any], status: int = 200):
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# 椤甸潰璺敱
@app.route('/')
def landing_page():
    """瀹ｄ紶椤甸潰"""
    try:
        with open('landing.html', 'r', encoding='utf-8') as f:
            return _html_response_no_cache(f.read())
    except FileNotFoundError:
        return "瀹ｄ紶椤甸潰鏂囦欢鏈壘鍒?, 404"

@app.route('/login')
def login():
    """棣栭〉 - 鐧诲綍鐣岄潰"""
    try:
        with open('login.html', 'r', encoding='utf-8') as f:
            return _html_response_no_cache(f.read())
    except FileNotFoundError:
        return "鐧诲綍椤甸潰鏂囦欢鏈壘鍒?, 404"

@app.route('/home')
@account_or_legacy_required
def home_page():
    try:
        with open('home.html', 'r', encoding='utf-8') as f:
            return _html_response_no_cache(f.read())
    except FileNotFoundError:
        return "鐢ㄦ埛棣栭〉鏂囦欢鏈壘鍒?, 404"

@app.route('/memory')
@account_or_legacy_required
def memory_page():
    try:
        with open('memory.html', 'r', encoding='utf-8') as f:
            return _html_response_no_cache(f.read())
    except FileNotFoundError:
        return "Memory page not found", 404

@app.route('/analysis')
@login_required
def analysis_interface():
    """AI鍒嗘瀽鐣岄潰"""
    user_id = session.get('user_id')
    try:
        with open('analysis-detail.html', 'r', encoding='utf-8') as f:
            return _html_response_no_cache(f.read())
    except FileNotFoundError:
        return "鍒嗘瀽椤甸潰鏂囦欢鏈壘鍒?, 404"

@app.route('/analysis-detail')
@login_required
def analysis_detail_alias():
    return analysis_interface()

@app.route('/birth-input')
def birth_input_page():
    """鍑虹敓淇℃伅杈撳叆椤甸潰"""
    try:
        with open('birth_input.html', 'r', encoding='utf-8') as f:
            return _html_response_no_cache(f.read())
    except FileNotFoundError:
        return "鍑虹敓淇℃伅杈撳叆椤甸潰鏂囦欢鏈壘鍒?, 404"

@app.route('/liuyao')
@login_required
def liuyao_page():
    """鍏埢鍗犲崪椤甸潰"""
    try:
        with open('liuyao.html', 'r', encoding='utf-8') as f:
            return _html_response_no_cache(f.read())
    except FileNotFoundError:
        return "鍏埢椤甸潰鏂囦欢鏈壘鍒?, 404"

@app.route('/qimen')
@login_required
def qimen_page():
    """濂囬棬閬佺敳椤甸潰"""
    try:
        with open('qimen.html', 'r', encoding='utf-8') as f:
            return _html_response_no_cache(f.read())
    except FileNotFoundError:
        return "濂囬棬椤甸潰鏂囦欢鏈壘鍒?, 404"

@app.route('/static/<path:filename>')
def serve_static(filename):
    """鎻愪緵闈欐€佹枃浠?"""
    return send_from_directory('static', filename)

# API 绔偣
@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    try:
        data = request.get_json(silent=True) or {}
        login_id = str(data.get("login_id") or data.get("phone") or data.get("nickname") or "").strip()
        pin = str(data.get("pin") or "").strip()
        display_name = str(data.get("display_name") or data.get("name") or data.get("nickname") or login_id).strip()
        if not login_id or not pin:
            return jsonify({"success": False, "error": "login_id and pin are required"}), 400
        if len(pin) < 4:
            return jsonify({"success": False, "error": "PIN must be at least 4 characters"}), 400

        account = auth_manager.create_account(
            login_id=login_id,
            pin=pin,
            display_name=display_name,
            role="user",
            metadata=_registration_birth_metadata(data),
        )
        bind_result = _try_auto_bind_account(account, data)
        account = bind_result["account"]
        profile_result = _ensure_account_bazi_from_birth_profile(account, data)
        account = profile_result["account"]
        _apply_account_session(account)
        profile_complete = _profile_complete(account.get("linked_user_id"))
        return jsonify({
            "success": True,
            "account": _public_account(account),
            "user_id": account.get("linked_user_id"),
            "profile_complete": profile_complete,
            "needs_profile": not profile_complete,
            "auto_bound": bind_result.get("auto_bound", False),
            "profile_created": profile_result.get("profile_created", False),
            "bazi_provider": profile_result.get("bazi_provider"),
            "bazi_duration_ms": profile_result.get("bazi_duration_ms"),
            "conflict_candidates": bind_result.get("candidates", []),
            "redirect_url": "/analysis" if profile_complete else "/home",
        })
    except ValueError as e:
        status = 409 if "exists" in str(e) else 400
        return jsonify({"success": False, "error": str(e)}), status
    except Exception as e:
        logger.error(f"auth register failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": "register failed"}), 500

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    try:
        data = request.get_json(silent=True) or {}
        login_id = str(data.get("login_id") or "").strip()
        pin = str(data.get("pin") or "").strip()
        if not login_id or not pin:
            return jsonify({"success": False, "error": "login_id and pin are required"}), 400

        account = auth_manager.authenticate(login_id, pin)
        if not account:
            return jsonify({"success": False, "error": "Invalid login_id or PIN"}), 401
        bind_result = _try_auto_bind_account(account, data)
        account = bind_result["account"]
        metadata = account.get("metadata") if isinstance(account.get("metadata"), dict) else {}
        stored_birth_profile = metadata.get("registration_birth_profile") if isinstance(metadata.get("registration_birth_profile"), dict) else {}
        if not account.get("linked_user_id") and stored_birth_profile:
            birth_payload = dict(stored_birth_profile)
            birth_payload.setdefault("login_id", account.get("login_id"))
            birth_payload.setdefault("display_name", account.get("display_name"))
            try:
                profile_result = _ensure_account_bazi_from_birth_profile(account, birth_payload)
                account = profile_result["account"]
            except Exception as e:
                logger.warning(f"auth login profile recovery failed: {e}")
        _apply_account_session(account)
        return jsonify({
            "success": True,
            "account": _public_account(account),
            "user_id": account.get("linked_user_id"),
            "profile_complete": _profile_complete(account.get("linked_user_id")),
            "needs_profile": not _profile_complete(account.get("linked_user_id")),
            "auto_bound": bind_result.get("auto_bound", False),
            "conflict_candidates": bind_result.get("candidates", []),
            "redirect_url": "/home",
        })
    except Exception as e:
        logger.error(f"auth login failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": "login failed"}), 500

@app.route('/api/auth/me', methods=['GET'])
def api_auth_me():
    account = _get_current_account()
    if account:
        linked_user_id = account.get("linked_user_id")
        profile_complete = _profile_complete(linked_user_id) or _account_profile_complete(account)
        return _json_response_no_cache({
            "authenticated": True,
            "role": account.get("role") or "user",
            "account": _public_account(account),
            "user_id": linked_user_id,
            "username": session.get("username") or account.get("display_name"),
            "profile_complete": profile_complete,
            "needs_profile": not profile_complete,
        })

    if session.get("user_id"):
        user_id = session.get("user_id")
        return _json_response_no_cache({
            "authenticated": True,
            "role": "legacy_user",
            "account": None,
            "user_id": user_id,
            "username": session.get("username"),
            "profile_complete": _profile_complete(user_id),
            "needs_profile": not _profile_complete(user_id),
        })

    return _json_response_no_cache({
        "authenticated": False,
        "role": None,
        "account": None,
        "user_id": None,
        "profile_complete": False,
        "needs_profile": True,
    })

@app.route('/api/user/home', methods=['GET'])
@account_or_legacy_required
def api_user_home():
    account = _get_current_account()
    if account:
        _apply_account_session(account)
    user_id = session.get("user_id") or (account or {}).get("linked_user_id")
    payload = _home_payload_for_user(user_id)
    if not user_id and account and _account_profile_complete(account):
        payload["needs_profile"] = False
        payload["profile_complete"] = True
        payload["bazi"] = _bazi_summary_from_account(account)
    payload.update({
        "success": True,
        "account": _public_account(account),
        "username": session.get("username"),
    })
    return _json_response_no_cache(payload)

@app.route('/api/memory/summary', methods=['GET'])
@account_or_legacy_required
def api_memory_summary():
    account = _get_current_account()
    if account:
        _apply_account_session(account)
    user_id = session.get("user_id") or (account or {}).get("linked_user_id")
    if not user_id:
        return jsonify({"success": False, "error": "No linked user profile"}), 400
    try:
        return jsonify(bazi_memory_manager.get_memory_summary(user_id))
    except Exception as e:
        logger.error("memory summary failed: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "memory summary failed"}), 500

def _memory_status_for_event(user_id: str, event_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        status = bazi_memory_manager.get_memory_status(user_id)
    except Exception as exc:
        return {
            "event_id": event_id,
            "status": "queued" if event_id else "unavailable",
            "event_status": None,
            "error": str(exc),
        }
    event_status = None
    for item in status.get("latest") or []:
        if isinstance(item, dict) and item.get("event_id") == event_id:
            event_status = item.get("status")
            break
    public_status = event_status
    if event_id and event_status in (None, "pending", "processing", "failed_retryable"):
        public_status = "queued"
    return {
        "event_id": event_id,
        "status": public_status,
        "event_status": event_status,
        "counts": status.get("counts") or {},
        "pending_count": status.get("pending_count", 0),
        "processing_count": status.get("processing_count", 0),
        "failed_count": status.get("failed_count", 0),
        "ready_count": status.get("ready_count", 0),
    }

def _markdown_scalar(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = " ".join(text.split()).strip()
    return text or fallback

def _markdown_json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value if value is not None else {}, ensure_ascii=False, indent=2, default=str) + "\n```"

def _append_markdown_pairs(lines: List[str], pairs: List[tuple]) -> None:
    for label, value in pairs:
        lines.append(f"- **{label}**：{_markdown_scalar(value)}")

def _export_filename(user_info: Dict[str, Any], user_id: str) -> str:
    raw_name = _markdown_scalar((user_info or {}).get("name"), user_id)
    safe_name = "".join(ch if ch not in '<>:"/\\|?*\r\n\t' else "_" for ch in raw_name).strip(" ._")
    safe_name = safe_name[:48] or user_id
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"命理记忆-{safe_name}-{stamp}.md"

def _extract_bazi_raw_data(bazi_data: Dict[str, Any]) -> Dict[str, Any]:
    bazi_info = bazi_data.get("bazi_info") if isinstance(bazi_data, dict) else {}
    if not isinstance(bazi_info, dict):
        return {}
    raw_data = bazi_info.get("raw_data")
    if isinstance(raw_data, dict):
        return raw_data
    text_result = bazi_info.get("text_result")
    if isinstance(text_result, str):
        try:
            parsed = json.loads(text_result)
            if isinstance(parsed, dict):
                raw = parsed.get("raw_data")
                return raw if isinstance(raw, dict) else parsed
        except Exception:
            return {}
    return {}

def _export_list(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]

def _export_hidden_stems(value: Any) -> List[Dict[str, Any]]:
    if not value:
        return []
    items: List[tuple] = []
    if isinstance(value, dict):
        ordered_keys = ["主气", "中气", "余气", "main", "middle", "rest"]
        for key in ordered_keys:
            if key in value:
                items.append((key, value.get(key)))
        for key, item in value.items():
            if key not in ordered_keys:
                items.append((key, item))
    elif isinstance(value, list):
        items = [("", item) for item in value]
    else:
        items = [("", value)]

    normalized: List[Dict[str, Any]] = []
    for role, item in items:
        if item in (None, ""):
            continue
        if isinstance(item, dict):
            normalized.append({
                "role": role,
                "char": item.get("天干") or item.get("char") or item.get("stem") or "",
                "element": item.get("五行") or item.get("element") or "",
                "yinYang": item.get("阴阳") or item.get("yin_yang") or item.get("yinYang") or "",
                "tenGod": item.get("十神") or item.get("ten_god") or item.get("tenGod") or "",
            })
        else:
            normalized.append({
                "role": role,
                "char": str(item),
                "element": "",
                "yinYang": "",
                "tenGod": "",
            })
    return [item for item in normalized if item.get("char")]

def _export_pillar_detail(raw_data: Dict[str, Any], label: str) -> Dict[str, Any]:
    raw = raw_data.get(label) if isinstance(raw_data, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    stem_raw = raw.get("天干") if isinstance(raw.get("天干"), dict) else {}
    branch_raw = raw.get("地支") if isinstance(raw.get("地支"), dict) else {}
    shensha = raw_data.get("神煞") if isinstance(raw_data.get("神煞"), dict) else {}

    stem_char = stem_raw.get("天干") or ""
    branch_char = branch_raw.get("地支") or ""
    return {
        "label": label,
        "ganzhi": f"{stem_char}{branch_char}".strip(),
        "stem": {
            "char": stem_char,
            "element": stem_raw.get("五行") or "",
            "yinYang": stem_raw.get("阴阳") or "",
            "tenGod": stem_raw.get("十神") or "",
        },
        "branch": {
            "char": branch_char,
            "element": branch_raw.get("五行") or "",
            "yinYang": branch_raw.get("阴阳") or "",
            "hiddenStems": _export_hidden_stems(branch_raw.get("藏干")),
        },
        "nayin": raw.get("纳音") or "",
        "xun": raw.get("旬") or "",
        "kongwang": raw.get("空亡") or "",
        "xingyun": raw.get("星运") or "",
        "zizuo": raw.get("自坐") or "",
        "shensha": _export_list(shensha.get(label)),
    }

def _export_dayun_details(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    source = raw_data.get("大运") if isinstance(raw_data, dict) else {}
    start_date = ""
    start_age = ""
    rows: List[Any] = []
    if isinstance(source, dict):
        start_date = source.get("起运日期") or source.get("start_date") or source.get("startDate") or ""
        start_age = source.get("起运年龄") or source.get("start_age") or source.get("startAge") or ""
        rows = source.get("大运") or source.get("rows") or source.get("cycles") or source.get("items") or []
    elif isinstance(source, list):
        rows = source

    cycles = []
    for index, row in enumerate(rows if isinstance(rows, list) else [], 1):
        if isinstance(row, str):
            cycles.append({"order": index, "ganzhi": row})
            continue
        if not isinstance(row, dict):
            continue
        cycles.append({
            "order": index,
            "ganzhi": row.get("干支") or row.get("ganzhi") or row.get("pillar") or "",
            "startYear": row.get("开始年份") or row.get("start_year") or row.get("startYear") or "",
            "endYear": row.get("结束") or row.get("结束年份") or row.get("end_year") or row.get("endYear") or "",
            "stemTenGod": row.get("天干十神") or row.get("stem_ten_god") or row.get("stemTenGod") or "",
            "branchTenGods": _export_list(row.get("地支十神") or row.get("branch_ten_gods") or row.get("branchTenGods")),
            "hiddenStems": _export_list(row.get("地支藏干") or row.get("hidden_stems") or row.get("hiddenStems")),
            "startAge": row.get("开始年龄") or row.get("start_age") or row.get("startAge") or "",
            "endAge": row.get("结束年龄") or row.get("end_age") or row.get("endAge") or "",
        })
    return {"startDate": start_date, "startAge": start_age, "cycles": cycles}

def _build_pdf_chart_details(
    raw_data: Dict[str, Any],
    bazi_info: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Dict[str, Any]:
    raw_data = raw_data if isinstance(raw_data, dict) else {}
    bazi_info = bazi_info if isinstance(bazi_info, dict) else {}
    user_info = user_info if isinstance(user_info, dict) else {}
    return {
        "meta": {
            "gender": raw_data.get("性别") or user_info.get("gender"),
            "solar": raw_data.get("阳历"),
            "lunar": raw_data.get("农历"),
            "bazi": raw_data.get("八字"),
            "zodiac": raw_data.get("生肖"),
            "dayMaster": raw_data.get("日主"),
            "calendarType": user_info.get("calendar_type"),
            "solarTimeApplied": user_info.get("solar_time_applied"),
            "trueSolarTime": user_info.get("true_solar_time"),
            "longitude": user_info.get("longitude"),
            "chartSignature": user_info.get("chart_signature"),
        },
        "extra": {
            "胎元": raw_data.get("胎元"),
            "胎息": raw_data.get("胎息"),
            "命宫": raw_data.get("命宫"),
            "身宫": raw_data.get("身宫"),
        },
        "pillars": [
            _export_pillar_detail(raw_data, "年柱"),
            _export_pillar_detail(raw_data, "月柱"),
            _export_pillar_detail(raw_data, "日柱"),
            _export_pillar_detail(raw_data, "时柱"),
        ],
        "dayun": _export_dayun_details(raw_data),
        "relations": raw_data.get("刑冲合会") if isinstance(raw_data.get("刑冲合会"), dict) else {},
        "fiveElements": bazi_info.get("five_elements") or raw_data.get("五行") or {},
        "tenGods": bazi_info.get("ten_gods") or raw_data.get("十神") or {},
    }

def _compact_export_text(value: Any, max_len: int = 1200) -> str:
    text = "\n".join(line.strip() for line in str(value or "").splitlines() if line.strip()).strip()
    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."
    return text

def _chart_export_payload(
    bazi_data: Dict[str, Any],
    chart_facts: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    user_info = bazi_data.get("user_info") if isinstance(bazi_data, dict) else {}
    bazi_info = bazi_data.get("bazi_info") if isinstance(bazi_data, dict) else {}
    user_info = user_info if isinstance(user_info, dict) else {}
    bazi_info = bazi_info if isinstance(bazi_info, dict) else {}
    raw_data = _extract_bazi_raw_data(bazi_data)
    chart_facts = chart_facts if isinstance(chart_facts, dict) else {}

    payload = {
        "出生资料": {
            "姓名": user_info.get("name"),
            "性别": user_info.get("gender") or raw_data.get("性别"),
            "出生日期": user_info.get("birth_date"),
            "出生时间": user_info.get("birth_time") or bazi_info.get("birth_time"),
            "历法": user_info.get("calendar_type"),
            "闰月": user_info.get("lunar_is_leap_month"),
        },
        "基础命盘": {
            "阳历": raw_data.get("阳历"),
            "农历": raw_data.get("农历"),
            "八字": raw_data.get("八字"),
            "生肖": raw_data.get("生肖"),
            "日主": raw_data.get("日主"),
            "胎元": raw_data.get("胎元"),
            "胎息": raw_data.get("胎息"),
            "命宫": raw_data.get("命宫"),
            "身宫": raw_data.get("身宫"),
        },
        "四柱": {
            "年柱": raw_data.get("年柱"),
            "月柱": raw_data.get("月柱"),
            "日柱": raw_data.get("日柱"),
            "时柱": raw_data.get("时柱"),
        },
        "神煞": raw_data.get("神煞"),
        "大运": raw_data.get("大运"),
        "刑冲合会": raw_data.get("刑冲合会"),
        "五行": bazi_info.get("five_elements") or chart_facts.get("five_elements"),
        "十神": bazi_info.get("ten_gods") or chart_facts.get("ten_gods"),
        "命盘摘要": ((chart_facts.get("summary") or {}).get("chart_facts_text") if isinstance(chart_facts.get("summary"), dict) else ""),
    }
    return {key: value for key, value in payload.items() if value not in ({}, [], None, "")}

def _append_bazi_export_section(
    lines: List[str],
    bazi_data: Dict[str, Any],
    chart_facts: Optional[Dict[str, Any]],
) -> None:
    lines.extend(["", "## 命盘数据", "", _markdown_json_block(_chart_export_payload(bazi_data or {}, chart_facts))])

def _memory_type_label(memory_type: str) -> str:
    labels = {
        "support_profile": "沟通偏好与稳定画像",
        "domain_insight": "领域摘要与稳定判断",
        "episode": "近期对话片段",
        "analysis": "分析记录",
        "interpretation": "解读记录",
        "followup": "追问记录",
    }
    return labels.get(memory_type or "", memory_type or "其他记忆")

def _memory_item_title(item: Dict[str, Any], index: int) -> str:
    pieces = [
        item.get("dimension"),
        item.get("domain"),
        item.get("type"),
    ]
    title = " / ".join(str(piece).strip() for piece in pieces if piece)
    return title or f"记忆 {index}"

def _append_memory_item(lines: List[str], item: Dict[str, Any], index: int) -> None:
    lines.extend(["", f"#### {index}. {_memory_item_title(item, index)}"])
    _append_markdown_pairs(lines, [
        ("ID", item.get("id")),
        ("类型", item.get("type")),
        ("领域", item.get("domain")),
        ("维度", item.get("dimension")),
        ("置顶", "是" if item.get("pinned") else "否"),
        ("状态", "停用" if item.get("disabled") else "启用"),
        ("创建时间", item.get("created_at")),
        ("更新时间", item.get("updated_at")),
    ])
    content = str(item.get("content") or "").strip()
    lines.extend(["", content or "—", "", "<details>", "<summary>完整字段</summary>", "", _markdown_json_block(item), "", "</details>"])

def _append_memory_export_section(
    lines: List[str],
    memory_doc: Dict[str, Any],
    profile_doc: Dict[str, Any],
    insights_doc: Dict[str, Any],
    summary: Dict[str, Any],
) -> None:
    memory_doc = memory_doc if isinstance(memory_doc, dict) else {}
    items = [item for item in (memory_doc.get("items") or []) if isinstance(item, dict)]
    active_items = [item for item in items if not item.get("disabled")]

    profile_doc = profile_doc if isinstance(profile_doc, dict) else {}
    insights_doc = insights_doc if isinstance(insights_doc, dict) else {}
    lines.extend(["", "## 记忆摘要", "", "### 用户偏好"])
    lines.append(_markdown_json_block({
        "memory_preferences": memory_doc.get("preferences") or {},
        "profile_preferences": profile_doc.get("preferences") or {},
        "tags": profile_doc.get("tags") or [],
    }))

    lines.extend(["", "### 摘要概览"])
    _append_markdown_pairs(lines, [
        ("摘要条目", len(active_items)),
        ("置顶条目", len([item for item in active_items if item.get("pinned")])),
        ("文档版本", memory_doc.get("schema_version")),
        ("最近更新", memory_doc.get("updated_at")),
    ])

    profile_summary = ((summary or {}).get("profile") or {}).get("summary") if isinstance(summary, dict) else ""
    lines.extend(["", "### 沟通偏好与稳定画像", "", _compact_export_text(profile_summary) or "—"])

    dimensions = insights_doc.get("dimensions") if isinstance(insights_doc.get("dimensions"), dict) else {}
    if dimensions:
        lines.extend(["", "### 领域洞察摘要"])
        for dimension, payload in dimensions.items():
            if not isinstance(payload, dict):
                continue
            versions = payload.get("versions") if isinstance(payload.get("versions"), dict) else {}
            summaries = []
            for version_payload in versions.values():
                if not isinstance(version_payload, dict):
                    continue
                current = version_payload.get("current") if isinstance(version_payload.get("current"), dict) else {}
                points = current.get("summary_points") if isinstance(current.get("summary_points"), list) else []
                summaries.extend(str(point).strip() for point in points if str(point).strip())
            if summaries:
                lines.append(f"- **{_markdown_scalar(dimension)}**：{_compact_export_text('；'.join(summaries), 500)}")

    ordered_types = ["support_profile", "domain_insight", "episode"]
    remaining_types = sorted({str(item.get("type") or "memory") for item in active_items} - set(ordered_types))
    for memory_type in ordered_types + remaining_types:
        bucket = [item for item in active_items if str(item.get("type") or "memory") == memory_type]
        if not bucket:
            continue
        lines.extend(["", f"### {_memory_type_label(memory_type)}（{len(bucket)} 条）"])
        for index, item in enumerate(bucket, 1):
            title = _memory_item_title(item, index)
            updated_at = _markdown_scalar(item.get("updated_at"), "")
            suffix = f"（{updated_at}）" if updated_at else ""
            lines.append(f"- **{_markdown_scalar(title)}**{suffix}：{_compact_export_text(item.get('content'), 800) or '—'}")

def _build_memory_export_markdown(
    user_id: str,
    bazi_data: Dict[str, Any],
    memory_doc: Dict[str, Any],
    chart_facts: Optional[Dict[str, Any]],
    profile_doc: Dict[str, Any],
    insights_doc: Dict[str, Any],
    summary: Dict[str, Any],
) -> str:
    lines: List[str] = [
        "# 命理记忆导出",
        "",
        f"- **用户档案**：{_markdown_scalar(user_id)}",
        f"- **导出时间**：{datetime.now().isoformat(timespec='seconds')}",
        "- **文件说明**：此文件仅包含去重后的命盘数据、记忆摘要与用户偏好，不包含完整对话记录。",
    ]
    _append_bazi_export_section(lines, bazi_data or {}, chart_facts)
    _append_memory_export_section(lines, memory_doc or {}, profile_doc or {}, insights_doc or {}, summary or {})
    return "\n".join(lines).rstrip() + "\n"

@app.route('/api/memory/export', methods=['GET'])
@account_or_legacy_required
def api_memory_export():
    account = _get_current_account()
    if account:
        _apply_account_session(account)
    user_id = session.get("user_id") or (account or {}).get("linked_user_id")
    if not user_id:
        return jsonify({"success": False, "error": "No linked user profile"}), 400

    try:
        bazi_data = load_from_local_file(get_user_bazi_file(user_id))
        memory_doc = bazi_memory_manager.get_memory_items_doc(user_id)
        chart_facts = bazi_memory_manager.get_chart_facts(user_id)
        profile_doc = bazi_memory_manager.get_profile_doc(user_id)
        insights_doc = bazi_memory_manager.get_insights_doc(user_id)
        summary = {
            "profile": {
                "summary": bazi_memory_manager.format_profile_text(profile_doc, max_len=700),
            }
        }
        markdown = _build_memory_export_markdown(
            user_id=user_id,
            bazi_data=bazi_data,
            memory_doc=memory_doc,
            chart_facts=chart_facts,
            profile_doc=profile_doc,
            insights_doc=insights_doc,
            summary=summary,
        )
        user_info = bazi_data.get("user_info") if isinstance(bazi_data, dict) else {}
        filename = _export_filename(user_info if isinstance(user_info, dict) else {}, user_id)
        response = make_response(markdown)
        response.headers["Content-Type"] = "text/markdown; charset=utf-8"
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception as e:
        logger.error("memory export failed: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "memory export failed"}), 500

def _compact_home_memory_text(value: Any, max_len: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."
    return text

def _parse_home_memory_time(value: Any) -> float:
    if not value:
        return 0.0
    try:
        normalized = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0

def _clean_home_profile_summary(value: Any) -> str:
    lines = []
    for line in str(value or "").splitlines():
        lowered = line.lower()
        if "user_id" in lowered or "用户 id" in lowered or "用户id" in lowered:
            continue
        clean = line.strip()
        if clean:
            lines.append(clean)
    text = " ".join(lines).strip()
    if text in ("用户画像：", "用户画像:"):
        return ""
    return _compact_home_memory_text(text, 520)

def _home_portrait_sources(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    categories = summary.get("categories") if isinstance(summary, dict) else {}
    if not isinstance(categories, dict):
        categories = {}

    sources: List[Dict[str, Any]] = []
    profile_summary = _clean_home_profile_summary(((summary.get("profile") or {}).get("summary") if isinstance(summary, dict) else ""))
    if profile_summary:
        sources.append({
            "type": "profile",
            "label": "历史画像",
            "dimension": "全局",
            "content": profile_summary,
            "updated_at": "",
        })

    labels = {
        "support_profile": "画像偏好",
        "domain_insight": "稳定判断",
        "episode": "追问片段",
    }
    for memory_type in ("support_profile", "domain_insight", "episode"):
        bucket = categories.get(memory_type) or {}
        items = bucket.get("items") if isinstance(bucket, dict) else []
        sorted_items = sorted(
            [item for item in (items or []) if isinstance(item, dict)],
            key=lambda item: _parse_home_memory_time(item.get("updated_at") or item.get("created_at")),
            reverse=True,
        )
        for item in sorted_items[:4]:
            content = _compact_home_memory_text(item.get("content"), 220)
            if not content:
                continue
            sources.append({
                "type": memory_type,
                "label": labels.get(memory_type, "记忆"),
                "dimension": item.get("dimension") or item.get("domain") or "综合关注",
                "content": content,
                "updated_at": item.get("updated_at") or item.get("created_at") or "",
            })
    return sources[:10]

def _fallback_home_portrait(summary: Dict[str, Any]) -> Dict[str, Any]:
    sources = [item for item in _home_portrait_sources(summary) if item.get("type") != "profile"]
    points: List[str] = []
    latest = ""
    for source in sources:
        if not latest:
            latest = str(source.get("updated_at") or "")
        content = _compact_home_memory_text(source.get("content"), 46)
        if content and content not in points:
            points.append(content)
        if len(points) >= 3:
            break

    if not points:
        return {
            "headline": "画像待完善",
            "summary": "",
            "points": [],
            "updated_at": latest,
        }

    return {
        "headline": "偏好已沉淀",
        "summary": points[0],
        "points": points[1:3],
        "updated_at": latest,
    }

def _build_home_portrait_prompt(summary: Dict[str, Any], sources: List[Dict[str, Any]]) -> str:
    payload = {
        "profile": _clean_home_profile_summary(((summary.get("profile") or {}).get("summary") if isinstance(summary, dict) else "")),
        "memories": sources,
    }
    return (
        "你是一个命理产品的用户画像整理助手。只基于给定记忆材料，输出首页用的短画像。\n"
        "要求：不要输出用户ID、内部ref、隐私原文；不要诊断心理或医疗问题；不要给确定性命运断言。\n"
        "只返回严格 JSON，不要 Markdown。JSON 格式："
        '{"headline":"不超过14个汉字","summary":"不超过60个汉字","points":["每条不超过28个汉字，2到3条"]}\n'
        f"材料：{json.dumps(payload, ensure_ascii=False)}"
    )

def _extract_home_portrait_json(value: Any) -> Dict[str, Any]:
    raw = str(value or "").strip()
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

def _normalize_home_portrait(data: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    headline = _compact_home_memory_text(data.get("headline"), 18) or fallback.get("headline") or "偏好已沉淀"
    summary = _compact_home_memory_text(data.get("summary"), 92) or fallback.get("summary") or ""
    raw_points = data.get("points")
    if not isinstance(raw_points, list):
        raw_points = fallback.get("points") or []
    points = []
    for item in raw_points:
        point = _compact_home_memory_text(item, 42)
        if point and point not in points:
            points.append(point)
        if len(points) >= 3:
            break
    return {
        "headline": headline,
        "summary": summary,
        "points": points,
        "updated_at": fallback.get("updated_at") or "",
    }

@app.route('/api/memory/home-portrait', methods=['GET'])
@account_or_legacy_required
def api_memory_home_portrait():
    account = _get_current_account()
    if account:
        _apply_account_session(account)
    user_id = session.get("user_id") or (account or {}).get("linked_user_id")
    if not user_id:
        return _json_response_no_cache({"success": False, "error": "No linked user profile"}, 400)

    try:
        summary = bazi_memory_manager.get_memory_summary(user_id)
        sources = _home_portrait_sources(summary)
        fallback = _fallback_home_portrait(summary)
        portrait = fallback
        ai_used = False
        model_used = None

        if sources and getattr(ai_analyzer, "deepseek_client", None):
            options = get_deepseek_followup_options()
            model_used = options.get("model") or get_deepseek_dialog_model()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(ai_analyzer.analyze_with_deepseek(
                    _build_home_portrait_prompt(summary, sources),
                    model_name=model_used,
                    temperature=0.15,
                    max_tokens=options.get("max_tokens") or 420,
                    timeout=options.get("timeout") or 12,
                ))
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
            content = result.content if hasattr(result, "content") else str(result)
            parsed = _extract_home_portrait_json(content)
            if parsed:
                portrait = _normalize_home_portrait(parsed, fallback)
                ai_used = True

        return _json_response_no_cache({
            "success": True,
            "portrait": portrait,
            "ai_used": ai_used,
            "model": model_used if ai_used else None,
            "source_count": len(sources),
        })
    except Exception as e:
        logger.error("home portrait failed: %s", e, exc_info=True)
        return _json_response_no_cache({"success": False, "error": "home portrait failed"}, 500)

@app.route('/api/memory/items/<memory_id>/pin', methods=['POST'])
@account_or_legacy_required
def api_memory_pin(memory_id: str):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "No linked user profile"}), 400
    body = request.get_json(silent=True) or {}
    pinned = body.get("pinned")
    if pinned is None:
        pinned = True
    item = bazi_memory_manager.set_memory_item_pin(user_id, memory_id, bool(pinned))
    if not item:
        return jsonify({"success": False, "error": "Memory item not found"}), 404
    return jsonify({"success": True, "item": item})

@app.route('/api/memory/items/<memory_id>', methods=['DELETE'])
@account_or_legacy_required
def api_memory_delete(memory_id: str):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "No linked user profile"}), 400
    deleted = bazi_memory_manager.delete_memory_item(user_id, memory_id)
    if not deleted:
        return jsonify({"success": False, "error": "Memory item not found"}), 404
    return jsonify({"success": True, "deleted": True})

@app.route('/api/memory/preferences', methods=['POST'])
@account_or_legacy_required
def api_memory_preferences():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "No linked user profile"}), 400
    body = request.get_json(silent=True) or {}
    allowed = {}
    for key in ("memory_enabled", "emotional_memory_enabled", "disabled_types"):
        if key in body:
            allowed[key] = body[key]
    prefs = bazi_memory_manager.update_memory_preferences(user_id, allowed)
    return jsonify({"success": True, "preferences": prefs})

@app.route('/api/memory/rebuild', methods=['POST'])
@account_or_legacy_required
def api_memory_rebuild():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "No linked user profile"}), 400
    try:
        organizer_status = bazi_memory_manager.get_memory_status(user_id)
        pending = organizer_status.get("pending_count")
        if memory_organizer:
            try:
                if pending:
                    memory_organizer.notify(user_id)
            except Exception:
                pending = None
        summary = bazi_memory_manager.get_memory_summary(user_id)
        return jsonify({
            "success": True,
            "backfill": {"mode": "background", "synchronous": False},
            "pending_events": pending,
            "organizer_status": organizer_status,
            "summary": summary,
        })
    except Exception as e:
        logger.error("memory rebuild failed: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "memory rebuild failed"}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    """澶勭悊鐧诲綍璇锋眰"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "缂哄皯璇锋眰鏁版嵁"}), 400

        # 鎻愬彇鐢ㄦ埛淇℃伅
        name = str(data.get('name', '')).strip()
        gender_raw = data.get('gender', '')
        gender = str(gender_raw).strip() if gender_raw is not None else ''
        birth_date = str(data.get('birth_date', '')).strip()
        birth_time_raw = data.get('birth_time', '')
        birth_time = str(birth_time_raw).strip() if birth_time_raw is not None else ''
        calendar_type = str(data.get('calendar_type', 'solar')).strip()
        skip_bazi = bool(data.get("skip_bazi"))
        
        # 鎻愬彇鍑虹敓鍦颁俊鎭?
        location = data.get('location', {})
        if isinstance(location, dict):
            # 娓呯悊 location 鏁版嵁
            location = {k: str(v).strip() for k, v in location.items() if v}
        else:
            location = {}

        # 楠岃瘉蹇呭～瀛楁
        if not all([name, gender, birth_date]):
            return jsonify({"error": "濮撳悕銆佹€у埆鍜屽嚭鐢熸棩鏈熶负蹇呭～椤?"}), 400

        gender_int = _normalize_gender_value(gender)

        # 鍐滃巻杞崲閫昏緫
        original_birth_date = birth_date
        original_birth_time = birth_time
        
        if calendar_type == 'lunar':
            if LunarDate is None:
                logger.warning("鈿狅笍 鏈畨瑁?lunardate 搴擄紝鏃犳硶杩涜鍐滃巻杞崲锛屽皢鎸夐槼鍘嗗鐞?")
            else:
                try:
                    # 瑙ｆ瀽骞存湀鏃?
                    y, m, d = map(int, birth_date.split('-'))
                    # 杞崲鍐滃巻涓洪槼鍘?
                    solar_date = LunarDate(y, m, d).toSolarDate()
                    # 鏇存柊涓洪槼鍘嗘棩鏈?
                    birth_date = f"{solar_date.year}-{solar_date.month:02d}-{solar_date.day:02d}"
                    logger.info(f"馃寵 [鍐滃巻杞崲] {original_birth_date} (鍐滃巻) -> {birth_date} (闃冲巻)")
                    
                    # 杞崲鍚庯紝鍚庣画娴佺▼鎸夐槼鍘嗗鐞嗭紝浣嗛渶淇濈暀 calendar_type='lunar' 鏍囪瘑缁?Ziwei MCP
                    # 娉ㄦ剰锛歓iwei MCP 鍙兘鑷繁澶勭悊鍐滃巻锛屼篃鍙兘闇€瑕侀槼鍘?
                    # 鏍规嵁 ziwei_client.py 鐨?generate_chart 鏂规硶锛屽畠鎺ュ彈 calendar 鍙傛暟
                    # 浣嗕负浜嗙粺涓€ bazi_client 鍜屽叾浠栫粍浠讹紝鏈€濂界粺涓€杞负闃冲巻 ISO 鏃堕棿浣滀负鍩哄噯
                except Exception as e:
                    logger.error(f"鉂?[鍐滃巻杞崲] 澶辫触: {e}")
                    return jsonify({"error": "鍐滃巻鏃ユ湡鏃犳晥"}), 400

        if birth_time and birth_time != "12:00":
            full_datetime = f"{birth_date}T{birth_time}:00+08:00"
        else:
            full_datetime = f"{birth_date}T12:00:00+08:00"

        # 鑷姩鑾峰彇鍏瓧淇℃伅
        bazi_data = None
        try:
            if skip_bazi:
                logger.info(f"鈴笍 [鐧诲綍鑷姩鍏瓧] 鐢ㄦ埛閫夋嫨璺宠繃鍏瓧鑾峰彇")
            else:
                logger.info(f"馃敭 [鐧诲綍鑷姩鍏瓧] 寮€濮嬭幏鍙栧叓瀛椾俊鎭?..")
                
                # 鏋勫缓鍏瓧鑾峰彇璇锋眰鏁版嵁
                # 娉ㄦ剰锛欱azi MCP 鍙兘闇€瑕佸噯纭殑闃冲巻鏃堕棿锛堢湡澶槼鏃讹級锛屾垨鑰呮牴鎹?calendar_type 鑷澶勭悊
                # 鎴戜滑鐨勭瓥鐣ワ細鎬绘槸璁＄畻鍑哄噯纭殑闃冲巻鐪熷お闃虫椂缁?Bazi MCP锛屽悓鏃朵紶閫掑師濮嬩俊鎭?
                
                bazi_request_data = {
                    "name": name,
                    "gender": int(gender_int) if gender_int is not None else 1,
                    "birth_date": birth_date, # 宸茬粡鏄槼鍘嗘棩鏈?
                    "birth_time": full_datetime,  # 宸茬粡鏄槼鍘?ISO 鏃堕棿
                    "calendar_type": "solar", # 寮哄埗鍛婅瘔 Bazi MCP 杩欐槸闃冲巻锛屽洜涓烘垜浠凡缁忚浆鎹㈣繃浜?
                    "location": location 
                }
                
                # 鑷姩搴旂敤鐪熷お闃虫椂淇 (濡傛灉鎻愪緵浜嗗嚭鐢熷湴)
                # 鏃犺鏄師鏈槸鍐滃巻杩樻槸闃冲巻锛屾鏃?full_datetime 閮芥槸骞冲お闃虫椂锛堥槼鍘嗭級锛屽彲浠ヨ繘琛岀粡搴︿慨姝?
                if location and full_datetime:
                    try:
                        # 1. 瑙ｆ瀽缁忓害
                        prov = location.get("province", "")
                        city = location.get("city", "")
                        dist = location.get("district", "")
                        addr = location.get("address", "")
                        
                        # 浼樺厛浣跨敤绂荤嚎瀛楀吀鑾峰彇缁忓害
                        coords = get_offline_coordinates(province=prov, city=city, district=dist, address=addr)
                        longitude = None
                        
                        if coords:
                            _, longitude = coords
                            logger.info(f"馃搷 [鐪熷お闃虫椂] 浣跨敤绂荤嚎鍧愭爣: {prov} {city} -> {longitude}掳E")
                        
                        # 濡傛灉绂荤嚎瀛楀吀澶辫触锛屽皾璇曞湪绾挎煡璇?
                        if longitude is None:
                            try:
                                logger.info(f"馃寪 [鐪熷お闃虫椂] 绂荤嚎鍧愭爣鏈壘鍒帮紝灏濊瘯鍦ㄧ嚎鏌ヨ...")
                                loc_query = _build_location_query(location)
                                online_res = _geocode_location(loc_query)
                                if online_res:
                                    longitude = online_res.get("longitude")
                                    logger.info(f"馃搷 [鐪熷お闃虫椂] 鍦ㄧ嚎鏌ヨ鎴愬姛: {loc_query} -> {longitude}掳E")
                                else:
                                    logger.warning(f"鈿狅笍 [鐪熷お闃虫椂] 鍦ㄧ嚎鏌ヨ澶辫触: {loc_query}")
                            except Exception as e:
                                logger.warning(f"鈿狅笍 [鐪熷お闃虫椂] 鍦ㄧ嚎鏌ヨ寮傚父: {e}")

                        # 濡傛灉鏈夌粡搴︼紝杩涜淇
                        if longitude is not None:
                            # 瑙ｆ瀽ISO鏃堕棿 (鍋囪鏍煎紡涓?YYYY-MM-DDTHH:MM:SS+08:00)
                            dt_obj = datetime.fromisoformat(full_datetime)
                            
                            # 璁＄畻鐪熷お闃虫椂
                            true_solar_dt = calculate_true_solar_time(dt_obj, longitude)
                            
                            # 鏇存柊涓虹湡澶槼鏃?
                            true_solar_iso = true_solar_dt.isoformat()
                            
                            # 淇濇寔鏃跺尯鍚庣紑涓€鑷存€?(绠€鍗曞鐞嗭紝鍋囪杈撳叆閮芥槸+08:00)
                            if not true_solar_iso.endswith("+08:00"):
                                 true_solar_iso = true_solar_iso.split("+")[0] + "+08:00"
                            
                            bazi_request_data["birth_time"] = true_solar_iso
                            bazi_request_data["solar_time_applied"] = True # 鏍囪宸插簲鐢ㄧ湡澶槼鏃?
                            bazi_request_data["longitude"] = longitude
                            
                            logger.info(f"馃尀 [鐪熷お闃虫椂] 淇瀹屾垚:")
                            logger.info(f"   鍘熸椂闂? {full_datetime}")
                            logger.info(f"   鐪熷お闃? {true_solar_iso}")
                            logger.info(f"   缁忓害: {longitude}")
                            
                            # 鍚屾椂鏇存柊瀛樺叆profile鐨勬椂闂村悧锛熼€氬父寤鸿瀛樺師濮嬫椂闂达紝鍒嗘瀽鐢ㄧ湡澶槼鏃?
                            # 杩欓噷鍙奖鍝嶄紶閫掔粰 Bazi MCP 鐨勫弬鏁帮紝涓嶄慨鏀瑰師濮嬭緭鍏ヨ褰?
                    except Exception as e:
                        logger.warning(f"鈿狅笍 [鐪熷お闃虫椂] 璁＄畻澶辫触锛屽皢浣跨敤骞冲お闃虫椂: {e}")
                
                logger.info(f"馃晲 [鏃堕棿鏍煎紡] 杞崲缁撴灉:")
                logger.info(f"   鍘熷: {birth_date} {birth_time}")
                logger.info(f"   ISO鏍煎紡: {full_datetime}")
                logger.info(f"   鍑虹敓鍦? {location}")
                
                # 鍐呴儴璋冪敤鍏瓧鑾峰彇鍑芥暟
                with app.test_request_context('/api/bazi/get', 
                                            method='POST', 
                                            json=bazi_request_data):
                    # 璋冪敤鍏瓧鑾峰彇API
                    response = get_bazi_info()

                    if isinstance(response, tuple):
                        response_data, status_code = response
                        if status_code == 200:
                            response_json = json.loads(response_data.get_data())
                            if response_json.get('success'):
                                bazi_data = response_json.get('data', {}).get('bazi_info')
                                logger.info(f"鉁?[鐧诲綍鑷姩鍏瓧] 鍏瓧淇℃伅鑾峰彇鎴愬姛")
                            else:
                                logger.warning(f"鈿狅笍 [鐧诲綍鑷姩鍏瓧] 鍏瓧鑾峰彇澶辫触: {response_json.get('error')}")
                        else:
                            logger.warning(f"鈿狅笍 [鐧诲綍鑷姩鍏瓧] 鍏瓧API杩斿洖閿欒鐘舵€? {status_code}")
                    else:
                        response_json = json.loads(response.get_data())
                        if response_json.get('success'):
                            bazi_data = response_json.get('data', {}).get('bazi_info')
                            logger.info(f"鉁?[鐧诲綍鑷姩鍏瓧] 鍏瓧淇℃伅鑾峰彇鎴愬姛")
                        else:
                            logger.warning(f"鈿狅笍 [鐧诲綍鑷姩鍏瓧] 鍏瓧鑾峰彇澶辫触: {response_json.get('error')}")
                        
        except Exception as e:
            logger.warning(f"鈿狅笍 [鐧诲綍鑷姩鍏瓧] 鑾峰彇鍏瓧淇℃伅鏃跺嚭閿? {str(e)}")
            # 缁х画鐧诲綍娴佺▼锛屼笉鍥犱负鍏瓧鑾峰彇澶辫触鑰屼腑鏂櫥褰?

        resolved_user_id = resolve_or_create_user_id_by_chart(
            name=name,
            gender=gender_int,
            birth_time_iso=full_datetime, # 瀛樺叆鐨勬槸闃冲巻ISO
            calendar_type=calendar_type, # 瀛樺叆鍘熷鐨勫巻娉曠被鍨?
            birth_date=original_birth_date if calendar_type == 'lunar' else birth_date, # 瀛樺叆鍘熷鏃ユ湡
        )

        # 璁剧疆浼氳瘽
        session['user_id'] = resolved_user_id
        session['username'] = name
        session['login_time'] = datetime.now().isoformat()
        _bind_current_account_to_user(resolved_user_id)
        if bazi_data:
            session['bazi_data'] = bazi_data

        try:
            bazi_memory_manager.update_profile(
                user_id=resolved_user_id,
                background={
                    "name": name,
                    "gender": gender_int,
                    "birth_date": original_birth_date if calendar_type == 'lunar' else birth_date,
                    "birth_time": original_birth_time if calendar_type == 'lunar' else full_datetime,
                    "calendar_type": calendar_type,
                    "location": location,
                    "solar_birth_date": birth_date, # 琛ュ厖闃冲巻鏃ユ湡
                    "solar_birth_time": full_datetime # 琛ュ厖闃冲巻鏃堕棿
                },
                preferences={},
                add_tags=["鐧诲綍"],
                feedback_text=None,
            )
        except Exception:
            pass

        logger.info(f"鐢ㄦ埛鐧诲綍鎴愬姛: {name} (ID: {resolved_user_id})")

        response_data = {
            "success": True,
            "message": "鐧诲綍鎴愬姛",
            "user_id": resolved_user_id,
            "username": name,
            "redirect_url": "/analysis"
        }
        
        # 濡傛灉鎴愬姛鑾峰彇鍒板叓瀛楁暟鎹紝涔熻繑鍥炵粰鍓嶇
        if bazi_data and not skip_bazi:
            response_data["bazi_data"] = bazi_data
            response_data["bazi_available"] = True
            logger.info(f"馃帄 [鐧诲綍瀹屾垚] 鐢ㄦ埛鐧诲綍鎴愬姛骞惰幏鍙栧埌鍏瓧淇℃伅")
        else:
            response_data["bazi_available"] = False
            logger.info(f"鈿狅笍 [鐧诲綍瀹屾垚] 鐢ㄦ埛鐧诲綍鎴愬姛浣嗘湭鑾峰彇鍒板叓瀛椾俊鎭?")

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"鐧诲綍澶勭悊澶辫触: {e}", exc_info=True)
        return jsonify({"error": "鐧诲綍澶勭悊澶辫触锛岃閲嶈瘯"}), 500

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """澶勭悊鐧诲嚭璇锋眰"""
    try:
        user_id = session.get('user_id')
        username = session.get('username')
        
        # 娓呴櫎浼氳瘽
        session.clear()
        
        logger.info(f"鐢ㄦ埛鐧诲嚭: {username} (ID: {user_id})")
        
        return jsonify({
            "success": True,
            "message": "鐧诲嚭鎴愬姛",
            "redirect_url": "/"
        })
    except Exception as e:
        logger.error(f"鐧诲嚭澶勭悊澶辫触: {e}", exc_info=True)
        return jsonify({"error": "鐧诲嚭澶勭悊澶辫触"}), 500

@app.route('/api/ziwei/chart', methods=['POST'])
@login_required
def api_ziwei_chart():
    if not MCP_ZIWEI_ENABLED:
        return jsonify({"success": False, "error": "ziwei mcp disabled"}), 400

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "娴嬭瘯鐢ㄦ埛").strip()
    birth_date = (body.get("birth_date") or "1990-05-15").strip()
    birth_time = (body.get("birth_time") or "14:30").strip()
    gender = (body.get("gender") or "male").strip()
    location = body.get("location") if isinstance(body.get("location"), dict) else None
    aspects = body.get("aspects") if isinstance(body.get("aspects"), list) else None
    detail_level = (body.get("detail_level") or "basic").strip()

    if "T" in birth_date and len(birth_date) >= 10:
        dt_parts = birth_date.split("T", 1)
        birth_date = dt_parts[0].strip()
        t = (dt_parts[1] or "").strip()
        hhmm = t[:5]
        if len(hhmm) == 5 and hhmm[2] == ":":
            birth_time = hhmm

    if len(birth_time) >= 5:
        bt = birth_time.strip()
        birth_time = bt[:5] if len(bt) >= 5 and bt[2] == ":" else bt

    if location:
        try:
            prov = (location.get("province") or "").strip()
            city = (location.get("city") or "").strip()
            lon = location.get("longitude")
            lat = location.get("latitude")
            lon_f = float(lon) if lon is not None and str(lon).strip() != "" else 0.0
            lat_f = float(lat) if lat is not None and str(lat).strip() != "" else 0.0
            if not prov and not city and abs(lon_f) < 1e-9 and abs(lat_f) < 1e-9:
                location = None
        except Exception:
            pass

    request_id = str(uuid.uuid4())

    async def _run():
        client = ZiweiClient(request_id=request_id)
        chart = await client.generate_chart(
            name=name,
            birth_date=birth_date,
            birth_time=birth_time,
            gender=gender,
            location=location,
        )

        chart_id = (
            (chart.get("chartId") if isinstance(chart, dict) else None)
            or (chart.get("chart_id") if isinstance(chart, dict) else None)
            or (chart.get("id") if isinstance(chart, dict) else None)
            or (((chart.get("data") or {}).get("chartId")) if isinstance(chart, dict) else None)
            or (((chart.get("data") or {}).get("id")) if isinstance(chart, dict) else None)
        )

        interpret = None
        if chart_id:
            interpret = await client.interpret_chart(
                chart_id=str(chart_id),
                aspects=aspects,
                detail_level=detail_level,
            )

        return chart, chart_id, interpret

    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        chart, chart_id, interpret = loop.run_until_complete(_run())
        loop.close()
        loop = None
        return jsonify(
            {
                "success": True,
                "chart_id": chart_id,
                "chart": chart,
                "interpret": interpret,
            }
        )
    except Exception as e:
        if loop is not None:
            try:
                loop.close()
            except Exception:
                pass
        return jsonify({"success": False, "error_type": type(e).__name__, "error": str(e)[:500]}), 500


def _ziwei_chart_to_text(chart: Any, max_len: int = 2600) -> str:
    if not isinstance(chart, dict):
        return ""
    chart_core = chart
    if isinstance(chart.get("data"), dict) and isinstance((chart.get("data") or {}).get("chart"), dict):
        chart_core = chart["data"]["chart"]
    if isinstance(chart.get("chart"), dict):
        chart_core = chart["chart"]

    info = chart_core.get("info") if isinstance(chart_core.get("info"), dict) else {}
    palaces = chart_core.get("palaces") if isinstance(chart_core.get("palaces"), list) else []

    lines = []
    if info:
        lines.append("銆愬熀鏈俊鎭€?")
        for k in ("name", "gender", "birthDate", "birthTime", "lunarDate", "age", "destinyPalace", "bodyPalace"):
            v = info.get(k)
            if v is not None and str(v).strip() != "":
                lines.append(f"- {k}: {v}")
    if palaces:
        lines.append("\n銆愬崄浜屽鎽樿銆?")
        for p in palaces[:12]:
            if not isinstance(p, dict):
                continue
            pname = (p.get("name") or "").strip()
            eb = (p.get("earthlyBranch") or "").strip()
            el = (p.get("element") or "").strip()
            strength = p.get("strength")
            main_star = ""
            ms = p.get("mainStar") if isinstance(p.get("mainStar"), dict) else None
            if ms:
                main_star = (ms.get("name") or "").strip()
                br = (ms.get("brightness") or "").strip()
                if br:
                    main_star = f"{main_star}({br})" if main_star else ""
            parts = [x for x in [pname, eb, el, (f"寮哄害{strength}" if isinstance(strength, (int, float)) else ""), (f"涓绘槦{main_star}" if main_star else "")] if x]
            if parts:
                lines.append("- " + " / ".join(parts))
    out = "\n".join(lines).strip()
    if len(out) > max_len:
        return out[:max_len] + "鈥?"
    return out


def _build_ziwei_chat_prompt(
    *,
    user_question: str,
    chart: Any,
    conversation: List[Dict[str, Any]],
    shared_memory_context: Optional[str],
    style: str,
) -> str:
    q = (user_question or "").strip()
    style_key = (style or "").strip().lower()
    role_desc = "浣犳槸涓€浣嶇簿閫氱传寰枟鏁扮殑鍛界悊甯堬紝鍚屾椂鍏峰娓呮櫚琛ㄨ揪涓庡挩璇㈠璇濊兘鍔涖€?"
    if style_key in ("interpretation", "wisdom", "friendly"):
        tone = "琛ㄨ揪瑕侀€氫織銆佺粨鏋勬竻鏅般€佸彲鎿嶄綔寤鸿浼樺厛锛岄伩鍏嶅爢鐮屾湳璇€?"
    else:
        tone = "琛ㄨ揪瑕佷笓涓氫弗璋ㄣ€侀€昏緫閾炬潯娓呮櫚銆佹湳璇噯纭紝浣嗛伩鍏嶇┖娉涘爢鐮屻€?"
    chart_text = _ziwei_chart_to_text(chart)

    recent = []
    for m in (conversation or [])[-8:]:
        if not isinstance(m, dict):
            continue
        r = (m.get("role") or "").strip()
        c = (m.get("content") or "").strip()
        if r and c:
            recent.append(f"{r}: {c}")
    recent_text = "\n".join(recent).strip()
    mem_block = f"\n\n--- 鍏变韩璁板繂 / 鍘嗗彶鎽樿 ---\n{(shared_memory_context or '').strip()}" if shared_memory_context else ""

    return (
        f"{role_desc}\n"
        f"{tone}\n\n"
        f"--- 绱井鍛界洏鎽樿 ---\n{chart_text}\n\n"
        f"--- 杩戞湡瀵硅瘽锛堣嫢鏈夛級 ---\n{recent_text or '鏃?'}\n\n"
        f"--- 鐢ㄦ埛闂 ---\n{q}\n"
        f"{mem_block}\n\n"
        f"璇风粨鍚堝懡鐩樹俊鎭笌鐢ㄦ埛闂杩涜鍥炵瓟锛歕n"
        f"- 鍏堢粰缁撹瑕佺偣锛屽啀缁欎緷鎹笌鎺ㄦ紨\n"
        f"- 鏈€鍚庣粰 2-5 鏉″彲鎵ц寤鸿锛堝鏋滈€傜敤锛塡n"
        f"- 杈撳嚭鐢ㄤ腑鏂囷紝閬垮厤鏆撮湶鍐呴儴瀛楁鍚峔n"
    ).strip()


@app.route('/api/ziwei/chat/history', methods=['GET'])
@login_required
def ziwei_chat_history():
    user_id = session.get('user_id')
    data = load_from_local_file(get_user_ziwei_chat_file(user_id))
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list):
        messages = []
    return jsonify({"success": True, "messages": messages[-100:]})


@app.route('/api/ziwei/chat/send', methods=['POST'])
@login_required
def ziwei_chat_send():
    try:
        user_id = session.get('user_id')
        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()
        style = (body.get("style") or "professional").strip()
        chart = body.get("chart")
        if not message:
            return jsonify({"success": False, "error": "缂哄皯娑堟伅鍐呭"}), 400
        if not isinstance(chart, (dict,)):
            return jsonify({"success": False, "error": "缂哄皯鍛界洏鏁版嵁锛岃鍏堢敓鎴愬懡鐩?"}), 400

        chat_file = get_user_ziwei_chat_file(user_id)
        chat_data = load_from_local_file(chat_file)
        if not isinstance(chat_data, dict):
            chat_data = {}
        messages = chat_data.get("messages")
        if not isinstance(messages, list):
            messages = []

        user_msg = {"role": "user", "content": message, "timestamp": datetime.now().isoformat()}
        messages.append(user_msg)

        shared_context = ""
        try:
            shared_context = bazi_memory_manager.build_shared_memory_context(user_id=user_id, dimension="紫微斗数", query=message)
        except Exception:
            shared_context = ""

        prompt = _build_ziwei_chat_prompt(
            user_question=message,
            chart=chart,
            conversation=messages,
            shared_memory_context=shared_context,
            style=style,
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(ai_analyzer.analyze_with_deepseek(prompt, model_name=get_deepseek_dialog_model()))
        finally:
            try:
                loop.close()
            except Exception:
                pass

        assistant_text = result.content if hasattr(result, "content") else str(result)
        assistant_msg = {"role": "assistant", "content": assistant_text, "timestamp": datetime.now().isoformat()}
        messages.append(assistant_msg)

        chat_data["messages"] = messages[-300:]
        chat_data["updated_at"] = datetime.now().isoformat()
        save_to_local_file(chat_file, chat_data)

        memory_status = _memory_status_for_event(user_id)
        try:
            event_id = bazi_memory_manager.append_raw_event(
                user_id=user_id,
                event_type="ziwei_chat",
                dimension="紫微斗数",
                version=style,
                content=f"User: {message}\nAssistant: {assistant_text}".strip(),
                model_used=get_deepseek_dialog_model(),
                user_background={"user_id": user_id, "username": session.get("username")},
                importance=5,
                extra={"source": "ziwei_chat"},
            )
            if memory_organizer:
                memory_organizer.notify(user_id)
            memory_status = _memory_status_for_event(user_id, event_id)
        except Exception:
            pass

        return jsonify({"success": True, "reply": assistant_text, "messages": messages[-50:], "memory_status": memory_status})
    except Exception as e:
        logger.error(f"绱井瀵硅瘽澶辫触: {e}", exc_info=True)
        return jsonify({"success": False, "error": "绱井瀵硅瘽澶辫触锛岃閲嶈瘯"}), 500

def _build_liuyao_chat_prompt(gua_info, conversation_history, user_question, style, shared_context=""):
    style_instruction = "请用通俗易懂的语言解释，避免过多专业术语。" if style == "interpretation" else "请用专业术语进行分析，保持严谨。"
    gua_text = json.dumps(gua_info, ensure_ascii=False, indent=2) if isinstance(gua_info, dict) else str(gua_info)
    history_text = ""
    for msg in conversation_history[-10:]:
        role_label = "用户" if msg.get("role") == "user" else "AI"
        history_text += f"{role_label}: {msg.get('content', '')}\n"
    memory_text = f"\n【用户背景信息】\n{shared_context}" if shared_context else ""
    return f"""你是一位专业的六爻占卜师，精通六爻八卦和易经卦象解析。请根据用户的卦象和提问进行解答。

【风格要求】
{style_instruction}

【用户卦象信息】
{gua_text}

【历史对话】
{history_text}

【用户提问】
{user_question}
{memory_text}

请给出专业、详细的解答。"""

def _build_qimen_chat_prompt(chart_info, conversation_history, user_question, style, shared_context=""):
    style_instruction = "请用通俗易懂的语言解释，避免过多专业术语。" if style == "interpretation" else "请用专业术语进行分析，保持严谨。"
    chart_text = json.dumps(chart_info, ensure_ascii=False, indent=2) if isinstance(chart_info, dict) else str(chart_info)
    history_text = ""
    for msg in conversation_history[-10:]:
        role_label = "用户" if msg.get("role") == "user" else "AI"
        history_text += f"{role_label}: {msg.get('content', '')}\n"
    memory_text = f"\n【用户背景信息】\n{shared_context}" if shared_context else ""
    return f"""你是一位专业的奇门遁甲师，精通奇门盘面和方位解析。请根据用户盘面和提问进行解答。

【风格要求】
{style_instruction}

【用户盘面信息】
{chart_text}

【历史对话】
{history_text}

【用户提问】
{user_question}
{memory_text}

请给出专业、详细的解答。"""

@app.route('/api/liuyao/chat/send', methods=['POST'])
def api_liuyao_chat_send():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "鏈櫥褰?"}), 401
    
    user_id = session['user_id']
    data = request.json
    message = data.get('message', '')
    gua = data.get('gua', {})
    style = data.get('style', 'professional')

    if not message:
        return jsonify({"success": False, "error": "娑堟伅涓嶈兘涓虹┖"}), 400

    chat_file = get_user_liuyao_chat_file(user_id)
    chat_history = load_from_local_file(chat_file)
    if not isinstance(chat_history, list):
        chat_history = []

    chat_history.append({"role": "user", "content": message, "timestamp": datetime.now().isoformat()})

    shared_context = bazi_memory_manager.build_shared_memory_context(user_id, dimension="六爻占卜", query=message)
    
    prompt = _build_liuyao_chat_prompt(
        gua_info=gua,
        conversation_history=chat_history,
        user_question=message,
        style=style,
        shared_context=shared_context
    )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(ai_analyzer.analyze_with_deepseek(prompt, model_name=get_deepseek_dialog_model()))
        finally:
            try:
                loop.close()
            except Exception:
                pass

        assistant_text = result.content if hasattr(result, "content") else str(result)
        
        chat_history.append({"role": "assistant", "content": assistant_text, "timestamp": datetime.now().isoformat()})
        save_to_local_file(chat_file, chat_history)

        memory_status = _memory_status_for_event(user_id)
        try:
            event_id = bazi_memory_manager.append_raw_event(
                user_id=user_id,
                event_type="liuyao_chat",
                dimension="六爻占卜",
                version=style,
                content=f"User: {message}\nAssistant: {assistant_text}".strip(),
                model_used=get_deepseek_dialog_model(),
                user_background={"user_id": user_id, "username": session.get("username")},
                importance=5,
                extra={"source": "liuyao_chat"},
            )
            if memory_organizer:
                memory_organizer.notify(user_id)
            memory_status = _memory_status_for_event(user_id, event_id)
        except Exception:
            pass

        return jsonify({"success": True, "reply": assistant_text, "memory_status": memory_status})
    except Exception as e:
        logger.error(f"鍏埢瀵硅瘽澶辫触: {e}", exc_info=True)
        return jsonify({"success": False, "error": "鍏埢瀵硅瘽澶辫触锛岃閲嶈瘯"}), 500

@app.route('/api/liuyao/chat/history', methods=['GET'])
def api_liuyao_chat_history():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "鏈櫥褰?"}), 401
    
    user_id = session['user_id']
    chat_file = get_user_liuyao_chat_file(user_id)
    chat_history = load_from_local_file(chat_file)
    if not isinstance(chat_history, list):
        chat_history = []
    return jsonify({"success": True, "history": chat_history})

@app.route('/api/qimen/chat/send', methods=['POST'])
def api_qimen_chat_send():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "鏈櫥褰?"}), 401
    
    user_id = session['user_id']
    data = request.json
    message = data.get('message', '')
    chart = data.get('chart', {})
    style = data.get('style', 'professional')

    if not message:
        return jsonify({"success": False, "error": "娑堟伅涓嶈兘涓虹┖"}), 400

    chat_file = get_user_qimen_chat_file(user_id)
    chat_history = load_from_local_file(chat_file)
    if not isinstance(chat_history, list):
        chat_history = []

    chat_history.append({"role": "user", "content": message, "timestamp": datetime.now().isoformat()})

    shared_context = bazi_memory_manager.build_shared_memory_context(user_id, dimension="奇门遁甲", query=message)
    
    prompt = _build_qimen_chat_prompt(
        chart_info=chart,
        conversation_history=chat_history,
        user_question=message,
        style=style,
        shared_context=shared_context
    )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(ai_analyzer.analyze_with_deepseek(prompt, model_name=get_deepseek_dialog_model()))
        finally:
            try:
                loop.close()
            except Exception:
                pass

        assistant_text = result.content if hasattr(result, "content") else str(result)
        
        chat_history.append({"role": "assistant", "content": assistant_text, "timestamp": datetime.now().isoformat()})
        save_to_local_file(chat_file, chat_history)

        memory_status = _memory_status_for_event(user_id)
        try:
            event_id = bazi_memory_manager.append_raw_event(
                user_id=user_id,
                event_type="qimen_chat",
                dimension="奇门遁甲",
                version=style,
                content=f"User: {message}\nAssistant: {assistant_text}".strip(),
                model_used=get_deepseek_dialog_model(),
                user_background={"user_id": user_id, "username": session.get("username")},
                importance=5,
                extra={"source": "qimen_chat"},
            )
            if memory_organizer:
                memory_organizer.notify(user_id)
            memory_status = _memory_status_for_event(user_id, event_id)
        except Exception:
            pass

        return jsonify({"success": True, "reply": assistant_text, "memory_status": memory_status})
    except Exception as e:
        logger.error(f"濂囬棬瀵硅瘽澶辫触: {e}", exc_info=True)
        return jsonify({"success": False, "error": "濂囬棬瀵硅瘽澶辫触锛岃閲嶈瘯"}), 500

@app.route('/api/qimen/chat/history', methods=['GET'])
def api_qimen_chat_history():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "鏈櫥褰?"}), 401
    
    user_id = session['user_id']
    chat_file = get_user_qimen_chat_file(user_id)
    chat_history = load_from_local_file(chat_file)
    if not isinstance(chat_history, list):
        chat_history = []
    return jsonify({"success": True, "history": chat_history})

@app.route('/api/status', methods=['GET'])
def get_status():
    """鑾峰彇绯荤粺鐘舵€?"""
    # 妫€鏌ユ槸鍚︽湁鐢ㄦ埛鐧诲綍
    is_logged_in = 'user_id' in session
    current_user = None
    if is_logged_in:
        current_user = {
            "user_id": session.get('user_id'),
            "username": session.get('username'),
            "login_time": session.get('login_time')
        }
    
    return jsonify({
        "status": "running",
        "timestamp": time.time(),
        "memory_backend": "local_json",
        "vector_memory_enabled": bool(getattr(bazi_memory_manager, "vector_memory", None)),
        "loaded_users": user_manager.get_user_count(),
        "current_session": {
            "logged_in": is_logged_in,
            "user": current_user
        }
    })

def _normalize_eight_char_provider_sect(data: Dict[str, Any]) -> int:
    raw = data.get("eightCharProviderSect", data.get("earlyZiTimeRule", 2))
    try:
        value = int(raw)
    except Exception:
        value = 2
    return value if value in (1, 2) else 2

def _ensure_seconds(time_part: str) -> str:
    value = str(time_part or "").strip() or "12:00"
    if "T" in value:
        return value
    if value.count(":") == 1:
        return f"{value}:00"
    return value

def _build_bazi_calculation_args(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("缂哄皯璇锋眰鏁版嵁")

    calendar_type = str(data.get("calendar_type") or "").strip().lower()
    solar_datetime = str(data.get("solarDatetime") or "").strip()
    lunar_datetime = str(data.get("lunarDatetime") or "").strip()
    birth_time_value = str(data.get("birth_time") or "").strip()
    birth_date = str(data.get("birth_date") or "").strip()
    lunar_is_leap_month = _normalize_boolish(
        data.get("lunar_is_leap_month")
        if "lunar_is_leap_month" in data
        else data.get("lunarIsLeapMonth")
    )

    input_type = None
    actual_birth_time = None
    arguments: Dict[str, Any] = {}

    if solar_datetime:
        input_type = "solar"
        actual_birth_time = solar_datetime
        arguments["solarDatetime"] = solar_datetime
    elif lunar_datetime:
        input_type = "lunar"
        actual_birth_time = lunar_datetime
        arguments["lunarDatetime"] = lunar_datetime
    elif birth_time_value and "T" in birth_time_value:
        input_type = "solar"
        actual_birth_time = birth_time_value
        arguments["solarDatetime"] = birth_time_value
    elif birth_date:
        time_part = _ensure_seconds(birth_time_value or "12:00")
        if calendar_type == "lunar":
            input_type = "lunar"
            actual_birth_time = f"{birth_date} {time_part}"
            arguments["lunarDatetime"] = actual_birth_time
        else:
            input_type = "solar"
            actual_birth_time = f"{birth_date}T{time_part}+08:00"
            arguments["solarDatetime"] = actual_birth_time
    elif birth_time_value:
        actual_birth_time = birth_time_value

    if not actual_birth_time or not input_type:
        raise ValueError("缂哄皯鍑虹敓鏃堕棿")
    if input_type == "solar" and (actual_birth_time.count("T") != 1 or actual_birth_time.count(":") < 2):
        raise ValueError(f"鏃堕棿鏍煎紡鏃犳晥: {actual_birth_time}")
    if input_type == "lunar" and actual_birth_time.count(":") < 2:
        raise ValueError(f"鍐滃巻鏃堕棿鏍煎紡鏃犳晥: {actual_birth_time}")

    gender_int = _normalize_gender_value(data.get("gender", 1))
    if gender_int is None:
        gender_int = 1
    arguments["gender"] = gender_int
    arguments["eightCharProviderSect"] = _normalize_eight_char_provider_sect(data)
    if input_type == "lunar" and lunar_is_leap_month:
        arguments["lunarIsLeapMonth"] = True

    return {
        "arguments": arguments,
        "actual_birth_time": actual_birth_time,
        "input_type": input_type,
        "gender": gender_int,
        "calendar_type": "lunar" if input_type == "lunar" else (calendar_type or "solar"),
        "birth_date": birth_date or _extract_birth_date_from_iso(actual_birth_time) or (actual_birth_time.split(" ", 1)[0] if input_type == "lunar" else ""),
        "lunar_is_leap_month": input_type == "lunar" and lunar_is_leap_month,
    }

async def _calculate_bazi_mcp_async(arguments: Dict[str, Any]) -> Dict[str, Any]:
    global bazi_client
    if not bazi_client:
        bazi_client = BaziClient()
    return await bazi_client.get_bazi_detail(arguments)

def _run_bazi_mcp(arguments: Dict[str, Any]) -> Dict[str, Any]:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_calculate_bazi_mcp_async(arguments))
    finally:
        try:
            loop.close()
        except Exception:
            pass

def _calculate_bazi_with_provider(arguments: Dict[str, Any]) -> Dict[str, Any]:
    requested_provider = str(os.getenv("BAZI_CALC_PROVIDER", "auto")).strip().lower() or "auto"
    if requested_provider not in ("auto", "local", "mcp"):
        requested_provider = "auto"

    started = time.perf_counter()
    fallback_reason = None

    if requested_provider in ("auto", "local"):
        try:
            result = calculate_bazi_local(arguments)
            return {
                "result": result,
                "provider": "local",
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "fallback_reason": None,
            }
        except LocalBaziError as e:
            fallback_reason = str(e)
            if requested_provider == "local":
                raise
            logger.warning(f"[BaziProvider] local provider failed, falling back to mcp: {fallback_reason}")

    result = _run_bazi_mcp(arguments)
    return {
        "result": result,
        "provider": "mcp",
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "fallback_reason": fallback_reason,
    }

def _handle_bazi_get_request():
    data = request.get_json(silent=True) or {}
    name = data.get('name', '鍖垮悕鐢ㄦ埛')
    location = data.get('location', {})

    try:
        request_info = _build_bazi_calculation_args(data)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    actual_birth_time = request_info["actual_birth_time"]
    birth_time = actual_birth_time
    gender_int = request_info["gender"]
    calendar_type = request_info["calendar_type"]
    birth_date = request_info["birth_date"]

    try:
        provider_payload = _calculate_bazi_with_provider(request_info["arguments"])
    except Exception as e:
        logger.error(f"[BaziAPI] calculation failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"鑾峰彇鍏瓧淇℃伅澶辫触: {str(e)}"}), 500

    bazi_result = provider_payload["result"]
    bazi_provider = provider_payload["provider"]
    bazi_duration_ms = provider_payload["duration_ms"]
    fallback_reason = provider_payload["fallback_reason"]

    if not bazi_result or not isinstance(bazi_result, dict):
        return jsonify({"success": False, "error": "鍏瓧鏁版嵁鏍煎紡鏃犳晥"}), 500

    logger.info(
        "[BaziAPI] ok provider=%s duration_ms=%s input=%s name=%s",
        bazi_provider,
        bazi_duration_ms,
        request_info["input_type"],
        name,
    )

    user_id = session.get('user_id') if 'user_id' in session else resolve_or_create_user_id_by_chart(
        name=name,
        gender=gender_int,
        birth_time_iso=birth_time,
        calendar_type=calendar_type,
        birth_date=birth_date,
        lunar_is_leap_month=request_info["lunar_is_leap_month"],
    )
    if 'user_id' not in session:
        session['user_id'] = user_id
        session['username'] = name
        session['login_time'] = datetime.now().isoformat()
    _bind_current_account_to_user(user_id)

    user_data = {
        "user_info": {
            "name": name,
            "gender": gender_int,
            "birth_time": birth_time,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "solar_time_applied": data.get("solar_time_applied", False),
            "true_solar_time": data.get("birth_time") if data.get("solar_time_applied") else None,
            "longitude": data.get("longitude"),
            "calendar_type": calendar_type,
            "birth_date": birth_date,
            "input_type": request_info["input_type"],
            "lunar_is_leap_month": request_info["lunar_is_leap_month"],
        },
        "bazi_info": bazi_result,
        "bazi_provider": bazi_provider,
        "bazi_duration_ms": bazi_duration_ms,
        "bazi_fallback_reason": fallback_reason,
        "timestamp": datetime.now().isoformat(),
    }
    chart_invalidation = _handle_chart_change_if_needed(
        user_id,
        user_data,
        reason="bazi_birth_profile_changed",
    )
    user_data["chart_invalidation"] = chart_invalidation

    if user_data["user_info"]["solar_time_applied"]:
        user_data["user_info"]["display_birth_time"] = user_data["user_info"]["true_solar_time"]
        user_data["user_info"]["is_true_solar_time"] = True
        user_data["user_info"]["original_birth_time"] = user_data["user_info"]["birth_time"]
    _sync_user_birth_metadata(user_id, user_data["user_info"])
    _sync_profile_doc_to_chart(user_id, user_data["user_info"], reset_tags=bool(chart_invalidation.get("changed")))

    bazi_file = get_user_bazi_file(user_id)
    if not save_to_local_file(bazi_file, user_data):
        logger.warning(f"[BaziAPI] failed to save bazi file: {bazi_file}")

    try:
        bazi_memory_manager.update_chart_facts_from_bazi_payload(
            user_id=user_id,
            user_info=user_data["user_info"],
            bazi_info=bazi_result,
            raw_file_path=bazi_file,
            parsed_time=bazi_result.get("parsed_time") if isinstance(bazi_result, dict) else None,
        )
    except Exception as e:
        logger.warning(f"[BaziAPI] failed to update chart facts: {e}")

    minimal = False
    try:
        minimal = str(request.args.get("minimal") or data.get("minimal") or "").strip().lower() in ("1", "true", "yes", "y", "on")
    except Exception:
        minimal = False

    response_data = {
        "success": True,
        "data": {
            "user_info": user_data["user_info"],
            "saved_locally": True,
            "bazi_provider": bazi_provider,
            "bazi_duration_ms": bazi_duration_ms,
            "bazi_fallback_reason": fallback_reason,
            "chart_signature": user_data.get("chart_signature"),
            "chart_invalidation": chart_invalidation,
        },
    }
    if not minimal:
        response_data["data"]["bazi_info"] = bazi_result

    return jsonify(response_data)

@app.route('/api/bazi/get', methods=['POST'])
def get_bazi_info():
    """鑾峰彇鍏瓧淇℃伅"""
    logger.debug("get_bazi_info start")
    try:
        return _handle_bazi_get_request()
        data = request.get_json()
        logger.debug("legacy get_bazi_info path called")
        logger.info(f"馃幆 [鍏瓧API] 鏀跺埌璇锋眰鏁版嵁: {data}")
        
        # 鏀寔澶氱鍙傛暟鏍煎紡
        birth_time = None
        if 'birth_time' in data:
            birth_time = data.get('birth_time')
        elif 'solarDatetime' in data:
            birth_time = data.get('solarDatetime')
        elif 'lunarDatetime' in data:
            birth_time = data.get('lunarDatetime')
        elif 'birth_date' in data:
            # 鍓嶇鐧诲綍鐣岄潰鐨勬牸寮忥細birth_date + birth_time
            birth_date = data.get('birth_date')  # YYYY-MM-DD
            birth_time_part = data.get('birth_time', '12:00')  # HH:MM锛岄粯璁や腑鍗?2鐐?
            calendar_type = data.get('calendar_type', 'solar')
            
            # 缁勫悎鎴愬畬鏁寸殑鏃ユ湡鏃堕棿
            if birth_time_part:
                birth_time = f"{birth_date}T{birth_time_part}:00+08:00"  # ISO鏍煎紡
            else:
                birth_time = f"{birth_date}T12:00:00+08:00"  # 榛樿鏃堕棿
            
            logger.info(f"馃攧 [鏁版嵁杞崲] 鍓嶇鏍煎紡杞崲:")
            logger.info(f"   鍘熷鏃ユ湡: {birth_date}")
            logger.info(f"   鍘熷鏃堕棿: {birth_time_part}")
            logger.info(f"   鍘嗘硶绫诲瀷: {calendar_type}")
            logger.info(f"   杞崲鍚? {birth_time}")
        
        gender = data.get('gender', 1)
        gender_int = _normalize_gender_value(gender)
        name = data.get('name', '鍖垮悕鐢ㄦ埛')
        location = data.get('location', {})  # 鎻愬彇location
        
        logger.info(f"馃搵 [鍏瓧API] 瑙ｆ瀽鍚庣殑鍙傛暟:")
        logger.info(f"   - 濮撳悕: {name}")
        logger.info(f"   - 鎬у埆: {('男' if gender_int == 1 else '女')} ({gender_int})")
        logger.info(f"   - 鍑虹敓鏃堕棿: {birth_time}")
        logger.info(f"   - 鍘嗘硶绫诲瀷: {data.get('calendar_type', 'unknown')}")
        
        if not birth_time:
            logger.error(f"鉂?[鍏瓧API] 缂哄皯鍑虹敓鏃堕棿鍙傛暟")
            return jsonify({"success": False, "error": "缂哄皯鍑虹敓鏃堕棿"})
        
        # 楠岃瘉鏃堕棿鏍煎紡锛岀‘淇濇槸瀹屾暣鐨処SO鏍煎紡
        if not birth_time.count('T') == 1 or not birth_time.count(':') >= 2:
            logger.error(f"鉂?[鍏瓧API] 鏃堕棿鏍煎紡鏃犳晥: {birth_time}")
            return jsonify({"success": False, "error": f"鏃堕棿鏍煎紡鏃犳晥: {birth_time}"})
        
        # 浣跨敤寮傛鏂瑰紡鑾峰彇鍏瓧淇℃伅
        async def get_bazi_async():
            global bazi_client
            if not bazi_client:
                logger.info(f"馃攲 [MCP瀹㈡埛绔痌 鍒濆鍖栧叓瀛楀鎴风...")
                bazi_client = BaziClient()
                await bazi_client.connect()
                logger.info(f"鉁?[MCP瀹㈡埛绔痌 杩炴帴鎴愬姛")
            
            # 浣跨敤鐪熷お闃虫椂淇鍚庣殑鏃堕棿
            # data 鏄姹備綋锛屽寘鍚簡鍙兘鐨勭湡澶槼鏃朵慨姝?
            actual_birth_time = data.get("birth_time", birth_time)
            
            logger.info(f"馃摗 [MCP璇锋眰] 鍙戦€佸叓瀛楄绠楄姹?")
            logger.info(f"   馃搮 鍘熷鏃堕棿: {birth_time}")
            logger.info(f"   馃尀 鏈€缁堜娇鐢? {actual_birth_time}")
            logger.info(f"   馃懁 鎬у埆: {('男' if gender == 1 else '女')} ({gender})")
            logger.info(f"   馃摑 濮撳悕: {name}")
            
            # 楠岃瘉鏃堕棿鏍煎紡
            if not actual_birth_time or actual_birth_time == '12:00':
                logger.error(f"鉂?[MCP瀹㈡埛绔痌 鏃堕棿鏍煎紡鏃犳晥: {actual_birth_time}")
                raise ValueError(f"鏃堕棿鏍煎紡鏃犳晥: {actual_birth_time}")
            
            if actual_birth_time != birth_time:
                 logger.info(f"鈿狅笍 [MCP璇锋眰] 娉ㄦ剰锛氫娇鐢ㄤ簡淇鍚庣殑鐪熷お闃虫椂 (鍘熸椂闂? {birth_time})")

            result = await bazi_client.get_bazi_details(actual_birth_time, gender)
            logger.info(f"馃摠 [MCP鍝嶅簲] 鏀跺埌鍏瓧鏁版嵁:")
            logger.info(f"   馃梻锔?鏁版嵁绫诲瀷: {type(result)}")
            
            # 璇︾粏璋冭瘯淇℃伅
            if isinstance(result, dict):
                logger.debug("MCP returned birth_time=%s", result.get('birth_time'))
                logger.debug("MCP returned four_pillars=%s", result.get('four_pillars'))
                if 'raw_data' in result:
                    raw = result['raw_data']
                    logger.debug("MCP raw bazi=%s", raw.get('鍏瓧') if isinstance(raw, dict) else 'N/A')
                    logger.debug("MCP raw birth_time=%s", raw.get('birth_time') if isinstance(raw, dict) else 'N/A')
            
            logger.info(f"   馃搹 鏁版嵁澶у皬: {len(str(result)) if result else 0} 瀛楃")
            if result:
                logger.info(f"   馃幆 鍖呭惈瀛楁: {list(result.keys()) if isinstance(result, dict) else 'not_dict'}")
            
            return result
        
        # 鑾峰彇鍏瓧鏁版嵁
        try:
            logger.info(f"鈿欙笍 [寮傛澶勭悊] 鍚姩浜嬩欢寰幆鑾峰彇鍏瓧鏁版嵁...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            bazi_result = loop.run_until_complete(get_bazi_async())
            loop.close()
            logger.info(f"鉁?[寮傛澶勭悊] 浜嬩欢寰幆瀹屾垚")
            
            if not bazi_result or not isinstance(bazi_result, dict):
                logger.error(f"鉂?[鏁版嵁楠岃瘉] 鍏瓧鏁版嵁鏍煎紡鏃犳晥: {type(bazi_result)}")
                raise ValueError("鍏瓧鏁版嵁鏍煎紡鏃犳晥")
            
            logger.info(f"馃帀 [鍏瓧鏁版嵁] 鎴愬姛鑾峰彇鏈夋晥鍏瓧淇℃伅:")
            if isinstance(bazi_result, dict):
                for key, value in bazi_result.items():
                    if key == 'baziFourPillars':
                        logger.info(f"   馃彌锔?鍥涙煴淇℃伅: {value}")
                    elif key == 'lunarDateTime':
                        logger.info(f"   馃寵 鍐滃巻鏃堕棿: {value}")
                    elif key == 'solarDateTime':
                        logger.info(f"   鈽€锔?闃冲巻鏃堕棿: {value}")
                    else:
                        logger.info(f"   馃搫 {key}: {str(value)[:100]}{'...' if len(str(value)) > 100 else ''}")
                
        except Exception as e:
            logger.error(f"鉂?[MCP瀹㈡埛绔痌 鑾峰彇鍏瓧澶辫触: {str(e)}")
            logger.error(f"   閿欒绫诲瀷: {type(e).__name__}")
            return jsonify({
                "success": False, 
                "error": f"鑾峰彇鍏瓧淇℃伅澶辫触: {str(e)}"
            }), 500
        
        # 淇濆瓨鍏瓧淇℃伅鍒版湰鍦版枃浠?
        # 灏濊瘯浠庝細璇濊幏鍙栫敤鎴稩D锛屽鏋滄病鏈夊垯鍒涘缓鏂扮殑
        calendar_type = data.get('calendar_type', 'solar')
        birth_date = data.get('birth_date') or _extract_birth_date_from_iso(birth_time)
        user_id = session.get('user_id') if 'user_id' in session else resolve_or_create_user_id_by_chart(
            name=name,
            gender=gender_int,
            birth_time_iso=birth_time,
            calendar_type=calendar_type,
            birth_date=birth_date,
        )
        if 'user_id' not in session:
            session['user_id'] = user_id
            session['username'] = name
            session['login_time'] = datetime.now().isoformat()
        _bind_current_account_to_user(user_id)
        
        user_data = {
            "user_info": {
                "name": name,
                "gender": gender_int if gender_int is not None else gender,
                "birth_time": birth_time,
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
                "solar_time_applied": data.get("solar_time_applied", False),
                "true_solar_time": data.get("birth_time") if data.get("solar_time_applied") else None,
                "longitude": data.get("longitude")
            },
            "bazi_info": bazi_result,
            "timestamp": datetime.now().isoformat()
        }
        
        # 淇杩斿洖缁欏墠绔殑 birth_time锛岀‘淇?AI 鍒嗘瀽浣跨敤鐪熷お闃虫椂
        if user_data["user_info"]["solar_time_applied"]:
            user_data["user_info"]["display_birth_time"] = user_data["user_info"]["true_solar_time"]
            user_data["user_info"]["is_true_solar_time"] = True
            user_data["user_info"]["original_birth_time"] = user_data["user_info"]["birth_time"]
            # 鍏抽敭锛氭洿鏂?user_background 涓殑 birth_time锛岃繖浼氳鍓嶇浼犲洖鐢ㄤ簬 AI 鍒嗘瀽
            # 鍓嶇閫氬父浣跨敤杩斿洖鐨?userInfo 浣滀负 user_background
            # 浣嗚娉ㄦ剰鍓嶇 analysis.html 鏄浣曟瀯寤?user_background 鐨?
        
        logger.info(f"馃捑 [鏈湴瀛樺偍] 鍑嗗淇濆瓨鐢ㄦ埛鍏瓧鏁版嵁:")
        logger.info(f"   馃懁 鐢ㄦ埛ID: {user_id}")
        logger.info(f"   馃摑 鐢ㄦ埛濮撳悕: {name}")
        logger.info(f"   馃搮 鍑虹敓鏃堕棿: {birth_time}")
        
        bazi_file = get_user_bazi_file(user_id)
        logger.info(f"   馃搧 淇濆瓨璺緞: {bazi_file}")
        
        if save_to_local_file(bazi_file, user_data):
            logger.info(f"鉁?[鏈湴瀛樺偍] 鍏瓧淇℃伅宸叉垚鍔熶繚瀛樺埌鏈湴鏂囦欢")
        else:
            logger.warning(f"鈿狅笍 [鏈湴瀛樺偍] 淇濆瓨鍏瓧淇℃伅鍒版湰鍦版枃浠跺け璐?")

        try:
            chart_facts = bazi_memory_manager.update_chart_facts_from_bazi_payload(
                user_id=user_id,
                user_info=user_data["user_info"],
                bazi_info=bazi_result,
                raw_file_path=bazi_file,
                parsed_time=bazi_result.get("parsed_time") if isinstance(bazi_result, dict) else None,
            )
            if chart_facts:
                logger.info("鉁?[鍏变韩璁板繂] 鍛界洏浜嬪疄灞傚凡鐢熸垚骞跺啓鍏ワ紙鍚憳瑕佷笌鍚戦噺绱㈠紩锛?")
            else:
                logger.warning("鈿狅笍 [鍏变韩璁板繂] 鏈娴嬪埌raw_data锛屽懡鐩樹簨瀹炲眰鏈敓鎴?")
        except Exception as e:
            logger.warning(f"鈿狅笍 [鍏变韩璁板繂] 鍛界洏浜嬪疄灞傜敓鎴愬け璐? {e}")

        minimal = False
        try:
            minimal = str(request.args.get("minimal") or data.get("minimal") or "").strip().lower() in ("1", "true", "yes", "y", "on")
        except Exception:
            minimal = False

        response_data = {
            "success": True,
            "data": {
                "user_info": user_data["user_info"],
                "saved_locally": True,
            },
        }
        if not minimal:
            response_data["data"]["bazi_info"] = bazi_result
        
        logger.info(f"馃帄 [API鍝嶅簲] 鍏瓧鑾峰彇鎴愬姛锛岃繑鍥炵粰鍓嶇:")
        logger.info(f"   鉁?鎴愬姛鐘舵€? {response_data['success']}")
        logger.info(f"   馃懁 鐢ㄦ埛淇℃伅: {response_data['data']['user_info']['name']}")
        logger.info(f"   馃捑 鏈湴淇濆瓨: {response_data['data']['saved_locally']}")
        logger.info(f"   馃搳 鍏瓧鏁版嵁瀛楁: {list(response_data['data']['bazi_info'].keys()) if response_data['data']['bazi_info'] else 'N/A'}")
        
        return jsonify(response_data)
        
    except Exception as e:
        raise
    #     import traceback
    #     with open("error_traceback.log", "w") as f:
    #         traceback.print_exc(file=f)
    #     traceback.print_exc()
    #     print(f"DEBUG: get_bazi_info EXCEPTION: {e}", flush=True)
    #     logger.error(f"鉂?[鍏瓧API] 鑾峰彇鍏瓧淇℃伅閿欒: {str(e)}")
    #     logger.error(f"   閿欒绫诲瀷: {type(e).__name__}")
    #     return jsonify({"success": False, "error": str(e)})

@app.route('/api/analysis/batch', methods=['POST'])
def start_batch_analysis():
    """鎵归噺鍏瓧鍒嗘瀽鎺ュ彛 - 鏀寔寮傛骞惰澶勭悊"""
    try:
        data = request.json
        version = data.get('version', 'classic')
        dimensions = data.get('dimensions', [])  # 澶氫釜缁村害鍒楄〃
        bazi_info_dict = data.get('bazi_info')
        user_background = data.get('user_background', {})
        queued_memory_event_ids = []

        logger.info(f"馃殌 [寮傛鎵归噺鍒嗘瀽] 寮€濮嬪苟琛屽鐞?- 鐗堟湰: {version}, 缁村害鏁伴噺: {len(dimensions)}, 缁村害: {dimensions}")

        if not all([dimensions, bazi_info_dict]):
            return jsonify({"error": "Missing required parameters: dimensions, bazi_info"}), 400

        if len(dimensions) > 10:  # 闄愬埗鏈€澶?0涓淮搴?
            return jsonify({"error": "Too many dimensions, maximum 10 allowed"}), 400

        user_id = session.get('user_id')
        if not user_id:
            user_id = resolve_or_create_user_id_by_chart(
                name=user_background.get('name') or '鍖垮悕鐢ㄦ埛',
                gender=user_background.get('gender'),
                birth_time_iso=user_background.get('birth_time'),
                calendar_type=user_background.get('calendar_type'),
                birth_date=user_background.get('birth_date'),
            )
            session['user_id'] = user_id
            session['username'] = user_background.get('name') or session.get('username') or '鍖垮悕鐢ㄦ埛'
            session['login_time'] = session.get('login_time') or datetime.now().isoformat()
        _bind_current_account_to_user(user_id)
        chart_signature = _chart_signature_from_bazi_info(bazi_info_dict, user_background)
        
        # 妫€鏌eepSeek瀹㈡埛绔?
        if not ai_analyzer.deepseek_client:
            raise ConnectionError("DeepSeek瀹㈡埛绔湭鍒濆鍖栵紝璇锋鏌PI瀵嗛挜閰嶇疆銆?")
        
        # 浣跨敤寮傛鏂规硶骞惰澶勭悊鎵€鏈夌淮搴?
        async def process_single_dimension(dimension):
            """澶勭悊鍗曚釜缁村害鐨勫垎鏋?"""
            try:
                logger.info(f"鈿?[骞惰澶勭悊] 寮€濮嬪垎鏋愮淮搴? {dimension}")
                
                # 鏋勫缓涓撲笟鐗堝垎鏋愭彁绀鸿瘝锛屾壒閲忓垎鏋愪篃娉ㄥ叆璇ョ淮搴︾殑鍏变韩璁板繂
                shared_context = bazi_memory_manager.build_shared_memory_context(user_id=user_id, dimension=dimension)
                professional_prompt = prompt_builder.build_analysis_prompt(
                    style=AnalysisStyle.PROFESSIONAL,
                    dimension=dimension,
                    bazi_info=bazi_info_dict,
                    user_context=user_background,
                    shared_memory_context=shared_context
                )
                
                # 寮傛璋冪敤DeepSeek鍒嗘瀽
                analysis_options = get_deepseek_analysis_options()
                prof_result = await ai_analyzer.analyze_with_deepseek(
                    professional_prompt, 
                    model_name=analysis_options["model"],
                    temperature=analysis_options["temperature"],
                    max_tokens=analysis_options["max_tokens"],
                    timeout=analysis_options["timeout"],
                )
                
                prof_content = prof_result.content if hasattr(prof_result, 'content') else str(prof_result)
                
                # 鏋勫缓鍒嗘瀽缁撴灉
                analysis_id = f"batch-analysis-{uuid.uuid4()}"
                analysis_data = {
                    "analysis_id": analysis_id,
                    "version": version,
                    "dimension": dimension,
                    "content": prof_content,
                    "timestamp": datetime.now().isoformat(),
                    "analysis_stage": "professional_only" if version == 'classic' else "professional_completed",
                    "models_used": {
                        "professional_analysis": analysis_options["model"]
                    },
                    "bazi_info": bazi_info_dict,
                    "user_background": user_background,
                    "chart_signature": chart_signature,
                }
                
                logger.info(f"鉁?[骞惰澶勭悊] 缁村害 {dimension} 鍒嗘瀽瀹屾垚")
                
                return {
                    "dimension": dimension,
                    "success": True,
                    "analysis_id": analysis_id,
                    "analysis_data": analysis_data,
                    "content": prof_content,
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as e:
                logger.error(f"鉂?[骞惰澶勭悊] 缁村害 {dimension} 鍒嗘瀽澶辫触: {e}")
                return {
                    "dimension": dimension,
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }
        
        async def run_batch_analysis():
            """寮傛鎵归噺鍒嗘瀽涓诲嚱鏁?"""
            logger.info(f"馃敟 [寮傛寮曟搸] 鍚姩{len(dimensions)}涓苟琛屼换鍔?..")
            
            # 浣跨敤asyncio.gather骞惰鎵ц鎵€鏈夌淮搴﹀垎鏋?
            results = await asyncio.gather(
                *[process_single_dimension(dim) for dim in dimensions],
                return_exceptions=True
            )
            
            # 澶勭悊缁撴灉
            batch_results = []
            successful_count = 0
            failed_count = 0
            successful_analyses = []
            
            for result in results:
                if isinstance(result, Exception):
                    # 澶勭悊寮傚父鎯呭喌
                    batch_results.append({
                        "dimension": "unknown",
                        "success": False,
                        "error": str(result),
                        "timestamp": datetime.now().isoformat()
                    })
                    failed_count += 1
                elif result.get("success"):
                    # 鎴愬姛鐨勫垎鏋?
                    batch_results.append({
                        "dimension": result["dimension"],
                        "success": True,
                        "analysis_id": result["analysis_id"],
                        "content": result["content"],
                        "timestamp": result["timestamp"]
                    })
                    successful_analyses.append(result["analysis_data"])
                    successful_count += 1
                else:
                    # 澶辫触鐨勫垎鏋?
                    batch_results.append(result)
                    failed_count += 1
            
            # 鎵归噺淇濆瓨鎴愬姛鐨勫垎鏋愮粨鏋?
            if successful_analyses:
                user_analysis_file = get_user_analysis_file(user_id)
                if append_analysis_records(user_analysis_file, successful_analyses) is not None:
                    logger.info(f"馃捑 [鎵归噺淇濆瓨] 鎴愬姛淇濆瓨{len(successful_analyses)}涓垎鏋愮粨鏋?")
                else:
                    logger.warning("鈿狅笍 [鎵归噺淇濆瓨] 鍒嗘瀽缁撴灉鍘熷瓙杩藉姞澶辫触")

                for analysis_data in successful_analyses:
                    try:
                        dim = analysis_data.get("dimension", "")
                        content = analysis_data.get("content", "")
                        ver = analysis_data.get("version", version)
                        model_used = None
                        if isinstance(analysis_data.get("models_used"), dict):
                            model_used = analysis_data["models_used"].get("professional_analysis")
                        bazi_memory_manager.store_bazi_analysis(
                            user_id=user_id,
                            dimension=dim,
                            analysis_content=content,
                            analysis_version=ver,
                            bazi_info=bazi_info_dict,
                            user_background=user_background,
                            model_used=model_used,
                            importance=8,
                            expires_in_days=365,
                        )
                        event_id = bazi_memory_manager.append_raw_event(
                            user_id=user_id,
                            event_type="analysis",
                            dimension=dim,
                            version=ver,
                            content=content,
                            model_used=model_used,
                            user_background=user_background,
                            importance=8,
                            extra={"source": "batch"},
                        )
                        queued_memory_event_ids.append(event_id)
                        if memory_organizer:
                            memory_organizer.notify(user_id)
                    except Exception as e:
                        logger.warning(f"鈿狅笍 [鍏变韩璁板繂] 鎵归噺鍐欏叆缁村害璁板繂澶辫触: {e}")
            
            return batch_results, successful_count, failed_count
        
        # 杩愯寮傛鎵归噺鍒嗘瀽
        logger.info(f"鈿?[寮傛鍚姩] 寮€濮嬪苟琛屽垎鏋愶紝棰勮鏁堢巼鎻愬崌{len(dimensions)}鍊?")
        start_time = datetime.now()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            batch_results, successful_count, failed_count = loop.run_until_complete(run_batch_analysis())
        finally:
            loop.close()
            
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        logger.info(f"馃帀 [寮傛瀹屾垚] 骞惰鎵归噺鍒嗘瀽瀹屾垚 - 鑰楁椂: {processing_time:.2f}s, 鎴愬姛: {successful_count}, 澶辫触: {failed_count}")

        return jsonify({
            "success": True,
            "batch_id": f"async-batch-{uuid.uuid4()}",
            "version": version,
            "total_dimensions": len(dimensions),
            "successful_count": successful_count,
            "failed_count": failed_count,
            "results": batch_results,
            "processing_time": processing_time,
            "parallel_processing": True,
            "timestamp": datetime.now().isoformat(),
            "memory_status": _memory_status_for_event(
                user_id,
                queued_memory_event_ids[-1] if queued_memory_event_ids else None,
            ),
            "memory_event_ids": queued_memory_event_ids,
        })

    except Exception as e:
        logger.error(f"鉂?[寮傛鎵归噺鍒嗘瀽] 鎺ュ彛閿欒: {e}")
        return jsonify({
            "error": f"寮傛鎵归噺鍒嗘瀽澶辫触: {str(e)}",
            "error_type": "async_batch_analysis_error",
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/analysis/start', methods=['POST'])
def start_bazi_analysis():
    """鍏瓧鍒嗘瀽鐨勬牳蹇冨叆鍙ｇ偣"""
    try:
        data = request.json
        version = data.get('version', 'classic')  # 'classic', 'wisdom', 'master'
        dimension = data.get('dimension')
        bazi_info_dict = data.get('bazi_info')
        user_background = data.get('user_background', {})

        logger.info(f"寮€濮嬪叓瀛楀垎鏋?- 鐗堟湰: {version}, 缁村害: {dimension}")

        if not dimension:
            return jsonify({"error": "Missing required parameters: dimension"}), 400

        user_id = session.get('user_id')
        if not user_id:
            user_id = resolve_or_create_user_id_by_chart(
                name=user_background.get('name') or '鍖垮悕鐢ㄦ埛',
                gender=user_background.get('gender'),
                birth_time_iso=user_background.get('birth_time'),
                calendar_type=user_background.get('calendar_type'),
                birth_date=user_background.get('birth_date'),
            )
            session['user_id'] = user_id
            session['username'] = user_background.get('name') or session.get('username') or '鍖垮悕鐢ㄦ埛'
            session['login_time'] = session.get('login_time') or datetime.now().isoformat()
        _bind_current_account_to_user(user_id)
        if not bazi_info_dict:
            bazi_info_dict = load_user_bazi_info(user_id)
        if not bazi_info_dict:
            return jsonify({"error": "Missing required parameters: bazi_info"}), 400
        chart_signature = _chart_signature_from_bazi_info(bazi_info_dict, user_background)
        try:
            bazi_memory_manager.update_profile(
                user_id=user_id,
                background=user_background or {},
                preferences={},
                add_tags=[dimension, "鍒嗘瀽"],
            )
        except Exception:
            pass
        
        # 鏋勫缓涓撲笟鐗堝垎鏋愭彁绀鸿瘝锛堜笉浣跨敤璁板繂绯荤粺锛?
        try:
            shared_context = bazi_memory_manager.build_shared_memory_context(user_id=user_id, dimension=dimension)
            professional_prompt = prompt_builder.build_analysis_prompt(
                style=AnalysisStyle.PROFESSIONAL,
                dimension=dimension,
                bazi_info=bazi_info_dict,
                user_context=user_background,
                shared_memory_context=shared_context
            )
            
            logger.info(f"鏋勫缓涓撲笟鐗堟彁绀鸿瘝瀹屾垚锛岄暱搴? {len(professional_prompt)}")
            
        except Exception as e:
            logger.error(f"鏋勫缓鎻愮ず璇嶅け璐? {e}")
            return jsonify({
                "error": f"鏋勫缓鎻愮ず璇嶅け璐? {str(e)}",
                "error_type": "prompt_error"
            }), 500
        
        # 杩涜涓撲笟鐗堝垎鏋?
        try:
            if not ai_analyzer.deepseek_client:
                raise ConnectionError("DeepSeek瀹㈡埛绔湭鍒濆鍖栵紝璇锋鏌PI瀵嗛挜閰嶇疆銆?")
            
            # 浣跨敤寮傛鏂规硶璋冪敤DeepSeek
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            analysis_options = get_deepseek_analysis_options()
            prof_result = loop.run_until_complete(ai_analyzer.analyze_with_deepseek(
                professional_prompt, 
                model_name=analysis_options["model"],
                temperature=analysis_options["temperature"],
                max_tokens=analysis_options["max_tokens"],
                timeout=analysis_options["timeout"],
            ))
            loop.close()
            
            prof_content = prof_result.content if hasattr(prof_result, 'content') else str(prof_result)
            logger.info(f"涓撲笟鐗堝垎鏋愬畬鎴愶紝鍐呭闀垮害: {len(prof_content)}")
            
        except Exception as e:
            logger.error(f"涓撲笟鐗堝垎鏋愬け璐? {e}")
            return jsonify({
                "error": f"涓撲笟鐗堝垎鏋愬け璐? {str(e)}",
                "error_type": "analysis_error",
                "timestamp": datetime.now().isoformat()
            }), 500

        # 淇濆瓨鍒嗘瀽缁撴灉鍒版湰鍦版枃浠?
        analysis_id = f"analysis-{uuid.uuid4()}"
        analysis_data = {
            "analysis_id": analysis_id,
            "version": version,
            "dimension": dimension,
            "content": prof_content,
            "timestamp": datetime.now().isoformat(),
            "analysis_stage": "professional_only" if version == 'classic' else "professional_completed",
            "models_used": {
                "professional_analysis": analysis_options["model"]
            },
            "model_metadata": prof_result.metadata if hasattr(prof_result, "metadata") else {},
            "bazi_info": bazi_info_dict,
            "user_background": user_background,
            "chart_signature": chart_signature,
        }
        
        # 淇濆瓨鍒扮敤鎴峰垎鏋愭枃浠?
        user_analysis_file = get_user_analysis_file(user_id)
        if append_analysis_records(user_analysis_file, [analysis_data]) is not None:
            logger.info(f"鉁?鍒嗘瀽缁撴灉宸蹭繚瀛樺埌鏈湴鏂囦欢 - 鐢ㄦ埛: {user_id}, 缁村害: {dimension}")
        else:
            logger.warning(f"鈿狅笍 淇濆瓨鍒嗘瀽缁撴灉鍒版湰鍦版枃浠跺け璐?")

        memory_status = _memory_status_for_event(user_id)
        try:
            bazi_memory_manager.store_bazi_analysis(
                user_id=user_id,
                dimension=dimension,
                analysis_content=prof_content,
                analysis_version=version,
                bazi_info=bazi_info_dict,
                user_background=user_background,
                model_used=analysis_options["model"],
                importance=8,
                expires_in_days=365,
            )
            event_id = bazi_memory_manager.append_raw_event(
                user_id=user_id,
                event_type="analysis",
                dimension=dimension,
                version=version,
                content=prof_content,
                model_used=analysis_options["model"],
                user_background=user_background,
                importance=8,
                extra={"analysis_id": analysis_id},
            )
            if memory_organizer:
                memory_organizer.notify(user_id)
            memory_status = _memory_status_for_event(user_id, event_id)
        except Exception as e:
            logger.warning(f"鈿狅笍 [鍏变韩璁板繂] 鍐欏叆缁村害璁板繂澶辫触: {e}")

        response_data = {
            "analysis_id": analysis_id,
            "version": version,
            "dimension": dimension,
            "content": prof_content,
            "timestamp": datetime.now().isoformat(),
            "analysis_stage": "professional_only" if version == 'classic' else "professional_completed",
            "models_used": {
                "professional_analysis": analysis_options["model"]
            },
            "model_metadata": prof_result.metadata if hasattr(prof_result, "metadata") else {},
            "memory_status": memory_status,
        }
        
        logger.info(f"{version}鐗堝垎鏋愬畬鎴?")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"鍏瓧鍒嗘瀽鎺ュ彛鏈煡閿欒: {e}")
        return jsonify({
            "error": f"鍒嗘瀽澶辫触: {str(e)}",
            "error_type": "server_error",
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/analysis/interpretation', methods=['POST'])
def start_interpretation():
    """杩涗竴姝ヨВ璇绘帴鍙?"""
    try:
        data = request.json
        version = data.get('version', 'wisdom')
        dimension = data.get('dimension')
        bazi_info_dict = data.get('bazi_info')
        user_background = data.get('user_background', {})

        logger.info(f"寮€濮{version}鐗堣В璇?- 缁村害: {dimension}")

        if not all([version, dimension, bazi_info_dict]):
            return jsonify({"error": "Missing required parameters: version, dimension, bazi_info"}), 400

        user_id = session.get('user_id')
        if not user_id:
            user_id = resolve_or_create_user_id_by_chart(
                name=user_background.get('name') or '鍖垮悕鐢ㄦ埛',
                gender=user_background.get('gender'),
                birth_time_iso=user_background.get('birth_time'),
                calendar_type=user_background.get('calendar_type'),
                birth_date=user_background.get('birth_date'),
            )
            session['user_id'] = user_id
            session['username'] = user_background.get('name') or session.get('username') or '鍖垮悕鐢ㄦ埛'
            session['login_time'] = session.get('login_time') or datetime.now().isoformat()
        _bind_current_account_to_user(user_id)
        chart_signature = _chart_signature_from_bazi_info(bazi_info_dict, user_background)
        try:
            bazi_memory_manager.update_profile(
                user_id=user_id,
                background=user_background or {},
                preferences={},
                add_tags=[dimension, "瑙ｈ"],
            )
        except Exception:
            pass
        
        # 鏋勫缓瑙ｈ鎻愮ず璇嶏紙涓嶄娇鐢ㄧ敤鎴疯蹇嗭級
        shared_context = bazi_memory_manager.build_shared_memory_context(user_id=user_id, dimension=dimension)
        interpretation_prompt = prompt_builder.build_analysis_prompt(
            style=AnalysisStyle.INTERPRETATION,
            dimension=dimension,
            bazi_info=bazi_info_dict,
            user_context=user_background,
            shared_memory_context=shared_context
        )

        logger.info(f"鏋勫缓瑙ｈ鎻愮ず璇嶅畬鎴愶紝闀垮害: {len(interpretation_prompt)}")

        # 鏍规嵁鐗堟湰閫夋嫨妯″瀷杩涜瑙ｈ
        loop = None
        try:
            # 鍒涘缓鏂扮殑浜嬩欢寰幆
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            if version not in ("classic", "wisdom", "master"):
                return jsonify({
                    "error": f"涓嶆敮鎸佺殑鐗堟湰: {version}",
                    "error_type": "invalid_version"
                }), 400

            if version == "master":
                gemini_options = get_gemini_master_options()
                model_used = gemini_options["model"]
                try:
                    if not ensure_gemini_client_ready():
                        gemini_env_state = {
                            "has_key": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
                            "base_url": os.getenv("GOOGLE_BASE_URL") or "",
                            "model": model_used,
                        }
                        raise ConnectionError(f"Gemini client not initialized: {gemini_env_state}")
                    interp_result = loop.run_until_complete(ai_analyzer.analyze_with_gemini(
                        interpretation_prompt,
                        model_name=model_used,
                        temperature=gemini_options["temperature"],
                        max_tokens=gemini_options["max_tokens"],
                        timeout=gemini_options["timeout"],
                    ))
                except Exception as gemini_error:
                    logger.warning("Master Gemini解读失败，降级到DeepSeek: %s", gemini_error)
                    fallback_options = get_deepseek_interpretation_options("master")
                    model_used = fallback_options["model"]
                    interp_result = loop.run_until_complete(ai_analyzer.analyze_with_deepseek(
                        interpretation_prompt,
                        model_name=model_used,
                        temperature=fallback_options["temperature"],
                        max_tokens=fallback_options["max_tokens"],
                        timeout=fallback_options["timeout"],
                    ))
            else:
                deepseek_options = get_deepseek_interpretation_options(version)
                model_used = deepseek_options["model"]
                interp_result = loop.run_until_complete(ai_analyzer.analyze_with_deepseek(
                    interpretation_prompt,
                    model_name=model_used,
                    temperature=deepseek_options["temperature"],
                    max_tokens=deepseek_options["max_tokens"],
                    timeout=deepseek_options["timeout"],
                ))
            
            interp_content = interp_result.content if hasattr(interp_result, 'content') else str(interp_result)
            logger.info(f"{version}鐗堣В璇诲畬鎴愶紝鍐呭闀垮害: {len(interp_content)}")

            # 淇濆瓨瑙ｈ缁撴灉鍒版湰鍦版枃浠?
            analysis_id = f"interpretation-{uuid.uuid4()}"
            interpretation_data = {
                "analysis_id": analysis_id,
                "version": version,
                "dimension": dimension,
                "content": interp_content,
                "timestamp": datetime.now().isoformat(),
                "analysis_stage": "completed",
                "models_used": {
                    "interpretation": interp_result.model if hasattr(interp_result, 'model') else 'unknown'
                },
                "model_metadata": interp_result.metadata if hasattr(interp_result, "metadata") else {},
                "bazi_info": bazi_info_dict,
                "user_background": user_background,
                "chart_signature": chart_signature,
            }
            
            # 淇濆瓨鍒扮敤鎴峰垎鏋愭枃浠?
            user_analysis_file = get_user_analysis_file(user_id)
            if append_analysis_records(user_analysis_file, [interpretation_data]) is not None:
                logger.info(f"鉁?瑙ｈ缁撴灉宸蹭繚瀛樺埌鏈湴鏂囦欢 - 鐢ㄦ埛: {user_id}")
            else:
                logger.warning(f"鈿狅笍 淇濆瓨瑙ｈ缁撴灉鍒版湰鍦版枃浠跺け璐?")

            memory_status = _memory_status_for_event(user_id)
            try:
                bazi_memory_manager.store_bazi_analysis(
                    user_id=user_id,
                    dimension=dimension,
                    analysis_content=interp_content,
                    analysis_version=version,
                    bazi_info=bazi_info_dict,
                    user_background=user_background,
                    model_used=model_used,
                    importance=8,
                    expires_in_days=365,
                )
                event_id = bazi_memory_manager.append_raw_event(
                    user_id=user_id,
                    event_type="interpretation",
                    dimension=dimension,
                    version=version,
                    content=interp_content,
                    model_used=model_used,
                    user_background=user_background,
                    importance=8,
                    extra={"analysis_id": analysis_id},
                )
                if memory_organizer:
                    memory_organizer.notify(user_id)
                memory_status = _memory_status_for_event(user_id, event_id)
            except Exception as e:
                logger.warning(f"鈿狅笍 [鍏变韩璁板繂] 鍐欏叆瑙ｈ缁村害璁板繂澶辫触: {e}")

            response_data = {
                "analysis_id": analysis_id,
                "version": version,
                "dimension": dimension,
                "content": interp_content,
                "timestamp": datetime.now().isoformat(),
                "analysis_stage": "completed",
                "models_used": {
                    "interpretation": interp_result.model if hasattr(interp_result, 'model') else 'unknown'
                },
                "model_metadata": interp_result.metadata if hasattr(interp_result, "metadata") else {},
                "memory_status": memory_status,
            }

            logger.info(f"{version}鐗堝畬鏁村垎鏋愬畬鎴?")
            return jsonify(response_data)

        except Exception as e:
            logger.error(f"{version}鐗堣В璇诲け璐? {e}")
            return jsonify({
                "error": f"{version}鐗堣В璇诲け璐? {str(e)}",
                "error_type": "interpretation_error",
                "timestamp": datetime.now().isoformat()
            }), 500
        finally:
            # 纭繚浜嬩欢寰幆琚纭叧闂?
            if loop and not loop.is_closed():
                try:
                    loop.close()
                    logger.info(f"鉁?[浜嬩欢寰幆] {version}鐗堣В璇讳簨浠跺惊鐜凡鍏抽棴")
                except Exception as e:
                    logger.warning(f"鈿狅笍 [浜嬩欢寰幆] 鍏抽棴浜嬩欢寰幆鏃跺嚭閿? {e}")

    except Exception as e:
        logger.error(f"瑙ｈ鎺ュ彛鏈煡閿欒: {e}")
        return jsonify({
            "error": f"瑙ｈ澶辫触: {str(e)}",
            "error_type": "server_error",
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/analysis/follow-up', methods=['POST'])
def follow_up_analysis():
    """杩介棶鍒嗘瀽鎺ュ彛锛堢畝鍖栫増鏈紝涓嶄娇鐢ㄤ笂涓嬫枃闆嗘垚锛?"""
    try:
        data = request.json
        version = data.get('version', 'classic')
        dimension = data.get('dimension')
        follow_up_question = data.get('follow_up_question')
        reanalyze_followup_id = (data.get('reanalyze_followup_id') or '').strip()
        bazi_info = data.get('bazi_info') or {}
        user_background = data.get('user_background', {})
        
        if not dimension or not follow_up_question:
            return jsonify({
                "error": "缂哄皯蹇呰鍙傛暟",
                "error_type": "missing_params"
            }), 400
            
        user_id = session.get('user_id')
        if not user_id:
            user_id = resolve_or_create_user_id_by_chart(
                name=user_background.get('name') or '鍖垮悕鐢ㄦ埛',
                gender=user_background.get('gender'),
                birth_time_iso=user_background.get('birth_time'),
                calendar_type=user_background.get('calendar_type'),
                birth_date=user_background.get('birth_date'),
            )
            session['user_id'] = user_id
            session['username'] = user_background.get('name') or session.get('username') or '鍖垮悕鐢ㄦ埛'
            session['login_time'] = session.get('login_time') or datetime.now().isoformat()
        _bind_current_account_to_user(user_id)
        if not bazi_info:
            bazi_info = load_user_bazi_info(user_id) or {}
        chart_signature = _chart_signature_from_bazi_info(bazi_info, user_background)
        try:
            bazi_memory_manager.update_profile(
                user_id=user_id,
                background=user_background or {},
                preferences={},
                add_tags=[dimension, "杩介棶"],
            )
        except Exception:
            pass
        logger.info(f"寮€濮嬭拷闂垎鏋?- 缁村害: {dimension}, 闂: {follow_up_question}")
        
        # 鏋勫缓绠€鍖栫殑杩介棶鎻愮ず璇嶏紙涓嶄娇鐢ㄨ蹇嗘垨涓婁笅鏂囷級
        previous_analysis = bazi_memory_manager.get_latest_dimension_insight(user_id=user_id, dimension=dimension)
        shared_context = bazi_memory_manager.build_shared_memory_context(user_id=user_id, dimension=dimension, query=follow_up_question)
        follow_up_prompt = prompt_builder.build_followup_prompt(
            analysis_dimension=dimension,
            bazi_info=bazi_info,
            previous_analysis=previous_analysis,
            followup_question=follow_up_question,
            user_context=user_background,
            shared_memory_context=shared_context
        )
        
        logger.info(f"鏋勫缓杩介棶鎻愮ず璇嶅畬鎴愶紝闀垮害: {len(follow_up_prompt)}")
        
        # 鏍规嵁鐗堟湰閫夋嫨妯″瀷杩涜鍒嗘瀽
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            if version not in ['classic', 'wisdom', 'master']:
                return jsonify({
                    "error": f"涓嶆敮鎸佺殑鐗堟湰: {version}",
                    "error_type": "invalid_version"
                }), 400

            followup_options = get_deepseek_followup_options()
            model_used = followup_options["model"]
            result = loop.run_until_complete(ai_analyzer.analyze_with_deepseek(
                follow_up_prompt,
                model_name=model_used,
                temperature=followup_options["temperature"],
                max_tokens=followup_options["max_tokens"],
                timeout=followup_options["timeout"],
            ))
            
            result_content = result.content if hasattr(result, 'content') else str(result)
            
        except Exception as e:
            logger.error(f"杩介棶鍒嗘瀽澶辫触: {e}")
            return jsonify({
                "error": f"杩介棶鍒嗘瀽澶辫触: {str(e)}",
                "error_type": "analysis_error"
            }), 500
        finally:
            # 纭繚浜嬩欢寰幆琚纭叧闂?
            if loop and not loop.is_closed():
                try:
                    loop.close()
                    logger.info("鉁?[浜嬩欢寰幆] 杩介棶鍒嗘瀽浜嬩欢寰幆宸插叧闂?")
                except Exception as e:
                    logger.warning(f"鈿狅笍 [浜嬩欢寰幆] 鍏抽棴杩介棶浜嬩欢寰幆鏃跺嚭閿? {e}")
        
        # 淇濆瓨杩介棶缁撴灉鍒版湰鍦版枃浠?
        now_iso = datetime.now().isoformat()
        followup_id = reanalyze_followup_id if reanalyze_followup_id.startswith("followup-") else f"followup-{uuid.uuid4()}"
        followup_data = {
            "analysis_id": followup_id,
            "version": version,
            "dimension": dimension,
            "question": follow_up_question,
            "content": result_content,
            "timestamp": now_iso,
            "bazi_info": bazi_info,
            "user_background": user_background,
            "chart_signature": chart_signature,
            "reanalyzed_at": now_iso if reanalyze_followup_id else None,
        }
        
        # 淇濆瓨鍒扮敤鎴峰垎鏋愭枃浠?
        user_analysis_file = get_user_analysis_file(user_id)
        saved_followup, updated_existing_followup = upsert_followup_record(
            user_analysis_file,
            followup_data,
            dimension,
            reanalyze_followup_id,
        )
        if saved_followup:
            logger.info("鉁?杩介棶缁撴灉宸蹭繚瀛樺埌鏈湴鏂囦欢")
        else:
            logger.warning("鈿狅笍 淇濆瓨杩介棶缁撴灉鍒版湰鍦版枃浠跺け璐?")

        memory_status = _memory_status_for_event(user_id)
        try:
            event_id = bazi_memory_manager.append_raw_event(
                user_id=user_id,
                event_type="followup",
                dimension=dimension,
                version=version,
                content=f"杩介棶锛{follow_up_question}\n{result_content}".strip(),
                model_used=model_used,
                user_background=user_background,
                importance=6,
                extra={
                    "question": follow_up_question,
                    "analysis_id": followup_id,
                    "reanalyze": bool(reanalyze_followup_id),
                    "updated_existing_followup": updated_existing_followup,
                },
            )
            if memory_organizer:
                memory_organizer.notify(user_id)
            memory_status = _memory_status_for_event(user_id, event_id)
        except Exception as e:
            logger.warning(f"鈿狅笍 [鍏变韩璁板繂] 鍐欏叆杩介棶璁板繂澶辫触: {e}")
        
        return jsonify({
            "success": True,
            "analysis_id": followup_id,
            "version": version,
            "dimension": dimension,
            "question": follow_up_question,
            "content": result_content,
            "timestamp": now_iso,
            "reanalyze": bool(reanalyze_followup_id),
            "updated_existing_followup": updated_existing_followup,
            "chart_signature": chart_signature,
            "memory_status": memory_status,
        })
        
    except Exception as e:
        logger.error(f"杩介棶鍒嗘瀽澶辫触: {e}")
        return jsonify({
            "error": f"杩介棶鍒嗘瀽澶辫触: {str(e)}",
            "error_type": "analysis_error",
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/api/user/analysis-history', methods=['GET'])
@login_required
def get_user_analysis_history():
    """鑾峰彇鐢ㄦ埛鍒嗘瀽鍘嗗彶"""
    try:
        user_id = session.get('user_id')
        user_analysis_file = get_user_analysis_file(user_id)
        analysis_data = load_from_local_file(user_analysis_file)
        if isinstance(analysis_data, dict):
            filtered = _filter_analysis_doc_for_chart(user_id, analysis_data)
            if filtered != analysis_data:
                save_to_local_file(user_analysis_file, filtered)
                analysis_data = filtered
        
        if analysis_data and "analyses" in analysis_data:
            return jsonify({
                "success": True,
                "analyses": analysis_data["analyses"],
                "total_count": len(analysis_data["analyses"]),
                "invalidations": analysis_data.get("invalidations", []),
            })
        else:
            return jsonify({
                "success": True,
                "analyses": [],
                "total_count": 0
            })
            
    except Exception as e:
        logger.error(f"鑾峰彇鍒嗘瀽鍘嗗彶澶辫触: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/user/bazi-data', methods=['GET'])
@login_required
def get_user_bazi_data():
    """鑾峰彇鐢ㄦ埛鍏瓧鏁版嵁"""
    try:
        user_id = session.get('user_id')
        username = session.get('username')
        
        logger.info(f"馃攳 [鑾峰彇鐢ㄦ埛鏁版嵁] 鐢ㄦ埛璇锋眰鍏瓧鏁版嵁: {username} (ID: {user_id})")
        
        bazi_file = get_user_bazi_file(user_id)
        bazi_data = load_from_local_file(bazi_file)
        
        logger.info(f"馃搧 [鏈湴鏂囦欢] 鍏瓧鏂囦欢璺緞: {bazi_file}")
        logger.info(f"馃搫 [鏈湴鏂囦欢] 鏂囦欢瀛樺湪: {bazi_data is not None}")
        
        # 濡傛灉娌℃湁鎵惧埌鏁版嵁锛屽皾璇曟悳绱㈡渶鏂扮殑鐢ㄦ埛鏂囦欢
        if not bazi_data:
            logger.warning(f"鈿狅笍 [鏁版嵁鏌ユ壘] 鏈壘鍒扮敤鎴{user_id}鐨勬暟鎹枃浠讹紝灏濊瘯鏌ユ壘鏈€鏂版枃浠?..")
            import glob
            import os
            bazi_files = glob.glob(os.path.join(BAZI_DATA_DIR, "user_*_bazi.json"))
            if bazi_files:
                # 鎸変慨鏀规椂闂存帓搴忥紝鑾峰彇鏈€鏂扮殑鏂囦欢
                latest_file = max(bazi_files, key=os.path.getmtime)
                logger.info(f"馃攳 [鏁版嵁鏌ユ壘] 鎵惧埌鏈€鏂板叓瀛楁枃浠? {latest_file}")
                bazi_data = load_from_local_file(latest_file)
                
                if bazi_data:
                    logger.info(f"鉁?[鏁版嵁鎭㈠] 鎴愬姛浠庢渶鏂版枃浠舵仮澶嶆暟鎹?")
        
        if bazi_data:
            # 纭繚杩斿洖姝ｇ‘鐨勬暟鎹粨鏋勬牸寮?
            # 澧炲己鏁版嵁锛氬鏋滀娇鐢ㄤ簡鐪熷お闃虫椂锛屼紭鍏堟樉绀虹湡澶槼鏃?
            user_info = bazi_data.get("user_info", {})
            
            # 妫€鏌ユ槸鍚﹀簲鐢ㄤ簡鐪熷お闃虫椂
            if user_info.get("solar_time_applied"):
                true_solar_time = user_info.get("true_solar_time")
                if true_solar_time:
                    # 灏嗙湡澶槼鏃朵綔涓烘樉绀烘椂闂达紝骞朵繚鐣欏師濮嬫椂闂?
                    user_info["display_birth_time"] = true_solar_time
                    user_info["is_true_solar_time"] = True
                    user_info["original_birth_time"] = user_info.get("birth_time")
                    
                    # 鍏抽敭淇敼锛氱洿鎺ヨ鐩?birth_time 浠ョ‘淇濆墠绔粯璁ゆ樉绀虹湡澶槼鏃?
                    # 浣嗗悓鏃朵繚鐣欏師濮嬫椂闂翠緵鍙傝€?
                    # user_info["birth_time"] = true_solar_time 
                    # 璋ㄦ厧璧疯锛屾垜浠鍔犱竴涓?explicit_display_time 瀛楁渚涘墠绔紭鍏堜娇鐢?
                    
                    logger.info(f"馃尀 [API鍝嶅簲] 宸叉敞鍏ョ湡澶槼鏃朵俊鎭? {true_solar_time}")

            response_data = {
                "user_info": user_info,
                "bazi_info": bazi_data.get("bazi_info", {}),
                "chart_signature": bazi_data.get("chart_signature") or _chart_signature_from_bazi_payload(bazi_data),
                "chart_invalidation": bazi_data.get("chart_invalidation"),
            }
            
            logger.info(f"鉁?[API鍝嶅簲] 鎴愬姛杩斿洖鐢ㄦ埛鍏瓧鏁版嵁:")
            logger.info(f"   鐢ㄦ埛淇℃伅: {response_data['user_info'].get('name', '鏈煡')}")
            logger.info(f"   鍏瓧鏁版嵁瀛楁: {list(response_data['bazi_info'].keys()) if response_data['bazi_info'] else 'N/A'}")
            
            return jsonify(response_data)
        else:
            logger.warning(f"鈿狅笍 [鏁版嵁缂哄け] 鏈壘鍒扮敤鎴峰叓瀛楁暟鎹枃浠?")
            return jsonify({
                "error": "鏈壘鍒板叓瀛楁暟鎹紝璇烽噸鏂扮櫥褰曡幏鍙?",
                "user_info": {
                    "name": username,
                    "user_id": user_id
                },
                "bazi_info": {}
            }), 404
            
    except Exception as e:
        logger.error(f"鉂?[API閿欒] 鑾峰彇鍏瓧鏁版嵁澶辫触: {e}")
        return jsonify({
            "error": f"鑾峰彇鍏瓧鏁版嵁澶辫触: {str(e)}",
            "user_info": {},
            "bazi_info": {}
        }), 500

@app.route('/api/user/pdf-report-data', methods=['GET'])
@login_required
def get_pdf_report_data():
    """获取 PDF 报告所需的当前用户数据。"""
    try:
        user_id = session.get('user_id')
        username = session.get('username')
        
        logger.info(f"📄 [PDF数据] 用户请求 PDF 报告数据: {username} (ID: {user_id})")
        
        report_data = {
            "userInfo": {},
            "baziInfo": {},
            "analysisResults": [],
            "followUpResults": [],
            "generatedTime": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 获取当前用户八字数据
        bazi_file = get_user_bazi_file(user_id)
        bazi_data = load_from_local_file(bazi_file)
        
        if not bazi_data:
            logger.warning(f"⚠️ [PDF数据] 未找到当前用户 {user_id} 的八字文件: {bazi_file}")
            return jsonify({
                "success": False,
                "error": "未找到当前用户的八字数据，请先完成排盘后再导出 PDF。"
            }), 404
        
        # 解析用户信息和八字信息
        if bazi_data:
            user_info = bazi_data.get("user_info", {})
            bazi_info = bazi_data.get("bazi_info", {})
            bazi_info = bazi_info if isinstance(bazi_info, dict) else {}
            raw_data = _extract_bazi_raw_data(bazi_data)

            gender_value = user_info.get("gender")
            if gender_value in (1, "1", "男", "male", "Male", "M", "m"):
                gender_text = "男"
            elif gender_value in (0, "0", "女", "female", "Female", "F", "f"):
                gender_text = "女"
            else:
                gender_text = raw_data.get("性别") or "未知"

            birth_time = (
                user_info.get("display_birth_time")
                or raw_data.get("阳历")
                or user_info.get("birth_time")
                or "未知"
            )
            
            report_data["userInfo"] = {
                "name": user_info.get("name") or username or "未知",
                "gender": gender_text,
                "birthDate": user_info.get("birth_date") or "未知",
                "birthTime": birth_time
            }
            
            if raw_data:
                report_data["baziInfo"] = {
                    "bazi": raw_data.get("八字") or "未知",
                    "solarDate": raw_data.get("阳历") or "未知",
                    "lunarDate": raw_data.get("农历") or "未知",
                    "zodiac": raw_data.get("生肖") or "未知",
                    "dayMaster": raw_data.get("日主") or "未知",
                    "chartDetails": _build_pdf_chart_details(raw_data, bazi_info, user_info),
                }
            
            logger.info(f"✅ [PDF数据] 八字信息收集完成: {report_data['baziInfo'].get('bazi', '未知')}")
        
        if not report_data["baziInfo"].get("bazi") or report_data["baziInfo"]["bazi"] == "未知":
            logger.warning(f"⚠️ [PDF数据] 当前用户 {user_id} 的八字信息不完整")
            return jsonify({
                "success": False,
                "error": "当前用户的八字数据不完整，请重新排盘后再导出 PDF。"
            }), 400

        # 获取当前用户分析历史数据
        user_analysis_file = get_user_analysis_file(user_id)
        analysis_data = load_from_local_file(user_analysis_file)
        
        if not analysis_data or "analyses" not in analysis_data:
            logger.warning(f"⚠️ [PDF数据] 未找到当前用户 {user_id} 的分析文件: {user_analysis_file}")
        
        if analysis_data and "analyses" in analysis_data:
            analyses = analysis_data["analyses"]
            logger.info(f"📊 [PDF数据] 找到 {len(analyses)} 条分析记录")
            
            # 按维度分组，只保留每个维度的最新主分析
            dimension_analysis = {}
            followup_records = []
            for analysis in analyses:
                if not isinstance(analysis, dict):
                    continue
                dimension = analysis.get("dimension", "未知维度")
                timestamp = analysis.get("timestamp", "")
                
                # 只保留主分析，跳过追问记录
                if str(analysis.get("analysis_id") or "").startswith("followup-"):
                    followup_records.append(analysis)
                    continue
                
                if dimension not in dimension_analysis or timestamp > dimension_analysis[dimension].get("timestamp", ""):
                    dimension_analysis[dimension] = analysis
            
            for dimension, analysis in dimension_analysis.items():
                content = analysis.get("content", "")
                if content:
                    report_data["analysisResults"].append({
                        "dimension": dimension,
                        "content": content,
                        "version": analysis.get("version", "classic"),
                        "timestamp": analysis.get("timestamp", "")
                    })

            for followup in sorted(followup_records, key=lambda item: item.get("timestamp", "")):
                content = followup.get("content", "")
                if content:
                    report_data["followUpResults"].append({
                        "dimension": followup.get("dimension", "未知维度"),
                        "question": followup.get("question", "追问"),
                        "content": content,
                        "version": followup.get("version", "classic"),
                        "timestamp": followup.get("timestamp", ""),
                    })
            
            logger.info(f"✅ [PDF数据] 分析结果收集完成，共 {len(report_data['analysisResults'])} 个维度")
        else:
            logger.warning(f"⚠️ [PDF数据] 未找到当前用户的分析历史数据")
        
        if not report_data["analysisResults"]:
            logger.warning(f"⚠️ [PDF数据] 分析结果为空")
        
        logger.info("📋 [PDF数据] 数据收集完成:")
        logger.info(f"   - 用户: {report_data['userInfo'].get('name', '未知')}")
        logger.info(f"   - 八字: {report_data['baziInfo'].get('bazi', '未知')}")
        logger.info(f"   - 分析维度: {len(report_data['analysisResults'])} 个")
        logger.info(f"   - 追问记录: {len(report_data['followUpResults'])} 条")
        
        return jsonify({
            "success": True,
            "data": report_data
        })
        
    except Exception as e:
        logger.error(f"❌ [PDF数据] 获取 PDF 报告数据失败: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"获取 PDF 报告数据失败: {str(e)}"
        }), 500

@app.route('/api/user/export-pdf', methods=['GET'])
@login_required
def export_user_pdf():
    """生成高清矢量 PDF 报告。"""
    try:
        data_response = get_pdf_report_data()
        status_code = 200
        response_obj = data_response
        if isinstance(data_response, tuple):
            response_obj = data_response[0]
            status_code = data_response[1] if len(data_response) > 1 else 200

        if status_code >= 400:
            return data_response

        payload = response_obj.get_json(silent=True) if hasattr(response_obj, "get_json") else None
        if not isinstance(payload, dict) or not payload.get("success"):
            return jsonify({
                "success": False,
                "error": (payload or {}).get("error") or "PDF 报告数据不可用。"
            }), 500

        report_data = payload.get("data") or {}
        if not report_data.get("analysisResults"):
            return jsonify({
                "success": False,
                "error": "没有找到任何分析结果，请先完成至少一个维度的分析后再导出 PDF。"
            }), 400

        pdf_bytes = build_pdf_report(report_data)
        filename = make_pdf_filename(report_data)
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Length"] = str(len(pdf_bytes))
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        response.headers["X-PDF-Mode"] = "vector-reportlab" if os.getenv("PDF_RENDERER", "html").lower() == "reportlab" else "html-chromium"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except Exception as e:
        logger.error(f"PDF 导出失败: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"PDF 导出失败: {str(e)}"
        }), 500

@app.route('/api/liuyao/calculate', methods=['POST'])
@login_required
def calculate_liuyao():
    """鍏埢鎺掔洏璁＄畻鎺ュ彛"""
    try:
        data = request.json
        method = data.get('method', 'coins') # 'coins' or 'plum_blossom'
        question = data.get('question')
        location = data.get('location') # 鑾峰彇鍦扮悊浣嶇疆淇℃伅
        
        # 鑾峰彇璧峰崷鏃堕棿
        divination_time_str = data.get('divination_time')
        divination_dt = datetime.now()
        if divination_time_str:
            try:
                divination_dt = datetime.fromisoformat(divination_time_str)
            except ValueError:
                pass
        
        # --- 鐪熷お闃虫椂澶勭悊寮€濮?---
        true_solar_applied = False
        used_longitude = None
        original_dt = divination_dt
        
        # 灏濊瘯鑾峰彇缁忓害
        longitude = None
        if location:
            # 1. 灏濊瘯鐩存帴鑾峰彇缁忓害
            if 'longitude' in location:
                try:
                    longitude = float(location['longitude'])
                except (ValueError, TypeError):
                    pass
            
            # 2. 濡傛灉娌℃湁缁忓害浣嗘湁鍦板潃锛屽皾璇曡В鏋?
            if longitude is None:
                try:
                    prov = location.get("province", "")
                    city = location.get("city", "")
                    dist = location.get("district", "")
                    addr = location.get("address", "")
                    coords = get_offline_coordinates(province=prov, city=city, district=dist, address=addr)
                    if coords:
                        _, longitude = coords
                except Exception as e:
                    logger.warning(f"鍏埢-鍦板潃瑙ｆ瀽澶辫触: {e}")
        
        # 濡傛灉鑾峰彇鍒颁簡缁忓害锛岃绠楃湡澶槼鏃?
        if longitude is not None:
            try:
                divination_dt = calculate_true_solar_time(divination_dt, longitude)
                true_solar_applied = True
                used_longitude = longitude
                logger.info(f"鍏埢鎺掔洏浣跨敤鐪熷お闃虫椂: {original_dt} -> {divination_dt} (缁忓害: {longitude})")
            except Exception as e:
                logger.warning(f"鍏埢-鐪熷お闃虫椂璁＄畻澶辫触: {e}")
        # --- 鐪熷お闃虫椂澶勭悊缁撴潫 ---

        # 绠€鍖栫殑骞叉敮璁＄畻锛堝疄闄呭簲璋冪敤BaziClient锛?
        ganzhi_map = qimen_logic.calculate_ganzhi_simplified(divination_dt)
        divination_time_ganzhi = {
            'year': ganzhi_map['year'],
            'month': ganzhi_map['month'],
            'day': ganzhi_map['day'],
            'hour': ganzhi_map['hour'],
            'is_true_solar': true_solar_applied,
            'longitude': used_longitude
        }

        result = {}
        if method == 'coins':
            result = liuyao_logic.generate_hexagram_coins(divination_time_ganzhi=divination_time_ganzhi)
        elif method == 'plum_blossom':
            # 姊呰姳鏄撴暟閫氬父浣跨敤鍐滃巻鎴栫壒瀹氭暟瀛楋紝杩欓噷濡傛灉浼犱簡鏃堕棿锛屼篃搴旇鐢ㄧ湡澶槼鏃?
            # 浣嗚娉ㄦ剰姊呰姳鏄撴暟鐨勫勾鏈堟棩鏃舵暟璧峰崷娉曪紝閫氬父鏄熀浜庡啘鍘嗙殑銆?
            # 杩欓噷鐨勫疄鐜?`generate_plum_blossom_hexagram` 鎺ユ敹 year, month, day, hour
            # 濡傛灉鍓嶇浼犵殑鏄叕鍘嗘暟瀛楋紝鍚庣鐩存帴鐢ㄥ叕鍘嗘暟瀛楄捣鍗︼紙杩欐槸涓€绉嶅彉閫氱殑姊呰姳鏄撴暟锛屾垨鑰呭彨鏃堕棿鍗︼級
            # 濡傛灉瑕佷弗鏍奸伒寰鑺辨槗鏁帮紝搴旇杞啘鍘嗐€?
            # 閴翠簬鐜版湁閫昏緫鏄洿鎺ュ彇 dt.year 绛夛紝鎴戜滑淇濇寔閫昏緫涓嶅彉锛屼絾浣跨敤淇鍚庣殑鏃堕棿瀵硅薄
            year = int(data.get('year', divination_dt.year))
            month = int(data.get('month', divination_dt.month))
            day = int(data.get('day', divination_dt.day))
            hour = int(data.get('hour', divination_dt.hour))
            result = liuyao_logic.generate_plum_blossom_hexagram(
                year, month, day, hour, 
                question=question,
                divination_time_ganzhi=divination_time_ganzhi
            )
        else:
            return jsonify({"success": False, "error": "涓嶆敮鎸佺殑璧峰崷鏂瑰紡"}), 400

        # 娉ㄥ叆鐪熷お闃虫椂淇℃伅鍒扮粨鏋滀腑锛屼互渚垮墠绔睍绀?
        result['solarTimeInfo'] = {
            'applied': true_solar_applied,
            'originalTime': original_dt.isoformat(),
            'solarTime': divination_dt.isoformat(),
            'longitude': used_longitude
        }

        # 瀛樺偍鍒拌蹇嗙郴缁?
        user_id = session.get('user_id')
        if user_id:
            try:
                bazi_memory_manager.store_liuyao_info(user_id, result)
            except Exception as e:
                logger.warning(f"瀛樺偍鍏埢淇℃伅澶辫触: {e}")

        return jsonify({"success": True, "data": result})

    except Exception as e:
        logger.error(f"鍏埢璁＄畻澶辫触: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/qimen/calculate', methods=['POST'])
@login_required
def calculate_qimen():
    """濂囬棬閬佺敳鎺掔洏璁＄畻鎺ュ彛"""
    try:
        data = request.json
        date_time_str = data.get('date_time')
        location = data.get('location') # 鑾峰彇鍦扮悊浣嶇疆淇℃伅
        
        dt = datetime.now()
        if date_time_str:
            try:
                dt = datetime.fromisoformat(date_time_str)
            except ValueError:
                pass
        
        # --- 鐪熷お闃虫椂澶勭悊寮€濮?---
        true_solar_applied = False
        used_longitude = None
        original_dt = dt
        
        # 灏濊瘯鑾峰彇缁忓害
        longitude = None
        if location:
            # 1. 灏濊瘯鐩存帴鑾峰彇缁忓害
            if 'longitude' in location:
                try:
                    longitude = float(location['longitude'])
                except (ValueError, TypeError):
                    pass
            
            # 2. 濡傛灉娌℃湁缁忓害浣嗘湁鍦板潃锛屽皾璇曡В鏋?
            if longitude is None:
                try:
                    prov = location.get("province", "")
                    city = location.get("city", "")
                    dist = location.get("district", "")
                    addr = location.get("address", "")
                    coords = get_offline_coordinates(province=prov, city=city, district=dist, address=addr)
                    if coords:
                        _, longitude = coords
                except Exception as e:
                    logger.warning(f"濂囬棬-鍦板潃瑙ｆ瀽澶辫触: {e}")
        
        # 濡傛灉鑾峰彇鍒颁簡缁忓害锛岃绠楃湡澶槼鏃?
        if longitude is not None:
            try:
                dt = calculate_true_solar_time(dt, longitude)
                true_solar_applied = True
                used_longitude = longitude
                logger.info(f"濂囬棬鎺掔洏浣跨敤鐪熷お闃虫椂: {original_dt} -> {dt} (缁忓害: {longitude})")
            except Exception as e:
                logger.warning(f"濂囬棬-鐪熷お闃虫椂璁＄畻澶辫触: {e}")
        # --- 鐪熷お闃虫椂澶勭悊缁撴潫 ---
        
        # 璁＄畻濂囬棬灞€
        result = qimen_logic.generate_qimen_chart(date_time=dt)
        
        # 娉ㄥ叆鐪熷お闃虫椂淇℃伅鍒扮粨鏋滀腑
        result['solarTimeInfo'] = {
            'applied': true_solar_applied,
            'originalTime': original_dt.isoformat(),
            'solarTime': dt.isoformat(),
            'longitude': used_longitude
        }
        
        # 瀛樺偍鍒拌蹇嗙郴缁?
        user_id = session.get('user_id')
        if user_id:
            try:
                info = {
                    'year': result['year'],
                    'month': result['month'],
                    'day': result['day'],
                    'hour': result['hour'],
                    'dun_type': '阳遁' if result['escapeType'] == 'yang' else '阴遁',
                    'bureau_number': result['bureauNumber'],
                    'lead_star': result['dutyChief'],
                    'lead_door': result['dutyDoor']
                }
                bazi_memory_manager.store_qimen_info(user_id, {'chart': result, 'info': info})
            except Exception as e:
                logger.warning(f"瀛樺偍濂囬棬淇℃伅澶辫触: {e}")
                
        return jsonify({"success": True, "data": result})

    except Exception as e:
        logger.error(f"濂囬棬璁＄畻澶辫触: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# 閿欒澶勭悊
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "椤甸潰鏈壘鍒?"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "鏈嶅姟鍣ㄥ唴閮ㄩ敊璇?"}), 500

if __name__ == '__main__':
    debug = str(os.getenv("FLASK_DEBUG", "true")).strip().lower() in ("1", "true", "yes", "y", "on")
    try:
        port = int(os.getenv("PORT") or os.getenv("FLASK_PORT") or "5002")
    except ValueError:
        logger.warning("绔彛閰嶇疆鏃犳晥锛屽洖閫€鍒?5002")
        port = 5002
    host = os.getenv("HOST", "0.0.0.0")
    display_host = "localhost" if host in ("0.0.0.0", "::") else host
    base_url = f"http://{display_host}:{port}"

    print("Starting Bazi analysis system - simplified version...")
    print("=" * 50)
    print("Core components:")
    print("   - AI analyzer: DeepSeek (Gemini legacy optional)")
    print("   - Prompt builder: three analysis versions")
    print("   - User manager: local file storage")
    print("   - Data storage: local")
    print()
    print(f"Server: {base_url}")
    print(f"Web: {base_url}/")
    print(f"API status: {base_url}/api/status")
    print("=" * 50)
    
    app.run(host=host, port=port, debug=debug, use_reloader=False)
