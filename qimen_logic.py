from datetime import datetime
from typing import List, Dict, Any, Optional

# 基础常数定义
HEAVENLY_STEMS = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
EARTHLY_BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']

NINE_STARS = [
    '天蓬', '天芮', '天冲', '天辅', '天禽', '天心', '天柱', '天任', '天英'
]

EIGHT_DOORS = [
    '休门', '死门', '伤门', '杜门', '中门', '开门', '惊门', '生门', '景门'
]

EIGHT_DEITIES = [
    '值符', '腾蛇', '太阴', '六合', '白虎', '玄武', '九地', '九天'
]

# 九宫位置定义（洛书排列）
NINE_PALACES = [
    {'position': 4, 'name': '四宫（巽）', 'direction': '东南'},
    {'position': 9, 'name': '九宫（离）', 'direction': '南'},
    {'position': 2, 'name': '二宫（坤）', 'direction': '西南'},
    {'position': 3, 'name': '三宫（震）', 'direction': '东'},
    {'position': 5, 'name': '五宫（中）', 'direction': '中央'},
    {'position': 7, 'name': '七宫（兑）', 'direction': '西'},
    {'position': 8, 'name': '八宫（艮）', 'direction': '东北'},
    {'position': 1, 'name': '一宫（坎）', 'direction': '北'},
    {'position': 6, 'name': '六宫（乾）', 'direction': '西北'}
]

def calculate_ganzhi_simplified(base_date: datetime) -> Dict[str, str]:
    """
    计算干支（简化版）
    实际应用应使用BaziClient获取准确干支
    """
    base_year = 1984 # 甲子年
    current_year = base_date.year
    year_offset = (current_year - base_year) % 60
    
    stem_index = year_offset % 10
    branch_index = year_offset % 12
    year = HEAVENLY_STEMS[stem_index] + EARTHLY_BRANCHES[branch_index]
    
    # 月干支（简化）
    month_stem_index = (stem_index * 2 + (base_date.month - 1)) % 10 # Note: TS used baseDate.getMonth() which is 0-indexed
    month_branch_index = (base_date.month + 1) % 12 # TS: (month + 2) % 12?
    # TS: (baseDate.getMonth() + 2) % 12. If Jan (0), index 2 (Yin). Correct.
    month = HEAVENLY_STEMS[month_stem_index] + EARTHLY_BRANCHES[month_branch_index]
    
    # 日干支（简化）
    # 确保日期计算时使用naive datetime以避免时区问题
    naive_base = base_date.replace(tzinfo=None) if base_date.tzinfo else base_date
    days_since_1900 = (naive_base - datetime(1900, 1, 1)).days
    day_stem_index = (days_since_1900 + 1) % 10 # 1900-1-1 was Jia Xu? Simplified...
    day_branch_index = (days_since_1900 + 1) % 12
    day = HEAVENLY_STEMS[day_stem_index] + EARTHLY_BRANCHES[day_branch_index]
    
    # 时干支
    hour_index = base_date.hour // 2
    hour_stem_index = (day_stem_index * 2 + hour_index) % 10
    hour = HEAVENLY_STEMS[hour_stem_index] + EARTHLY_BRANCHES[hour_index % 12]
    
    return {'year': year, 'month': month, 'day': day, 'hour': hour}

def determine_escape_type(date: datetime) -> str:
    """确定阳遁阴遁（简化：3-8月阳，9-2月阴）"""
    month = date.month
    if 3 <= month <= 8:
        return 'yang'
    else:
        return 'yin'

def calculate_bureau_number(date: datetime, escape_type: str) -> int:
    """计算局数（简化）"""
    month = date.month
    
    if escape_type == 'yang':
        # 阳遁：立春一七四...
        patterns = [1, 7, 4, 2, 8, 5, 3, 9, 6, 1, 7, 4]
        return patterns[month - 1]
    else:
        # 阴遁：立秋九三六...
        patterns = [9, 3, 6, 8, 2, 5, 7, 1, 4, 9, 3, 6]
        return patterns[month - 1]

def get_duty_chief_and_door(day: str, hour: str) -> Dict[str, str]:
    """获取值符值使（简化）"""
    day_stem = day[0]
    hour_stem = hour[0]
    
    stem_index = HEAVENLY_STEMS.index(day_stem)
    hour_stem_index = HEAVENLY_STEMS.index(hour_stem)
    
    duty_chief = NINE_STARS[stem_index % len(NINE_STARS)]
    duty_door = EIGHT_DOORS[hour_stem_index % len(EIGHT_DOORS)]
    
    return {'dutyChief': duty_chief, 'dutyDoor': duty_door}

