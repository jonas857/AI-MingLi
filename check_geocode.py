import requests
from typing import Dict, Any, Optional

def _geocode_location(query: str) -> Optional[Dict[str, Any]]:
    if not query:
        return None
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "bazi-mcp-client/1.0"}
    
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
        "countrycodes": "cn",  # 限制在中国
    }
    
    try:
        print(f"查询 URL: {url} ? {params}")
        resp = requests.get(url, params=params, headers=headers, timeout=6)
        print(f"响应状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"错误: {resp.text}")
            return None
        data = resp.json()
        print(f"响应数据: {data}")
    except Exception as e:
        print(f"异常: {e}")
        return None
    if not data:
        return None
    item = data[0] if isinstance(data, list) else data
    try:
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
        return {"latitude": lat, "longitude": lon}
    except (ValueError, TypeError):
        return None

if __name__ == "__main__":
    queries = [
        "内蒙古自治区 阿拉善盟 阿拉善左旗 中国",
        "阿拉善左旗",
        "Alashan Zuoqi"
    ]
    for q in queries:
        print(f"--- 测试查询: {q} ---")
        res = _geocode_location(q)
        print(f"结果: {res}\n")
