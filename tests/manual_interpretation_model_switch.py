import requests


def main():
    base = "http://127.0.0.1:5002"
    s = requests.Session()

    login_payload = {
        "name": "测试用户",
        "gender": 1,
        "birth_date": "1996-05-02",
        "birth_time": "16:15",
        "calendar_type": "solar",
        "location": {"province": "上海", "city": "上海", "district": "", "address": "上海上海"},
        "skip_bazi": True,
    }
    r = s.post(f"{base}/api/login", json=login_payload, timeout=30)
    print("login", r.status_code)
    if r.status_code != 200:
        print(r.text[:300])
        return

    bazi_info = {"raw_data": {"八字": "甲子 乙丑 丙寅 丁卯", "性别": "男"}}
    user_bg = {"name": "测试用户", "gender": 1, "birth_time": "1996-05-02T16:15:00+08:00"}

    for version in ("wisdom", "master"):
        payload = {"version": version, "dimension": "事业运势分析", "bazi_info": bazi_info, "user_background": user_bg}
        r = s.post(f"{base}/api/analysis/interpretation", json=payload, timeout=180)
        print("interpretation", version, r.status_code)
        try:
            data = r.json()
        except Exception:
            print(r.text[:500])
            continue
        if r.status_code != 200:
            print(data)
            continue
        print("model_used", data.get("models_used", {}))


if __name__ == "__main__":
    main()

