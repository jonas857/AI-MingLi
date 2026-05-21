#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提示词工程模块 - 统一构建版
根据用户选择的风格和维度，动态构建统一的分析提示词。
"""

import json
from typing import Dict, Any, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)

MAX_SHARED_MEMORY_CHARS = 7000
MAX_USER_CONTEXT_CHARS = 700

class AnalysisStyle(Enum):
    """分析风格"""
    PROFESSIONAL = "professional"  # 专业版
    INTERPRETATION = "interpretation" # 解读版

# 1. 专业版基础预设
PROFESSIONAL_PRESET = """
你是一位深研中国传统命理学的权威大师，精通《渊海子平》《三命通会》《滴天髓》《子平真诠》《穷通宝鉴》《神峰通考》等核心典籍，并熟练掌握子平术、格局法、调候法、旺衰法、五行生克制化、十神精要等核心推算方法。你的分析必须：
引经据典，有理有据： 关键论断需明确引用所依据的古籍原文或核心理论原则。
术语精准，逻辑严谨： 使用规范的命理学专业术语，分析过程逻辑链条清晰完整。
方法明确： 清晰说明所使用的推算方法（如：此结论基于调候用神优先原则 / 此格局判定依据《子平真诠》的成格破格标准）。
系统全面： 分析需覆盖命盘的核心要素及其相互作用。
结论审慎： 基于命盘信息进行专业推断，避免过度解读或无依据的猜测。
请为命主提供专业、严谨、具有古籍理论支撑的命理分析与建议。
""".strip()

# 2. 解读版提示词预设
INTERPRETATION_PRESET = """
你是一位深谙中国传统命理学精髓，同时精通现代沟通的智慧导师。你不仅精通《渊海子平》《三命通会》《滴天髓》等古籍理论，更能：
化繁为简，通俗表达： 将深奥的命理术语和复杂格局，转化为清晰、易懂、生活化的语言，避免晦涩难懂。
融合新知，启迪心智： 在尊重命理学原理的基础上，有机融合现代心理学（如人格特质、行为模式、潜在动机分析）和东方哲学智慧（如阴阳平衡、顺应天道），为命主提供更深层次的自我认知和人生启发。
聚焦当下，正向引导： 分析应联系命主现实生活情境，着重指出性格优势、潜在挑战及建设性的发展建议，强调个人能动性和趋吉避凶的可能性。
温暖共情，鼓励为主： 传递信息时保持理解、支持和鼓励的态度。
请为命主提供一份既有专业深度，又易于理解、富有启发性且充满正向引导的命理解读报告。
""".strip()

# 3. 10个维度的具体分析要求
DIMENSION_INSTRUCTIONS = {
    "日元核心分析": "从日元角度分析命主的命盘核心，深入解析命主最核心的先天禀赋、能量特质、行为模式根基及人生潜在主题。",
    "天干十神分析": "分析年、月、日、时四天干所透十神（尤其是日干三围：月干、时干、日支藏干透出），着重描述命主在社交互动、工作场合中自然展现出的主要性格特征、行为方式、第一印象和显性能力。",
    "地支藏干分析": "分析四地支中的主气藏干及其代表的十神（特别是日支夫妻宫、月支提纲），深入解读命主不易察GLISH察的真实性格底色、深层动机、情感需求模式、安全感来源及价值观根基。",
    "五行生克分析": "清晰列出八字中五行（金木水火土）各自的数量（几个字）和力量强弱（需考虑地支藏干主气）分析五行之间生克关系是否顺畅？是否存在明显的亢旺（过强）、衰弱（过弱）、阻塞（相克无解） 或 战克（激烈冲突）？指出最关键的生克路径及其对命局的影响",
    "用神忌神分析": "明确指出命局的核心用神（调候用神、扶抑用神、通关用神等，需说明依据）和主要忌神。",
    "事业运势分析": "命主的事业运势如何，基于十神组合（如官杀、印枭、食伤、财星）、格局特点（如官印相生、食伤生财、杀印相生等），分析命主最适合的事业领域类型、核心竞争优势、潜在领导力/专业性/创造力特质。适合稳定发展还是开拓创业？贵人运如何？需注意哪些关键挑战（如比劫夺财竞争大、官杀混杂压力多）？并注意结合大运流年信息。",
    "感情婚姻分析": "命主的桃花运势如何？分析夫妻宫（日支）状态及十神（正财/偏财 for 男，正官/七杀 for 女），解读命主深层的感情需求、吸引的伴侣类型、关系互动模式",
    "健康状况分析": "命主的健康状况如何\n体质倾向： 根据五行过旺/过弱/受克的情况（木-肝胆/筋骨、火-心脑/血液、土-脾胃/皮肉、金-肺肠/呼吸、水-肾膀胱/泌尿），指出命主先天体质上的相对强项和薄弱环节。\n潜在隐患： 分析是否存在明显的五行冲克（如金木交战、水火相激）或特定十神组合（如枭神夺食）带来的健康风险信号。\n养生建议： 建议需要重点保养的脏腑系统和需要注意的生活习惯（如：土弱需注意饮食规律养脾胃；水过旺需防寒湿）。",
    "大运流年分析": "大运流年关键节点分析\n简述命主当前所处的大运（XX岁 - XX岁），分析该大运的核心特质（干支组合、五行力量变化）及其对命局整体运势（事业/财运/感情/健康）的主要影响方向。特别指出未来1-3年内（或用户关心的特定年份）的关键流年（如2025乙巳年），分析其与命局、大运的互动关系（吉凶应期），提示重要机遇、挑战或需注意的事项。",
    "综合建议": "总结与综合建议\n基于以上所有分析，提炼3-5条最核心的人生发展建议，涵盖性格扬长避短、事业方向聚焦、人际关系（贵人/感情）经营、健康养生重点、趋吉避凶策略（结合用神） 等方面。"
}

# 4. 追问模板
FOLLOWUP_TEMPLATE = """
基于之前对【{analysis_dimension}】的分析，回答用户的追问。

