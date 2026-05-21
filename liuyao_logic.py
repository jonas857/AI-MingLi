import random
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any

# 六十四卦名称
HEXAGRAM_NAMES = [
    '乾为天', '坤为地', '水雷屯', '山水蒙', '水天需', '天水讼', '地水师', '水地比',
    '风天小畜', '天泽履', '地天泰', '天地否', '天火同人', '火天大有', '地山谦', '雷地豫',
    '泽雷随', '山风蛊', '地泽临', '风地观', '火雷噬嗑', '山火贲', '山地剥', '地雷复',
    '天雷无妄', '山天大畜', '山雷颐', '泽风大过', '坎为水', '离为火', '泽山咸', '雷风恒',
    '天山遁', '雷天大壮', '火地晋', '地火明夷', '风火家人', '火泽睽', '水山蹇', '雷水解',
    '山泽损', '风雷益', '泽天夬', '天风姤', '泽地萃', '地风升', '泽水困', '水风井',
    '泽火革', '火风鼎', '震为雷', '艮为山', '风山渐', '雷泽归妹', '雷火丰', '火山旅',
    '巽为风', '兑为泽', '风水涣', '水泽节', '风泽中孚', '雷山小过', '水火既济', '火水未济'
]

# 爻值对应的阴阳和动静
YAO_TYPES = {
    6: {'name': '老阴', 'symbol': '⚋', 'isMoving': True},  # 变爻
    7: {'name': '少阳', 'symbol': '⚊', 'isMoving': False}, # 静爻
    8: {'name': '少阴', 'symbol': '⚋', 'isMoving': False}, # 静爻
    9: {'name': '老阳', 'symbol': '⚊', 'isMoving': True}   # 变爻
}

def calculate_hexagram_number(yaos: List[int]) -> int:
    """根据爻值计算卦号（0-63）"""
    # 将爻值转换为二进制，老阴和少阴为0，老阳和少阳为1
    binary = ''
    for i in range(len(yaos) - 1, -1, -1):  # 从上爻到下爻
        binary += '1' if yaos[i] in [7, 9] else '0'
    return int(binary, 2)

def calculate_world_response(hexagram_number: int) -> Dict[str, int]:
    """计算世应位置（简化算法）"""
    world_yao = (hexagram_number % 6) + 1
    if world_yao == 6:
        response_yao = 3
    elif world_yao == 5:
        response_yao = 2
    elif world_yao == 4:
        response_yao = 1
    else:
        response_yao = world_yao + 3
    return {'worldYao': world_yao, 'responseYao': response_yao}

def build_yaos_from_trigrams(upper: int, lower: int) -> List[int]:
    """根据八卦数构建六爻"""
    # 八卦对应的三爻模式 (7=阳爻, 8=阴爻)
    trigram_patterns = {
        1: [7, 7, 7], # 乾
        2: [8, 8, 8], # 坤
        3: [7, 8, 8], # 震
        4: [8, 7, 8], # 巽
        5: [8, 7, 7], # 坎
        6: [7, 8, 7], # 离
        7: [8, 8, 7], # 艮
        8: [7, 7, 8]  # 兑
    }
    lower_yaos = trigram_patterns.get(lower, [7, 7, 7])
    upper_yaos = trigram_patterns.get(upper, [7, 7, 7])
    return lower_yaos + upper_yaos

