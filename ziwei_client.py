import mcp
from mcp.client.stdio import StdioServerParameters, stdio_client
import json
import asyncio
from typing import Any, Dict, List, Optional, Tuple
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
import requests

try:
    from china_locations import get_coordinates as get_offline_coordinates
except ImportError:
    def get_offline_coordinates(*args, **kwargs):
        return None

def _ensure_logger() -> logging.Logger:
    logger = logging.getLogger("ziwei_mcp")
    logger.setLevel(logging.INFO)
    if getattr(logger, "_ziwei_configured", False):
        return logger

    log_dir = os.path.join("local_data", "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "ziwei_mcp.log")
    handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.propagate = True
    logger._ziwei_configured = True
    return logger


_logger = _ensure_logger()


def _safe_json_dumps(obj: Any, max_len: int = 4000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _extract_text_content(result_content: Any) -> str:
    if result_content is None:
        return ""
    if isinstance(result_content, str):
        return result_content
    if hasattr(result_content, "text"):
        try:
            return str(result_content.text or "")
        except Exception:
            return str(result_content)
    if isinstance(result_content, list) and result_content:
        item0 = result_content[0]
        if hasattr(item0, "text"):
            try:
                return str(item0.text or "")
            except Exception:
                return str(item0)
        return str(item0)
    return str(result_content)


def _try_parse_json(text: str) -> Tuple[Optional[Any], str]:
    t = (text or "").strip()
    if not t:
        return None, ""
    try:
        return json.loads(t), t
    except Exception:
        return None, t


def _append_jsonl(path: str, record: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str))
            f.write("\n")
    except Exception as e:
        _logger.error("ziwei jsonl append failed: %s", str(e)[:300])


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _normalize_location(location: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = {"province": "", "city": "", "longitude": 0, "latitude": 0}
    if not isinstance(location, dict):
        return base
    province = (location.get("province") or "").strip()
    city = (location.get("city") or "").strip()
    address = (location.get("address") or location.get("full_address") or "").strip()
    longitude = _coerce_float(location.get("longitude"))
    latitude = _coerce_float(location.get("latitude"))
    base.update(
        {
            "province": province,
            "city": city,
            "address": address,
            "longitude": longitude if longitude is not None else 0,
            "latitude": latitude if latitude is not None else 0,
        }
    )
    return base


def _build_location_query(location: Dict[str, Any]) -> str:
    parts = []
    for key in ["address", "city", "province"]:
        v = (location.get(key) or "").strip()
        if v and v not in parts:
            parts.append(v)
    query = " ".join(parts).strip()
    if not query:
        return ""
    if "中国" not in query and "China" not in query:
        query = f"{query} 中国"
    return query


def _geocode_location(query: str) -> Optional[Dict[str, Any]]:
    if not query:
        return None
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "ziwei-mcp-client/1.0"}
    
    # 尝试解析 query 中的省市信息以构建结构化查询
    # query 格式通常为: "address city province 中国"
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
        "countrycodes": "cn",  # 限制在中国
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=6)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not data:
        return None
    item = data[0] if isinstance(data, list) else data
    lat = _coerce_float(item.get("lat"))
    lon = _coerce_float(item.get("lon"))
    if lat is None or lon is None:
        return None
    
    # 提取详细地址信息
    address = item.get("address") or {}
    province = (
        address.get("state")
        or address.get("province")
        or address.get("region")
        or ""
    )
    city = (
        address.get("city")
        or address.get("town")
        or address.get("county")
        or address.get("state_district")
        or ""
    )
    
    # 简单校验: 如果查询包含省份/城市，结果最好也要包含
    # 但由于 OSM 数据不完整，这里只做软性校验或记录
    
    return {
        "latitude": lat,
        "longitude": lon,
        "province": province,
        "city": city,
        "display_name": item.get("display_name") or "",
    }


def _has_valid_coordinates(location: Dict[str, Any]) -> bool:
    lat = _coerce_float(location.get("latitude"))
    lon = _coerce_float(location.get("longitude"))
    if lat is None or lon is None:
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