原始八字：
{bazi_info}

之前的分析摘要：
{previous_analysis}

用户追问：
{followup_question}

用户背景：
{user_context}

请严格根据用户的追问，提供针对性的补充说明和解答，保持与之前分析的风格一致。
""".strip()


class PromptBuilder:
    """提示词构建器"""

    def _truncate(self, text: Optional[str], max_chars: int) -> str:
        s = (text or "").strip()
        if not s:
            return ""
        if len(s) <= max_chars:
            return s
        return s[:max_chars].rstrip() + "…"

    def build_analysis_prompt(self,
                              style: AnalysisStyle,
                              dimension: str,
                              bazi_info: Dict[str, Any],
                              user_context: Dict[str, Any],
                              shared_memory_context: Optional[str] = None) -> str:
        """
        构建分析提示词。
        最终提示词 = (专业版预设 或 解读版预设) + 所选维度要求 + 八字信息 + 用户背景
        """
        if style == AnalysisStyle.PROFESSIONAL:
            base_preset = PROFESSIONAL_PRESET
        elif style == AnalysisStyle.INTERPRETATION:
            base_preset = INTERPRETATION_PRESET
        else:
            raise ValueError(f"不支持的分析风格: {style}")

        dimension_instruction = DIMENSION_INSTRUCTIONS.get(dimension)
        if not dimension_instruction:
            raise ValueError(f"不支持的分析维度: {dimension}")

        formatted_bazi = self._format_bazi_info(bazi_info)
        formatted_context = self._format_user_context(user_context)

        memory_block = ""
        if shared_memory_context:
            clipped = self._truncate(shared_memory_context, MAX_SHARED_MEMORY_CHARS)
            memory_block = f"\n\n--- 共享记忆 / 历史摘要 ---\n{clipped}"

        final_prompt = (
            f"{base_preset}\n\n"
            f"--- 八字信息 ---\n{formatted_bazi}\n\n"
            f"--- 用户背景 ---\n{formatted_context}\n\n"
            f"--- 分析要求 ---\n"
            f"请严格围绕【{dimension}】这个维度展开分析，具体要求如下：\n"
            f"{dimension_instruction}"
            f"{memory_block}"
        )

        # 监控提示词长度
        prompt_length = len(final_prompt)
        if prompt_length > 3000:
            logger.warning(
                "提示词过长：%s 字符；分段长度 base=%s bazi=%s user=%s dim=%s mem=%s",
                prompt_length,
                len(base_preset),
                len(formatted_bazi),
                len(formatted_context),
                len(dimension_instruction),
                len(memory_block),
            )
        
        return final_prompt.strip()

    def build_followup_prompt(self,
                              analysis_dimension: str,
                              bazi_info: Dict[str, Any],
                              previous_analysis: str,
                              followup_question: str,
                              user_context: Dict[str, Any],
                              shared_memory_context: Optional[str] = None) -> str:
        """构建追问提示词"""
        base = FOLLOWUP_TEMPLATE.format(
            analysis_dimension=analysis_dimension,
            bazi_info=self._format_bazi_info(bazi_info),
            previous_analysis=previous_analysis[:1500] + "..." if len(previous_analysis) > 1500 else previous_analysis,
            followup_question=followup_question,
            user_context=self._format_user_context(user_context)
        )
        if shared_memory_context:
            clipped = self._truncate(shared_memory_context, MAX_SHARED_MEMORY_CHARS)
            out = f"{base}\n\n--- 共享记忆 / 历史摘要 ---\n{clipped}".strip()
            if len(out) > 3500:
                logger.warning("追问提示词过长：%s 字符", len(out))
            return out
        return base

    def _format_bazi_info(self, bazi_info: Dict[str, Any]) -> str:
        """格式化八字信息 - 支持记忆系统模式"""
        if not bazi_info:
            return "暂无八字信息"
        
        # 检查是否是记忆系统模式
        if isinstance(bazi_info, dict) and bazi_info.get('memory_source'):
            # 记忆系统模式：直接使用记忆中的内容
            bazi_memories = bazi_info.get('bazi_memories', [])
            user_context = bazi_info.get('user_context', {})
            
            formatted_output = []
            if bazi_memories:
                formatted_output.append("=== 从记忆系统获取的八字信息 ===")
                for i, memory in enumerate(bazi_memories, 1):
                    formatted_output.append(f"记忆{i}：{memory}")
            
            if user_context:
                formatted_output.append("\n=== 用户基础信息 ===")
                for key, value in user_context.items():
                    if value:
                        formatted_output.append(f"{key}：{value}")
            
            return '\n'.join(formatted_output) if formatted_output else "记忆系统中暂无八字信息"
        
        # 原有的直接八字信息模式 - 简化处理
        if isinstance(bazi_info, dict):
            # 提取核心信息，避免冗余数据
            core_fields = []
            
            # 优先提取raw_data中的核心信息
            if 'raw_data' in bazi_info:
                raw_data = bazi_info['raw_data']
                if isinstance(raw_data, dict):
                    for key in ['八字', '四柱八字', '性别', '生肖', '日主', '阳历时间', '阴历时间']:
                        if key in raw_data and raw_data[key]:
                            core_fields.append(f"{key}：{raw_data[key]}")
            
            # 如果没有raw_data，尝试直接提取
            if not core_fields:
                for key in ['八字', '四柱八字', '性别', '生肖', '日主', 'bazi', 'zodiac', 'dayMaster']:
                    if key in bazi_info and bazi_info[key]:
                        display_key = {'bazi': '八字', 'zodiac': '生肖', 'dayMaster': '日主'}.get(key, key)
                        core_fields.append(f"{display_key}：{bazi_info[key]}")
            
            return '\n'.join(core_fields) if core_fields else "八字信息解析中..."
        
        # 兜底：字符串形式
        return str(bazi_info)[:200] + "..." if len(str(bazi_info)) > 200 else str(bazi_info)

    def _format_user_context(self, context: Dict[str, Any]) -> str:
        """格式化用户上下文"""
        if not context:
            return "无用户背景信息"
        s = "; ".join(f"{key}: {value}" for key, value in context.items() if value is not None and str(value).strip() != "")
        return self._truncate(s, MAX_USER_CONTEXT_CHARS) or "无用户背景信息"

# 全局实例
prompt_builder = PromptBuilder()

# 测试函数
def test_prompt_builder():
    """测试提示词构建器"""
    print("📝 测试统一构建版提示词系统...")

    test_bazi = {"八字": "庚午 辛巳 甲子 乙未", "性别": "男"}
    test_context = {"年龄": 30, "职业": "程序员"}
    
    # 1. 测试专业版提示词
    try:
        professional_prompt = prompt_builder.build_analysis_prompt(
            style=AnalysisStyle.PROFESSIONAL,
            dimension="事业运势分析",
            bazi_info=test_bazi,
            user_context=test_context
        )
        print(f"✅ 专业版 '事业运势分析' 提示词生成成功，长度: {len(professional_prompt)}")
        assert "权威大师" in professional_prompt
        assert "事业运势如何" in professional_prompt
        assert "庚午 辛巳 甲子 乙未" in professional_prompt
    except Exception as e:
        print(f"❌ 专业版提示词测试失败: {e}")

    # 2. 测试解读版提示词
    try:
        interpretation_prompt = prompt_builder.build_analysis_prompt(
            style=AnalysisStyle.INTERPRETATION,
            dimension="感情婚姻分析",
            bazi_info=test_bazi,
            user_context=test_context
        )
        print(f"✅ 解读版 '感情婚姻分析' 提示词生成成功，长度: {len(interpretation_prompt)}")
        assert "智慧导师" in interpretation_prompt
        assert "桃花运势如何" in interpretation_prompt
        assert "庚午 辛巳 甲子 乙未" in interpretation_prompt
    except Exception as e:
        print(f"❌ 解读版提示词测试失败: {e}")
        
    # 3. 测试追问提示词
    try:
        followup_prompt = prompt_builder.build_followup_prompt(
            analysis_dimension="事业运势分析",
            bazi_info=test_bazi,
            previous_analysis="你的事业发展潜力巨大，但需要注意防范小人。",
            followup_question="具体应该怎么防范小人呢？",
            user_context=test_context
        )
        print(f"✅ 追问提示词生成成功，长度: {len(followup_prompt)}")
        assert "防范小人" in followup_prompt
        assert "事业运势分析" in followup_prompt
    except Exception as e:
        print(f"❌ 追问提示词测试失败: {e}")

    # 4. 测试无效参数
    try:
        prompt_builder.build_analysis_prompt(
            style=AnalysisStyle.PROFESSIONAL,
            dimension="不存在的维度",
            bazi_info=test_bazi,
            user_context=test_context
        )
    except ValueError as e:
        print(f"✅ 无效维度测试成功: {e}")

    print("\n✅ 提示词系统测试完成")

if __name__ == "__main__":
    test_prompt_builder() 