def generate_hexagram_coins(divination_time_ganzhi: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """三钱起卦法"""
    yaos = []
    yao_types_list = []
    symbols = []
    coin_details = []

    for i in range(6):
        heads = random.randint(0, 3)  # 0-3个正面 (Python random.randint is inclusive)
        # Note: TS logic was Math.floor(Math.random() * 4), which is 0,1,2,3. 
        # But wait, coin toss logic usually is: 3 coins.
        # Each coin is Head(3) or Tail(2). 
        # Sum: 
        # 3H = 9 (Old Yang)
        # 2H+1T = 8 (Young Yin)
        # 1H+2T = 7 (Young Yang)
        # 3T = 6 (Old Yin)
        # The TS logic `heads = Math.floor(Math.random() * 4)` simulates the *result* distribution?
        # Let's stick to the TS implementation for consistency:
        # heads in [0, 3]. tails = 3 - heads.
        # yaoValue = heads * 3 + tails * 2
        # If heads=3, val=9 (Old Yang). If heads=0, val=6 (Old Yin).
        # If heads=1, val=3+4=7 (Young Yang). If heads=2, val=6+2=8 (Young Yin).
        # Probability:
        # P(3H) = 1/8. P(0H)=1/8. P(1H)=3/8. P(2H)=3/8.
        # Math.random()*4 gives uniform distribution 0,1,2,3. This is NOT correct for 3 coins probability.
        # But the TS code uses it. I will replicate the TS logic exactly as requested ("reference...").
        # TS: `Math.floor(Math.random() * 4)` -> 0, 1, 2, 3 with equal probability?
        # If so, 6, 7, 8, 9 are equally likely. This is non-standard but I will follow the TS code "implementation".
        # WAIT. TS `Math.random() * 4` is uniform.
        # Standard Liu Yao probabilities are different (6: 1/8, 9: 1/8, 7: 3/8, 8: 3/8).
        # If the TS code does uniform, it's a "simplified" or "buggy" implementation.
        # Given the task is to "incorporate... referencing the algorithm list", I should probably stick to the TS logic
        # OR fix it if I want to be a "powerful code assistant".
        # The prompt says "based on the warehouse current implementation... archive".
        # So I should follow the TS implementation.
        
        heads = random.choice([0, 1, 2, 3]) # Uniform distribution to match TS `Math.floor(Math.random() * 4)`
        tails = 3 - heads
        yao_value = heads * 3 + tails * 2

        yaos.append(yao_value)
        
        yao_type = YAO_TYPES[yao_value]
        yao_types_list.append(yao_type['name'])
        symbols.append(yao_type['symbol'])
        
        coin_details.append({
            'throw': i + 1,
            'heads': heads,
            'tails': tails,
            'yaoValue': yao_value,
            'yaoType': yao_type['name']
        })

    original_number = calculate_hexagram_number(yaos)
    
    moving_lines = []
    for index, yao in enumerate(yaos):
        if YAO_TYPES[yao]['isMoving']:
            moving_lines.append(index + 1)
            
    changed_hexagram = None
    if moving_lines:
        changed_yaos = []
        for index, yao in enumerate(yaos):
            if (index + 1) in moving_lines:
                # 6->7, 9->8
                new_yao = 7 if yao == 6 else (8 if yao == 9 else yao)
                changed_yaos.append(new_yao)
            else:
                changed_yaos.append(yao)
        
        changed_number = calculate_hexagram_number(changed_yaos)
        changed_yao_types = [YAO_TYPES[y]['name'] for y in changed_yaos]
        changed_symbols = [YAO_TYPES[y]['symbol'] for y in changed_yaos]
        
        changed_hexagram = {
            'number': changed_number,
            'name': HEXAGRAM_NAMES[changed_number],
            'yaos': changed_yaos,
            'yaoTypes': changed_yao_types,
            'symbols': changed_symbols
        }

    world_response = calculate_world_response(original_number)
    
    return {
        'id': f"liuyao_{int(datetime.now().timestamp() * 1000)}",
        'timestamp': int(datetime.now().timestamp() * 1000),
        'method': 'coins',
        'divinationTime': divination_time_ganzhi,
        'originalHexagram': {
            'number': original_number,
            'name': HEXAGRAM_NAMES[original_number],
            'yaos': yaos,
            'yaoTypes': yao_types_list,
            'symbols': symbols
        },
        'changedHexagram': changed_hexagram,
        'movingLines': moving_lines,
        'worldYao': world_response['worldYao'],
        'responseYao': world_response['responseYao']
    }

def generate_plum_blossom_hexagram(year: int, month: int, day: int, hour: int, 
                                 question: Optional[str] = None,
                                 divination_time_ganzhi: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """梅花易数起卦法"""
    upper_sum = (year + month + day) % 8 or 8
    lower_sum = (year + month + day + hour) % 8 or 8
    moving_line_pos = ((year + month + day + hour) % 6) or 6
    
    upper_trigram = upper_sum
    lower_trigram = lower_sum
    
    yaos = build_yaos_from_trigrams(upper_trigram, lower_trigram)
    
    # 设置动爻
    original_yaos = list(yaos)
    # TS logic: originalYaos[movingLinePos - 1] = originalYaos[movingLinePos - 1] === 7 ? 9 : 6;
    idx = moving_line_pos - 1
    original_yaos[idx] = 9 if original_yaos[idx] == 7 else 6
    
    original_number = calculate_hexagram_number(original_yaos)
    moving_lines = [moving_line_pos]
    
    changed_yaos = []
    for index, yao in enumerate(original_yaos):
        if (index + 1) == moving_line_pos:
            new_yao = 7 if yao == 6 else (8 if yao == 9 else yao)
            changed_yaos.append(new_yao)
        else:
            changed_yaos.append(yao)
            
    changed_number = calculate_hexagram_number(changed_yaos)
    
    original_hexagram = {
        'number': original_number,
        'name': HEXAGRAM_NAMES[original_number],
        'yaos': original_yaos,
        'yaoTypes': [YAO_TYPES[y]['name'] for y in original_yaos],
        'symbols': [YAO_TYPES[y]['symbol'] for y in original_yaos]
    }
    
    changed_hexagram = {
        'number': changed_number,
        'name': HEXAGRAM_NAMES[changed_number],
        'yaos': changed_yaos,
        'yaoTypes': [YAO_TYPES[y]['name'] for y in changed_yaos],
        'symbols': [YAO_TYPES[y]['symbol'] for y in changed_yaos]
    }
    
    world_response = calculate_world_response(original_number)
    
    return {
        'id': f"liuyao_plum_{int(datetime.now().timestamp() * 1000)}",
        'timestamp': int(datetime.now().timestamp() * 1000),
        'method': 'plum',
        'divinationTime': divination_time_ganzhi,
        'originalHexagram': original_hexagram,
        'changedHexagram': changed_hexagram,
        'movingLines': moving_lines,
        'worldYao': world_response['worldYao'],
        'responseYao': world_response['responseYao'],
        'question': question
    }

def format_hexagram(result: Dict[str, Any]) -> str:
    """格式化六爻卦象显示"""
    original = result['originalHexagram']
    changed = result.get('changedHexagram')
    moving_lines = result['movingLines']
    
    display = [f"本卦：{original['name']}"]
    
    # 显示爻象（从上到下）
    for i in range(5, -1, -1):
        position = i + 1
        is_moving = position in moving_lines
        symbol = original['symbols'][i]
        yao_name = ['初', '二', '三', '四', '五', '上'][i]
        yao_type = original['yaoTypes'][i]
        
        line_str = f"{yao_name}爻：{symbol} {yao_type}"
        if is_moving:
            line_str += " (动)"
        display.append(line_str)
        
    if changed:
        display.append(f"\n变卦：{changed['name']}")
        
    div_time = result.get('divinationTime')
    if div_time:
        # Assuming div_time structure matches simple dict or Bazi format
        # TS: {year, month, day, hour} (strings)
        y = div_time.get('year', '')
        m = div_time.get('month', '')
        d = div_time.get('day', '')
        h = div_time.get('hour', '')
        if y or m or d or h:
            display.append(f"\n起卦时间：{y}年 {m}月 {d}日 {h}时")
            
    display.append(f"\n世爻：{result['worldYao']}爻，应爻：{result['responseYao']}爻")
    
    return "\n".join(display)
