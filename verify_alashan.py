import requests
import json
import time

def verify_alashan_solar_time():
    url = "http://localhost:5002/api/login"
    
    # 阿拉善左旗 2002-05-10 11:00:00
    # 阿拉善左旗经度约 105.7度 (巴彦浩特镇)
    # 经度差：105.7 - 120 = -14.3度
    # 时差：-14.3 * 4 = -57.2分钟 (约 -1小时)
    # 预期真太阳时：约 10:03
    
    payload = {
        "name": "AlashanUser_TrueSolar",
        "gender": "female",
        "birth_date": "2002-05-10",
        "birth_time": "11:00",
        "calendar_type": "solar",
        "skip_bazi": False,
        "location": {
            "province": "内蒙古自治区",
            "city": "阿拉善盟", 
            "district": "阿拉善左旗",
            "address": "内蒙古自治区阿拉善盟阿拉善左旗"
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
            print(f"登录成功: {json.dumps(data, ensure_ascii=False, indent=2)}")
        else:
            print(f"登录失败: {response.text}")
    except Exception as e:
        print(f"请求异常: {e}")

if __name__ == "__main__":
    verify_alashan_solar_time()
