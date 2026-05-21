#!/usr/bin/env python3
"""
AI分析引擎模块
支持多AI模型协作分析，集成本地记忆系统，提供灵活的参数配置
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import time
import asyncio

# AI模型客户端
import openai
try:
    import google.generativeai as genai
except ImportError:
    genai = None
    print("⚠️  Google Generative AI未安装，Gemini功能将不可用")

# 导入记忆管理器
from memory_manager import BaziMemoryManager
from user_manager import MemoryType

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIModel(Enum):
    """AI模型枚举"""
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"

class AnalysisType(Enum):
    """分析类型枚举"""
    FULL = "full"                    # 完整分析
    DEEPSEEK_ONLY = "deepseek_only"  # 仅DeepSeek分析
    GEMINI_ONLY = "gemini_only"      # 仅Gemini分析
    COLLABORATIVE = "collaborative"   # 协作分析

@dataclass
class ModelConfig:
    """模型配置类"""
    model_name: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout: int = 30
    retry_count: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

@dataclass
class AnalysisResult:
    """分析结果类"""
    model: str
    content: str
    timestamp: str
    tokens_used: Optional[int] = None
    processing_time: Optional[float] = None
    confidence_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

class AIAnalyzer:
    """AI分析引擎"""
    
    def __init__(self, memory_manager: Optional[BaziMemoryManager] = None):
        """
        初始化AI分析引擎
        
        Args:
            memory_manager: 记忆管理器实例
        """
        self.memory_manager = memory_manager or BaziMemoryManager()

        deepseek_model = os.getenv("DEEPSEEK_MODEL") or os.getenv("DEEPSEEK_DIALOG_MODEL") or "deepseek-v4-pro"
        gemini_flash_model = os.getenv("GEMINI_FLASH_MODEL") or "gemini-3-flash-preview"
        
        # 模型配置
        self.model_configs = {
            AIModel.DEEPSEEK: ModelConfig(
                model_name=deepseek_model,
                temperature=0.3
            ),
            AIModel.GEMINI: ModelConfig(
                model_name=gemini_flash_model,
                temperature=0.7
            )
        }
        
        # 初始化客户端
        self._init_clients()
        
        logger.info("AI分析引擎初始化完成")
    
    def _init_clients(self):
        """初始化AI客户端"""
        # DeepSeek客户端
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            self.deepseek_client = openai.OpenAI(
                api_key=deepseek_key,
                base_url=os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com",
                max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES") or 0),
            )
            logger.info("✅ DeepSeek客户端初始化成功")
        else:
            self.deepseek_client = None
            logger.warning("⚠️  DeepSeek API密钥未配置")
        
        # Gemini客户端
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        google_base_url = os.getenv("GOOGLE_BASE_URL")
        
        if gemini_key:
            # 如果提供了GOOGLE_BASE_URL，使用OpenAI兼容的方式
            if google_base_url and google_base_url != "https://generativelanguage.googleapis.com":
                # 处理base_url，确保不会重复添加/chat/completions
                if google_base_url.endswith('/chat/completions'):
                    # 如果URL已经包含/chat/completions，移除它，因为OpenAI客户端会自动添加
                    base_url = google_base_url.replace('/chat/completions', '')
                    logger.info(f"✅ 自动修正base_url: {google_base_url} -> {base_url}")
                else:
                    base_url = google_base_url.rstrip("/")
                if not (base_url.endswith("/v1") or base_url.endswith("/v1beta")):
                    base_url = f"{base_url}/v1"
                
                logger.info(f"✅ 使用OpenAI兼容代理访问Gemini: {base_url}")
                self.gemini_openai_client = openai.OpenAI(
                    api_key=gemini_key,
                    base_url=base_url,
                    max_retries=int(os.getenv("GEMINI_RELAY_MAX_RETRIES") or 0),
                    default_headers={
                        "User-Agent": os.getenv("GEMINI_RELAY_USER_AGENT") or "curl/8.0.1",
                    },
                )
                self.gemini_model = None  # 将使用OpenAI兼容客户端
                self.use_gemini_via_openai = True
                logger.info("✅ Gemini客户端初始化成功（通过OpenAI兼容代理）")
            # 否则使用原生Google SDK
            elif genai:
                genai.configure(api_key=gemini_key)
                default_model = (os.getenv("GEMINI_FLASH_MODEL") or "gemini-3-flash-preview").strip()
                self.gemini_model = genai.GenerativeModel(self._normalize_gemini_model_name_for_native(default_model))
                self.gemini_openai_client = None
                self.use_gemini_via_openai = False
                logger.info("✅ Gemini客户端初始化成功")
            else:
                self.gemini_model = None
                self.gemini_openai_client = None
                self.use_gemini_via_openai = False
                logger.warning("⚠️  Google Generative AI库未安装")
        else:
            self.gemini_model = None
            self.gemini_openai_client = None
            self.use_gemini_via_openai = False
            logger.warning("⚠️  Gemini API密钥未配置（需要GEMINI_API_KEY或GOOGLE_API_KEY）")
    
    def update_model_config(self, model: AIModel, **kwargs):
        """
        更新模型配置
        
        Args:
            model: AI模型
            **kwargs: 配置参数
        """
        if model in self.model_configs:
            config = self.model_configs[model]
            for key, value in kwargs.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            logger.info(f"更新 {model.value} 模型配置: {kwargs}")
        else:
            logger.error(f"未知模型: {model}")
    
    def get_model_config(self, model: AIModel) -> ModelConfig:
        """获取模型配置"""
        return self.model_configs.get(model)

    def _normalize_gemini_model_name_for_native(self, model_name: str) -> str:
        s = (model_name or "").strip()
        if not s:
            return "gemini-3-flash-preview"
        if "-thinking" in s:
            s = s.split("-thinking", 1)[0].strip()
        return s
    
    async def analyze_with_memory(self, 
                                user_id: str,
                                prompt_template: str,
                                analysis_type: AnalysisType = AnalysisType.FULL,
                                context_limit: int = 5,
                                **kwargs) -> Dict[str, AnalysisResult]:
        """
        基于记忆进行AI分析
        
        Args:
            user_id: 用户ID
            prompt_template: 提示词模板
            analysis_type: 分析类型
            context_limit: 上下文记忆限制
            **kwargs: 额外参数
            
        Returns:
            分析结果字典
        """
        try:
            # 1. 从记忆中获取用户数据
            user_context = await self._get_user_context(user_id, context_limit)
            
            # 2. 构建分析提示词
            formatted_prompt = self._format_prompt_with_context(
                prompt_template, 
                user_context, 
                **kwargs
            )
            
            # 3. 执行AI分析
            results = {}
            
            if analysis_type == AnalysisType.FULL:
                # 完整分析：所有可用模型
                if self.deepseek_client:
                    results["deepseek"] = await self.analyze_with_deepseek(formatted_prompt)
                if self.gemini_model or self.gemini_openai_client:
                    results["gemini"] = await self.analyze_with_gemini(formatted_prompt)
                    
            elif analysis_type == AnalysisType.DEEPSEEK_ONLY and self.deepseek_client:
                results["deepseek"] = await self.analyze_with_deepseek(formatted_prompt)
                
            elif analysis_type == AnalysisType.GEMINI_ONLY and (self.gemini_model or self.gemini_openai_client):
                results["gemini"] = await self.analyze_with_gemini(formatted_prompt)
                
            elif analysis_type == AnalysisType.COLLABORATIVE:
                # 协作分析：先主分析，再辅助分析
                results = await self._collaborative_analysis(formatted_prompt, user_context)
            
            # 4. 存储分析结果到记忆
            if results:
                await self._store_analysis_results(user_id, results, user_context)
            
            return results
            
        except Exception as e:
            logger.error(f"AI分析失败: {str(e)}")
            raise
    
    async def _get_user_context(self, user_id: str, limit: int = 5) -> Dict[str, Any]:
        """获取用户上下文信息"""
        try:
            # 获取用户基本信息
            user_info = self.memory_manager.get_user_info(user_id)
            
            # 获取八字信息
            bazi_memories = self.memory_manager.search_user_memories_advanced(
                user_id=user_id,
                query="八字",
                memory_type=MemoryType.BAZI_INFO,
                min_importance=7,
                include_expired=False
            )
            
            # 获取历史分析结果
            analysis_memories = self.memory_manager.search_user_memories_advanced(
                user_id=user_id,
                query="分析",
                memory_type=MemoryType.ANALYSIS_RESULT,
                min_importance=6,
                include_expired=False
            )
            
            # 获取用户偏好
            preference_memories = self.memory_manager.search_user_memories_advanced(
                user_id=user_id,
                query="偏好",
                memory_type=MemoryType.USER_PREFERENCE,
                include_expired=False
            )
            
            context = {
                "user_info": user_info if user_info else {},
                "bazi_info": bazi_memories[:2] if bazi_memories else [],
                "previous_analysis": analysis_memories[:limit] if analysis_memories else [],
                "user_preferences": preference_memories[:3] if preference_memories else [],
                "context_timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"获取用户 {user_id} 上下文: 八字信息 {len(context['bazi_info'])} 条，"
                       f"历史分析 {len(context['previous_analysis'])} 条")
            
            return context
            
        except Exception as e:
            logger.error(f"获取用户上下文失败: {str(e)}")
            return {"user_info": None, "bazi_info": [], "previous_analysis": [], "user_preferences": []}
    
    def _format_prompt_with_context(self, 
                                   template: str, 
                                   context: Dict[str, Any], 
                                   **kwargs) -> str:
        """格式化带上下文的提示词"""
        try:
            # 提取八字信息
            bazi_summary = ""
            if context.get("bazi_info"):
                bazi_data = context["bazi_info"][0].get("content", "")
                bazi_summary = bazi_data[:500] + "..." if len(bazi_data) > 500 else bazi_data
            
            # 提取历史分析摘要
            history_summary = ""
            if context.get("previous_analysis"):
                recent_analysis = context["previous_analysis"][:2]
                history_summary = "\n".join([
                    f"- {analysis.get('content', '')[:200]}..."
                    for analysis in recent_analysis
                ])
            
            # 提取用户偏好
            preferences_summary = ""
            if context.get("user_preferences"):
                preferences = [pref.get("content", "") for pref in context["user_preferences"]]
                preferences_summary = "; ".join(preferences)
            
            # 格式化模板
            user_info = context.get("user_info", {})
            user_id = "unknown"
            if isinstance(user_info, dict):
                user_id = user_info.get("user_id", "unknown")
            elif hasattr(user_info, 'user_id'):
                user_id = user_info.user_id
            
            formatted_prompt = template.format(
                bazi_info=bazi_summary,
                history_summary=history_summary,
                user_preferences=preferences_summary,
                user_id=user_id,
                **kwargs
            )
            
            return formatted_prompt
            
        except Exception as e:
            logger.error(f"格式化提示词失败: {str(e)}")
            return template

    def _format_user_base_info(self, user_context: Dict[str, Any], bazi_info: Any = None) -> str:
        """格式化用户基本信息"""
        birth_time_str = ""
        name = "命主"
        gender_str = "未知"
        
        # 1. 优先尝试从 bazi_info 中提取真太阳时
        if isinstance(bazi_info, dict) and bazi_info.get("solar_time_applied"):
            birth_time_str = bazi_info.get("true_solar_time")
        
        # 2. 如果没有，从 user_context 中提取
        if not birth_time_str and isinstance(user_context, dict):
            # 优先使用真太阳时 (如果存在)
            if user_context.get("is_true_solar_time") and user_context.get("display_birth_time"):
                birth_time_str = user_context.get("display_birth_time")
            elif user_context.get("true_solar_time"):
                 birth_time_str = user_context.get("true_solar_time")
            else:
                birth_time_str = user_context.get("birth_time") or user_context.get("birth")
                
            name = user_context.get("name", "命主")
            gender = user_context.get("gender")
            if gender is not None:
                if isinstance(gender, int):
                    gender_str = "男" if gender == 1 else "女"
                else:
                    gender_str = str(gender)
        
        # 3. 如果还是没有，尝试从 bazi_info 中提取 (有些结构可能包含用户信息)
        if not birth_time_str and isinstance(bazi_info, dict) and "birth_time" in bazi_info:
             birth_time_str = bazi_info.get("birth_time")

        # 格式化时间
        formatted_time = birth_time_str
        if birth_time_str:
            try:
                # 尝试解析并格式化为更易读的形式
                dt = datetime.fromisoformat(birth_time_str.replace("Z", "+00:00"))
                formatted_time = dt.strftime("%Y年%m月%d日 %H时%M分")
            except Exception:
                pass

        base_info = f"性别：{gender_str}，出生时间：{formatted_time}"
        if name:
            base_info = f"姓名：{name}，{base_info}"
            
        return base_info
    
    async def analyze_with_deepseek(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> AnalysisResult:
        """
        使用DeepSeek进行分析
        
        Args:
            prompt: 分析提示词
            model_name: 要使用的模型名称，如果为None则使用默认配置
            
        Returns:
            分析结果
        """
        if not self.deepseek_client:
            logger.error("DeepSeek客户端未初始化")
            raise ConnectionError("DeepSeek client not initialized")
        
        start_time = time.time()
        try:
            config = self.get_model_config(AIModel.DEEPSEEK)
            model_to_use = model_name or config.model_name
            
            logger.info(f"使用DeepSeek模型 {model_to_use} 进行分析...")
            
            request_kwargs = {
                "model": model_to_use,
                "messages": [
                    {"role": "system", "content": "You are an experienced BaZi analysis assistant. Provide professional, accurate, and easy-to-understand readings."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": config.temperature if temperature is None else temperature,
                "top_p": config.top_p,
                "frequency_penalty": config.frequency_penalty,
                "presence_penalty": config.presence_penalty,
            }
            if max_tokens is not None:
                request_kwargs["max_tokens"] = max_tokens
            if timeout is not None:
                request_kwargs["timeout"] = timeout
            completion = await asyncio.to_thread(
                self.deepseek_client.chat.completions.create,
                **request_kwargs
            )
            
            end_time = time.time()
            choice = completion.choices[0]
            content = choice.message.content
            finish_reason = getattr(choice, "finish_reason", None)
            tokens_used = completion.usage.total_tokens if hasattr(completion, 'usage') else None
            
            result = AnalysisResult(
                model=f"deepseek:{model_to_use}",
                content=content,
                timestamp=datetime.now().isoformat(),
                tokens_used=tokens_used,
                processing_time=end_time - start_time,
                metadata={"completion_id": completion.id, "finish_reason": finish_reason}
            )
            
            logger.info(f"DeepSeek分析完成，耗时: {result.processing_time:.2f}s, Tokens: {tokens_used}, Finish: {finish_reason}")
            return result
            
        except Exception as e:
            logger.error(f"DeepSeek分析出错: {str(e)}")
            raise

    async def analyze_with_openai(self, prompt: str, model_name: Optional[str] = None) -> AnalysisResult:
        """OpenAI direct analysis is not configured in this simplified build."""
        raise ValueError("OpenAI analysis is not configured; use deepseek or gemini.")

    async def analyze_with_gemini(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> AnalysisResult:
        """
        使用Gemini进行分析

        Args:
            prompt: 分析提示词
            model_name: 要使用的模型名称，如果为None则使用默认配置

        Returns:
            分析结果
        """
        if not self.gemini_model and not self.gemini_openai_client:
            logger.error("Gemini客户端未初始化")
            raise ConnectionError("Gemini client not initialized")
        
        start_time = time.time()
        try:
            config = self.get_model_config(AIModel.GEMINI)
            final_model_name = model_name or config.model_name
            
            # 通过OpenAI兼容代理使用Gemini
            if self.use_gemini_via_openai and self.gemini_openai_client:
                logger.info(f"使用Gemini模型 {final_model_name} 进行分析（通过OpenAI兼容代理）...")
                temp = config.temperature if temperature is None else temperature
                max_tok = max_tokens
                
                # 注意：OpenAI客户端是同步的，这里使用同步调用
                try:
                    request_kwargs = {
                        "model": final_model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temp,
                        "top_p": config.top_p,
                    }
                    if max_tokens is not None:
                        request_kwargs["max_tokens"] = max_tokens
                    if timeout is not None:
                        request_kwargs["timeout"] = timeout
                    response = await asyncio.to_thread(
                        self.gemini_openai_client.chat.completions.create,
                        **request_kwargs
                    )
                except Exception:
                    fallback_model = self._normalize_gemini_model_name_for_native(final_model_name)
                    if fallback_model and fallback_model != final_model_name:
                        request_kwargs = {
                            "model": fallback_model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temp,
                            "top_p": config.top_p,
                        }
                        if max_tokens is not None:
                            request_kwargs["max_tokens"] = max_tokens
                        if timeout is not None:
                            request_kwargs["timeout"] = timeout
                        response = await asyncio.to_thread(
                            self.gemini_openai_client.chat.completions.create,
                            **request_kwargs
                        )
                        final_model_name = fallback_model
                    else:
                        raise
                
                choice = response.choices[0]
                content = choice.message.content
                finish_reason = getattr(choice, "finish_reason", None)
                tokens_used = response.usage.total_tokens if response.usage else None
                
                result = AnalysisResult(
                    model=f"gemini:{final_model_name}",
                    content=content,
                    timestamp=datetime.now().isoformat(),
                    tokens_used=tokens_used,
                    processing_time=time.time() - start_time,
                    metadata={"via_openai_proxy": True, "finish_reason": finish_reason}
                )
                
            # 使用原生Google SDK
            else:
                logger.info(f"使用Gemini模型 {final_model_name} 进行分析...")
                
                # 如果提供了model_name，则使用它，否则使用默认配置的模型
                model_to_use_obj = self.gemini_model
                if model_name:
                    model_to_use_obj = genai.GenerativeModel(self._normalize_gemini_model_name_for_native(model_name))

                # 使用同步调用，因为Google SDK的异步方法可能不稳定
                response = await asyncio.to_thread(model_to_use_obj.generate_content, prompt)
                content = response.text
                tokens_used = None 

                result = AnalysisResult(
                    model=f"gemini:{final_model_name}",
                    content=content,
                    timestamp=datetime.now().isoformat(),
                    tokens_used=tokens_used,
                    processing_time=time.time() - start_time,
                    metadata={"candidate_count": len(response.candidates)}
                )
            
            logger.info(f"Gemini分析完成，耗时: {result.processing_time:.2f}s, Tokens: {result.tokens_used}")
            return result

        except Exception as e:
            logger.error(f"Gemini分析出错: {str(e)}")
            raise

    async def _collaborative_analysis(self, prompt: str, context: Dict[str, Any]) -> Dict[str, AnalysisResult]:
        """协作分析模式"""
        results = {}
        
        try:
            # 第一步：主分析（优先DeepSeek）
            primary_result = None
            if self.deepseek_client:
                primary_result = await self.analyze_with_deepseek(prompt)
                results["primary"] = primary_result
            
            # 第二步：基于主分析结果进行辅助分析
            if primary_result and (self.gemini_model or self.gemini_openai_client):
                secondary_prompt = f"""
                基于以下初步分析结果，请提供补充性的深度解读：
                
                初步分析：
                {primary_result.content}
                
                请从以下角度补充分析：
                1. 对初步分析的验证和补充
                2. 潜在机遇和挑战的识别
                3. 具体的改运建议
                4. 重要时间节点提醒
                5. 生活指导建议
                
                请保持客观理性，避免过于绝对的预测。
                """
                
                secondary_result = await self.analyze_with_gemini(secondary_prompt)
                results["secondary"] = secondary_result
            
            logger.info(f"协作分析完成，生成 {len(results)} 个分析结果")
            return results
            
        except Exception as e:
            logger.error(f"协作分析失败: {str(e)}")
            return results
    
    async def _store_analysis_results(self, 
                                    user_id: str, 
                                    results: Dict[str, AnalysisResult],
                                    context: Dict[str, Any]):
        """存储分析结果到记忆系统"""
        try:
            # 构建分析结果数据
            analysis_data = {
                "analysis_time": datetime.now().isoformat(),
                "models_used": list(results.keys()),
                "context_summary": {
                    "bazi_info_count": len(context.get("bazi_info", [])),
                    "history_count": len(context.get("previous_analysis", [])),
                    "preferences_count": len(context.get("user_preferences", []))
                }
            }
            
            # 添加各模型的分析结果
            for model_name, result in results.items():
                analysis_data[f"{model_name}_analysis"] = result.content
                analysis_data[f"{model_name}_metadata"] = result.metadata
            
            # 存储到记忆系统
            self.memory_manager.store_analysis_result(
                user_id=user_id,
                analysis=analysis_data,
                expires_in_days=365
            )
            
            logger.info(f"分析结果已存储到记忆系统，用户: {user_id}")
            
        except Exception as e:
            logger.error(f"存储分析结果失败: {str(e)}")
    
    def get_available_models(self) -> List[str]:
        """获取可用的AI模型列表"""
        available = []
        if self.deepseek_client:
            available.append("deepseek")
        if self.gemini_model or self.gemini_openai_client:
            available.append("gemini")
        return available
    
    def get_model_status(self) -> Dict[str, Dict[str, Any]]:
        """获取模型状态信息"""
        status = {}
        
        for model in AIModel:
            model_name = model.value
            config = self.model_configs[model]
            
            if model == AIModel.DEEPSEEK:
                available = self.deepseek_client is not None
            elif model == AIModel.GEMINI:
                available = self.gemini_model is not None or self.gemini_openai_client is not None
            else:
                available = False
            
            status[model_name] = {
                "available": available,
                "config": config.to_dict(),
                "api_key_configured": bool(os.getenv(f"{model_name.upper()}_API_KEY"))
            }
        
        return status
    
    async def quick_analysis(self, 
                           user_id: str, 
                           question: str,
                           model: AIModel = AIModel.DEEPSEEK) -> AnalysisResult:
        """
        快速分析接口
        
        Args:
            user_id: 用户ID
            question: 分析问题
            model: 使用的AI模型
            
        Returns:
            分析结果
        """
        try:
            logger.info(f"用户 {user_id} 请求快速分析，使用模型: {model.value}")
            
            # 构建简化的提示词
            prompt = f"""
            用户问题：{question}
            
            请基于八字命理学知识，对用户的问题提供专业、准确、实用的分析和建议。
            请保持客观理性，避免过于绝对的预测。
            """
            
            # 根据模型类型选择分析方法
            if model == AIModel.DEEPSEEK:
                result = await self.analyze_with_deepseek(prompt)
            elif model == AIModel.GEMINI:
                result = await self.analyze_with_gemini(prompt)
            else:
                raise ValueError(f"不支持的模型类型: {model}")
            
            # 存储分析结果
            try:
                self.memory_manager.store_analysis_result(
                    user_id=user_id,
                    analysis_type="quick_analysis",
                    content=result.content,
                    metadata={
                        "question": question,
                        "model": result.model,
                        "timestamp": result.timestamp
                    }
                )
            except Exception as e:
                logger.warning(f"存储快速分析结果失败: {e}")
            
            logger.info(f"快速分析完成，模型: {result.model}")
            return result
            
        except Exception as e:
            logger.error(f"快速分析失败: {str(e)}")
            raise

    def analyze_sync(self, 
                    prompt: str,
                    model: str = "deepseek",
                    specific_model: Optional[str] = None,
                    temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """
        同步分析方法，支持多种AI模型
        
        Args:
            prompt: 分析提示词
            model: 模型类型 ("deepseek", "openai", "gemini")
            specific_model: 具体模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            分析结果字典
        """
        try:
            start_time = time.time()
            
            if model.lower() == "deepseek":
                if not self.deepseek_client:
                    raise ConnectionError("DeepSeek客户端未初始化")
                
                config = self.get_model_config(AIModel.DEEPSEEK)
                model_to_use = specific_model or config.model_name
                temp = temperature if temperature is not None else config.temperature
                max_tok = max_tokens
                
                logger.info(f"使用DeepSeek模型 {model_to_use} 进行同步分析...")
                
                request_kwargs = {
                    "model": model_to_use,
                    "messages": [
                        {"role": "system", "content": "You are an experienced BaZi analysis assistant. Provide professional, accurate, and easy-to-understand readings."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": temp,
                    "top_p": config.top_p,
                    "frequency_penalty": config.frequency_penalty,
                    "presence_penalty": config.presence_penalty,
                }
                if max_tok is not None:
                    request_kwargs["max_tokens"] = max_tok
                completion = self.deepseek_client.chat.completions.create(**request_kwargs)
                
                content = completion.choices[0].message.content
                tokens_used = completion.usage.total_tokens if hasattr(completion, 'usage') else None
                
            elif model.lower() == "gemini":
                if not self.gemini_model and not self.gemini_openai_client:
                    raise ConnectionError("Gemini客户端未初始化")
                
                config = self.get_model_config(AIModel.GEMINI)
                model_to_use = specific_model or config.model_name
                temp = temperature if temperature is not None else config.temperature
                max_tok = max_tokens
                
                logger.info(f"使用Gemini模型 {model_to_use} 进行同步分析...")
                
                # 通过OpenAI兼容代理使用Gemini
                if self.use_gemini_via_openai and self.gemini_openai_client:
                    logger.info(f"通过OpenAI兼容代理使用Gemini模型 {model_to_use}")
                    request_kwargs = {
                        "model": model_to_use,
                        "messages": [
                            {"role": "system", "content": "You are an experienced BaZi analysis assistant. Provide professional, accurate, and easy-to-understand readings."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": temp,
                        "top_p": config.top_p,
                    }
                    if max_tok is not None:
                        request_kwargs["max_tokens"] = max_tok
                    completion = self.gemini_openai_client.chat.completions.create(**request_kwargs)
                    
                    content = completion.choices[0].message.content
                    tokens_used = completion.usage.total_tokens if hasattr(completion, 'usage') else None
                    
                # 使用原生Google SDK
                else:
                    # 对于Gemini，使用指定的模型创建新实例
                    if specific_model:
                        model_obj = genai.GenerativeModel(specific_model)
                    else:
                        model_obj = self.gemini_model
                    
                    # Gemini同步调用
                    response = model_obj.generate_content(prompt)
                    content = response.text
                    tokens_used = None
                
            else:
                raise ValueError(f"不支持的模型类型: {model}")
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            result = {
                "model": f"{model}:{model_to_use}" if 'model_to_use' in locals() else model,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "tokens_used": tokens_used,
                "processing_time": processing_time
            }
            
            logger.info(f"{model}同步分析完成，耗时: {processing_time:.2f}s, Tokens: {tokens_used}")
            return result
            
        except Exception as e:
            logger.error(f"{model}同步分析失败: {str(e)}")
            raise

# 测试函数
async def test_ai_analyzer():
    """测试AI分析引擎"""
    print("🧠 测试AI分析引擎...")
    
    # 初始化分析器
    analyzer = AIAnalyzer()
    
    # 检查可用模型
    available_models = analyzer.get_available_models()
    print(f"可用模型: {available_models}")
    
    # 获取模型状态
    status = analyzer.get_model_status()
    for model, info in status.items():
        print(f"{model}: {'✅' if info['available'] else '❌'} (API密钥: {'✅' if info['api_key_configured'] else '❌'})")
    
    # 测试快速分析
    if available_models:
        try:
            test_user_id = "test_user_ai_analyzer"
            
            # 创建测试用户
            analyzer.memory_manager.create_or_get_user(
                identifier=test_user_id,
                username="AI分析测试用户"
            )
            
            # 添加测试八字信息
            test_bazi = {
                "raw_data": {
                    "性别": "男",
                    "八字": "庚午 辛巳 庚辰 癸未",
                    "生肖": "马",
                    "日主": "庚"
                }
            }
            analyzer.memory_manager.store_bazi_info(test_user_id, test_bazi)
            
            # 测试快速分析
            model = AIModel.DEEPSEEK if "deepseek" in available_models else AIModel(available_models[0])
            result = await analyzer.quick_analysis(
                user_id=test_user_id,
                question="我的事业运势如何？",
                model=model
            )
            
            print(f"✅ 快速分析测试成功")
            print(f"模型: {result.model}")
            print(f"处理时间: {result.processing_time:.2f}s")
            print(f"回答: {result.content[:200]}...")
            
            # 清理测试数据
            analyzer.memory_manager.user_manager.delete_user(test_user_id, soft_delete=False)
            
        except Exception as e:
            print(f"❌ 快速分析测试失败: {str(e)}")
    
    print("AI分析引擎测试完成")

if __name__ == "__main__":
    import asyncio
    
    # 加载环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # 运行测试
    asyncio.run(test_ai_analyzer())