def generate_palaces(bureau_number: int, escape_type: str, duty_chief: str, duty_door: str) -> List[Dict[str, Any]]:
    """生成九宫数据"""
    palaces = []
    
    # 地盘基础排列
    base_earth_stems = ['戊', '己', '庚', '辛', '壬', '癸', '丁', '丙', '乙']
    
    for i in range(9):
        palace = NINE_PALACES[i]
        
        earth_stem = base_earth_stems[i]
        
        # 天盘天干
        earth_stem_idx = HEAVENLY_STEMS.index(earth_stem)
        heaven_stem_index = (earth_stem_idx + bureau_number - 1) % 10
        heaven_stem = HEAVENLY_STEMS[heaven_stem_index]
        
        # 九星
        chief_index = NINE_STARS.index(duty_chief)
        star_index = (chief_index + i) % len(NINE_STARS)
        star = NINE_STARS[star_index]
        
        # 八门
        door_index = EIGHT_DOORS.index(duty_door)
        # TS logic: palace.position === 5 ? 4 : (doorIndex + i) % 8
        adjusted_door_index = 4 if palace['position'] == 5 else (door_index + i) % len(EIGHT_DOORS)
        door = EIGHT_DOORS[adjusted_door_index]
        
        # 八神
        deity = ''
        if palace['position'] == 5:
            deity = ''
        else:
            deity_index = i if i < 4 else i - 1
            deity = EIGHT_DEITIES[deity_index % len(EIGHT_DEITIES)]
            
        palaces.append({
            'position': palace['position'],
            'name': palace['name'],
            'direction': palace['direction'],
            'earthStem': earth_stem,
            'heavenStem': heaven_stem,
            'star': star,
            'door': door,
            'deity': deity,
            'isCenter': palace['position'] == 5
        })
        
    return palaces

def generate_key_points(chart_data: Dict[str, Any]) -> List[str]:
    """生成分析要点"""
    points = []
    
    points.append(f"当前为{'阳' if chart_data['escapeType'] == 'yang' else '阴'}遁{chart_data['bureauNumber']}局")
    points.append(f"值符为{chart_data['dutyChief']}，值使为{chart_data['dutyDoor']}")
    
    center_palace = next((p for p in chart_data['palaces'] if p['isCenter']), None)
    if center_palace:
        action = '生发' if '生' in center_palace['door'] else '谨慎'
        points.append(f"中宫{center_palace['star']}{center_palace['door']}，主事宜{action}")
        
    good_doors = ['开门', '休门', '生门']
    good_palaces = [p for p in chart_data['palaces'] if p['door'] in good_doors]
    if good_palaces:
        locs = "、".join([f"{p['direction']}方{p['door']}" for p in good_palaces])
        points.append(f"吉门位于：{locs}")
        
    return points

def generate_qimen_chart(date_time: Optional[datetime] = None, ganzhi_override: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """生成奇门遁甲盘"""
    dt = date_time or datetime.now()
    
    if ganzhi_override:
        ganzhi = ganzhi_override
    else:
        ganzhi = calculate_ganzhi_simplified(dt)
        
    escape_type = determine_escape_type(dt)
    bureau_number = calculate_bureau_number(dt, escape_type)
    
    duty = get_duty_chief_and_door(ganzhi['day'], ganzhi['hour'])
    
    palaces = generate_palaces(bureau_number, escape_type, duty['dutyChief'], duty['dutyDoor'])
    
    chart_data = {
        'id': f"qimen-{int(dt.timestamp() * 1000)}",
        'timestamp': int(dt.timestamp() * 1000),
        'dateTime': dt.isoformat(),
        'year': ganzhi['year'],
        'month': ganzhi['month'],
        'day': ganzhi['day'],
        'hour': ganzhi['hour'],
        'escapeType': escape_type,
        'bureauNumber': bureau_number,
        'dutyChief': duty['dutyChief'],
        'dutyDoor': duty['dutyDoor'],
        'palaces': palaces,
        'keyPoints': []
    }
    
    chart_data['keyPoints'] = generate_key_points(chart_data)
    
    return chart_data
