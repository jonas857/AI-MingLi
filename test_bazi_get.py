import requests
import json

def test_bazi_get():
    url = "http://localhost:5002/api/bazi/get"
    
    # 模拟真太阳时参数 (假设经度 105.7)
    payload = {
        "name": "DebugUser",
        "gender": 0,
        "birth_date": "2002-05-10",
        "birth_time": "2002-05-10T10:03:00+08:00", # 真太阳时
        "calendar_type": "solar",
        "solar_time_applied": True,
        "longitude": 105.7
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        print(f"发送测试请求: {json.dumps(payload, ensure_ascii=False)}")
        response = requests.post(url, json=payload, headers=headers)
        print(f"状态码: {response.status_code}")
        print(f"响应: {response.text}")
    except Exception as e:
        print(f"请求异常: {e}")

if __name__ == "__main__":
    test_bazi_get()
