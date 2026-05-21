# -*- coding: utf-8 -*-
"""
真太阳时计算工具
用于根据经度修正平太阳时（标准时间）为真太阳时。
真太阳时 = 平太阳时 + 经度时差 + 真平太阳时差 (Equation of Time)
"""

import math
from datetime import datetime, timedelta

def calculate_true_solar_time(dt: datetime, longitude: float, timezone: float = 8.0) -> datetime:
    """
    计算真太阳时
    
    Args:
        dt: 标准时间 (datetime对象)
        longitude: 观测地经度 (东经为正，西经为负)
        timezone: 时区 (默认东八区 +8.0)
        
    Returns:
        修正后的真太阳时 (datetime对象)
    """
    # 1. 经度时差修正
    # 地球每小时转15度，每度4分钟
    # 标准经度：东八区为 120度
    standard_longitude = timezone * 15.0
    longitude_diff = longitude - standard_longitude
    longitude_correction_minutes = longitude_diff * 4.0
    
    # 2. 真平太阳时差 (Equation of Time, EOT) 修正
    # 使用近似公式计算 EOT
    # 参考: https://en.wikipedia.org/wiki/Equation_of_time
    day_of_year = dt.timetuple().tm_yday
    
    # B参数计算
    # B = (n - 81) * 360 / 365
    # n 为积日
    b = (day_of_year - 81) * 360 / 365
    b_rad = math.radians(b)
    
    # EOT公式 (分钟)
    # E = 9.87 * sin(2B) - 7.53 * cos(B) - 1.5 * sin(B)
    eot_minutes = 9.87 * math.sin(2 * b_rad) - 7.53 * math.cos(b_rad) - 1.5 * math.sin(b_rad)
    
    # 总修正量 (分钟)
    total_correction_minutes = longitude_correction_minutes + eot_minutes
    
    # 应用修正
    true_solar_time = dt + timedelta(minutes=total_correction_minutes)
    
    return true_solar_time

if __name__ == "__main__":
    # 测试用例
    test_cases = [
        # (时间, 经度, 说明)
        ("2024-02-04 12:00:00", 120.0, "杭州附近 (标准经度), 立春附近"),
        ("2024-02-04 12:00:00", 116.4, "北京 (116.4E)"),
        ("2024-02-04 12:00:00", 87.6, "乌鲁木齐 (87.6E)"),
        ("2024-07-01 12:00:00", 121.5, "上海 (121.5E), 夏至后"),
    ]
    
    print("=== 真太阳时计算测试 ===")
    for t_str, lon, desc in test_cases:
        dt = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
        tst = calculate_true_solar_time(dt, lon)
        diff = (tst - dt).total_seconds() / 60.0
        
        print(f"地点/说明: {desc}")
        print(f"  标准时间: {dt}")
        print(f"  经度: {lon}°E")
        print(f"  真太阳时: {tst}")
        print(f"  时差: {diff:.2f} 分钟")
        print("-" * 30)