async def _resolve_location(location: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    loc = _normalize_location(location)
    if _has_valid_coordinates(loc):
        return loc
    
    # 0. 尝试离线字典
    prov = loc.get("province", "")
    city = loc.get("city", "")
    addr = loc.get("address", "")
    
    off_coord = get_offline_coordinates(province=prov, city=city, address=addr)
    if off_coord:
        loc["latitude"], loc["longitude"] = off_coord
        loc["display_name"] = f"离线数据: {prov} {city} {addr}".strip()
        _logger.info(f"Using offline coordinates for {loc['display_name']}")
        return loc
    
    # 1. 在线查询
    query = _build_location_query(loc)
    if not query:
        return loc
    try:
        loop = asyncio.get_running_loop()
        geo = await loop.run_in_executor(None, _geocode_location, query)
    except Exception:
        geo = None
    if not geo:
        return loc
    if not loc.get("province"):
        loc["province"] = geo.get("province") or loc.get("province")
    if not loc.get("city"):
        loc["city"] = geo.get("city") or loc.get("city")
    loc["longitude"] = geo.get("longitude") or loc.get("longitude")
    loc["latitude"] = geo.get("latitude") or loc.get("latitude")
    loc["display_name"] = geo.get("display_name") or loc.get("display_name") or ""
    return loc


class ZiweiClient:
    def __init__(
        self,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        request_id: Optional[str] = None,
    ):
        self.command = (command or os.getenv("ZIWEI_MCP_COMMAND") or "npx").strip()
        self.args = args or self._load_args_from_env() or ["-y", "ziwei-mcp"]
        self.request_id = (request_id or "").strip() or None

    def _load_args_from_env(self) -> Optional[List[str]]:
        raw = (os.getenv("ZIWEI_MCP_ARGS") or "").strip()
        if not raw:
            return None
        try:
            v = json.loads(raw)
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                return v
        except Exception:
            pass
        parts = [p.strip() for p in raw.split() if p.strip()]
        return parts or None

    async def list_tools(self) -> List[str]:
        server = StdioServerParameters(command=self.command, args=self.args)
        async with stdio_client(server) as (read_stream, write_stream):
            async with mcp.ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                return [t.name for t in (tools_result.tools or [])]

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        arguments = arguments or {}
        server = StdioServerParameters(command=self.command, args=self.args)
        t0 = datetime.now()
        try:
            async with stdio_client(server) as (read_stream, write_stream):
                async with mcp.ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=arguments)
            dt_ms = int((datetime.now() - t0).total_seconds() * 1000)
        except Exception as e:
            dt_ms = int((datetime.now() - t0).total_seconds() * 1000)
            err_record = {
                "ts": datetime.now().isoformat(),
                "request_id": self.request_id,
                "tool": tool_name,
                "dt_ms": dt_ms,
                "args": arguments,
                "error_type": type(e).__name__,
                "error": str(e)[:4000],
            }
            _append_jsonl(os.path.join("local_data", "logs", "ziwei_mcp_results.jsonl"), err_record)
            _logger.error(
                "ziwei tool_call failed request_id=%s tool=%s dt_ms=%s error_type=%s error=%s",
                self.request_id or "",
                tool_name,
                dt_ms,
                type(e).__name__,
                str(e)[:800],
            )
            raise

        content = getattr(result, "content", None)
        text = _extract_text_content(content)
        parsed, raw_text = _try_parse_json(text)

        record = {
            "ts": datetime.now().isoformat(),
            "request_id": self.request_id,
            "tool": tool_name,
            "dt_ms": dt_ms,
            "args": arguments,
            "raw_text": raw_text[:20000],
            "parsed": parsed if isinstance(parsed, (dict, list)) else None,
        }
        _append_jsonl(os.path.join("local_data", "logs", "ziwei_mcp_results.jsonl"), record)

        _logger.info(
            "ziwei tool_call done request_id=%s tool=%s dt_ms=%s args=%s preview=%s",
            self.request_id or "",
            tool_name,
            dt_ms,
            _safe_json_dumps({k: arguments.get(k) for k in list(arguments.keys())[:20]}, max_len=800),
            (raw_text[:600] + "...") if len(raw_text) > 600 else raw_text,
        )

        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"text_result": raw_text}

    async def generate_chart(
        self,
        name: str,
        birth_date: str,
        birth_time: str,
        gender: str,
        location: Optional[Dict[str, Any]] = None,
        timezone: str = "Asia/Shanghai",
        calendar: str = "solar",
    ) -> Dict[str, Any]:
        """
        生成紫微斗数命盘
        
        注意：Ziwei MCP 内部会自动根据 location 计算真太阳时，
        因此这里的 birth_time 应该传入平太阳时（标准时间），
        除非你确定 Ziwei MCP 没有启用自动修正。
        
        更新：现在 app_simplified.py 会自动将农历转换为阳历，
        并传入 calendar='solar' 给 Bazi MCP，但对于 Ziwei MCP，
        如果原始输入是农历，我们可能希望传递农历给它（如果它支持），
        或者我们已经转成了准确的阳历，就直接传阳历。
        目前策略：统一使用阳历 (solar)，因为我们在 Python 层做了统一转换。
        """
        resolved_location = await _resolve_location(location)
        args = {
            "name": name,
            "birthDate": birth_date,
            "birthTime": birth_time,
            "gender": gender,
            "location": resolved_location,
            "timezone": timezone,
            "calendar": calendar,
        }
        return await self.call_tool("generate_chart", arguments=args)

    async def interpret_chart(
        self,
        chart_id: str,
        aspects: Optional[List[str]] = None,
        detail_level: str = "basic",
    ) -> Dict[str, Any]:
        args = {
            "chartId": chart_id,
            "aspects": aspects or ["personality", "career", "wealth"],
            "detailLevel": detail_level,
        }
        return await self.call_tool("interpret_chart", arguments=args)


def run_ziwei_tool_sync(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    client = ZiweiClient()
    return asyncio.run(client.call_tool(tool_name, arguments=arguments))
