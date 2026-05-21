import requests
import json
import time

def verify_solar_time_logic():
    url = "http://localhost:5000/api/login"
    
    # 杭州 2024-02-04 12:00:00
    # 经度 120.1551 E
    # 预期真太阳时应约为 11:45-11:50 之间
    payload = {
        "name": "SolarVerifyUser",
        "gender": "male",
        "birth_date": "2024-02-04",
        "birth_time": "12:00",
        "calendar_type": "solar",
        "skip_bazi": True,
        "location": {
            "province": "浙江省",
            "city": "杭州市", 
            "district": ""
        }
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        print(f"发送测试请求: {json.dumps(payload, ensure_ascii=False)}")
        t0 = time.time()
        response = requests.post(url, json=payload, headers=headers)
        print(f"耗时: {time.time() - t0:.2f}s")
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"登录成功: {json.dumps(data, ensure_ascii=False)}")
            user_id = data.get("user_id")
            if user_id:
                print(f"获取到 UserID: {user_id}")
                # 这里我们只能通过后端日志查看是否触发了真太阳时计算
                # 或者查看生成的 profile 是否有相关信息
        else:
            print(f"登录失败: {response.text}")
    except Exception as e:
        print(f"请求异常: {e}")

if __name__ == "__main__":
    verify_solar_time_logic()
