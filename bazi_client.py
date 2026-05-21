import mcp
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.stdio import StdioServerParameters, stdio_client
import json
import base64
import asyncio
from typing import Dict, Any, Optional
import logging
from datetime import datetime
import os

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BaziClient:
    """八字数据获取客户端"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化八字客户端
        
        Args:
            api_key: Smithery API密钥，如果不提供则从环境变量获取
        """
        self.api_key = (api_key or os.getenv("MCP_BAZI_API_KEY") or os.getenv("SMITHERY_API_KEY") or "").strip()
        
        self.config = {}
        logger.info("BaziClient初始化完成")
        
    async def get_bazi_detail(self, birth_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取八字详细信息
        
        Args:
            birth_info: 出生信息字典，包含年月日时等信息
            
        Returns:
            包含八字详细信息的字典
        """
        try:
            logger.info(f"开始获取八字信息: {birth_info}")
            
            # 编码配置信息
            config_b64 = base64.b64encode(json.dumps(self.config).encode()).decode()

            if not self.api_key:
                server = StdioServerParameters(command="npx", args=["bazi-mcp"])
                async with stdio_client(server) as (read_stream, write_stream):
                    async with mcp.ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools_result = await session.list_tools()
                        available_tools = [t.name for t in tools_result.tools]
                        logger.info(f"可用工具: {', '.join(available_tools)}")
                        if "getBaziDetail" not in available_tools:
                            raise ValueError("getBaziDetail工具不可用")
                        result = await session.call_tool("getBaziDetail", arguments=birth_info)
                        logger.info("八字信息获取成功")
                        return self._parse_bazi_result(result.content)

            url = f"https://server.smithery.ai/@cantian-ai/bazi-mcp/mcp?config={config_b64}&api_key={self.api_key}"
            headers = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
                async with mcp.ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    available_tools = [t.name for t in tools_result.tools]
                    logger.info(f"可用工具: {', '.join(available_tools)}")
                    if "getBaziDetail" not in available_tools:
                        raise ValueError("getBaziDetail工具不可用")
                    result = await session.call_tool("getBaziDetail", arguments=birth_info)
                    logger.info("八字信息获取成功")
                    return self._parse_bazi_result(result.content)
                    
        except Exception as e:
            logger.error(f"获取八字信息失败: {str(e)}")
            logger.error(f"错误类型: {type(e)}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            raise
    
    async def get_bazi_details(self, birth_time: str, gender: int) -> Dict[str, Any]:
        """
        兼容性方法：根据出生时间和性别获取八字信息
        
        Args:
            birth_time: ISO格式的出生时间
            gender: 性别 (1=男, 0=女)
            
        Returns:
            八字信息字典
        """
        birth_info = {
            "solarDatetime": birth_time,
            "gender": gender
        }
        
        logger.info(f"🔮 MCP调用参数:")
        logger.info(f"   solarDatetime: {birth_time}")
        logger.info(f"   gender: {gender}")
        logger.info(f"   完整参数: {json.dumps(birth_info, ensure_ascii=False)}")
        
        return await self.get_bazi_detail(birth_info)
    
    async def connect(self):
        """
        兼容性方法：连接到MCP服务器
        """
        # 测试连接
        success = await self.test_connection()
        if not success:
            raise ConnectionError("无法连接到MCP服务器")
        logger.info("MCP客户端连接成功")
    
    def _parse_bazi_result(self, raw_result: Any) -> Dict[str, Any]:
        """
        解析八字结果数据
        
        Args:
            raw_result: 原始结果数据
            
        Returns:
            格式化的八字信息字典
        """
        try:
            # 处理MCP返回的内容格式
            if hasattr(raw_result, '__iter__') and not isinstance(raw_result, (str, dict)):
                # 如果是列表或其他可迭代对象，提取第一个元素
                if len(raw_result) > 0:
                    content_item = raw_result[0]
                    if hasattr(content_item, 'text'):
                        # 如果是TextContent对象
                        result_text = content_item.text
                    elif hasattr(content_item, 'content'):
                        result_text = content_item.content
                    else:
                        result_text = str(content_item)
                else:
                    result_text = str(raw_result)
            elif hasattr(raw_result, 'text'):
                # 如果是TextContent对象
                result_text = raw_result.text
            elif isinstance(raw_result, str):
                result_text = raw_result
            else:
                result_text = str(raw_result)
            
            # 尝试解析为JSON
            try:
                result_data = json.loads(result_text)
            except (json.JSONDecodeError, TypeError):
                # 如果不是JSON格式，直接使用文本
                result_data = {"text_result": result_text}
            
            # 标准化八字信息格式
            parsed_result = {
                "birth_time": result_data.get("birth_time", ""),
                "four_pillars": result_data.get("four_pillars", {}),
                "five_elements": result_data.get("five_elements", {}),
                "ten_gods": result_data.get("ten_gods", {}),
                "lunar_info": result_data.get("lunar_info", {}),
                "solar_terms": result_data.get("solar_terms", {}),
                "text_result": result_data.get("text_result", result_text),
                "raw_data": result_data,  # 保留原始数据
                "parsed_time": datetime.now().isoformat()
            }
            
            logger.info("八字结果解析完成")
            return parsed_result
            
        except Exception as e:
            logger.error(f"解析八字结果失败: {str(e)}")
            # 返回原始数据作为备选
            return {
                "raw_data": str(raw_result),
                "parsed_time": datetime.now().isoformat(),
                "parse_error": str(e)
            }
    
    async def test_connection(self) -> bool:
        """
        测试MCP连接是否正常
        
        Returns:
            连接是否成功
        """
        try:
            config_b64 = base64.b64encode(json.dumps(self.config).encode()).decode()

            if not self.api_key:
                server = StdioServerParameters(command="npx", args=["bazi-mcp"])
                async with stdio_client(server) as (read_stream, write_stream):
                    async with mcp.ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools_result = await session.list_tools()
                        tools = [t.name for t in tools_result.tools]
                        logger.info(f"连接测试成功，可用工具: {tools}")
                        return True

            url = f"https://server.smithery.ai/@cantian-ai/bazi-mcp/mcp?config={config_b64}&api_key={self.api_key}"
            headers = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            }
            async with streamablehttp_client(url, headers=headers) as (read_stream, write_stream, _):
                async with mcp.ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    tools = [t.name for t in tools_result.tools]
                    logger.info(f"连接测试成功，可用工具: {tools}")
                    return True
                    
        except Exception as e:
            logger.error(f"连接测试失败: {str(e)}")
            logger.error(f"错误类型: {type(e)}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            return False

# 便捷函数
async def get_bazi_analysis(birth_info: Dict[str, Any], api_key: str) -> Dict[str, Any]:
    """
    便捷函数：获取八字分析
    
    Args:
        birth_info: 出生信息
        api_key: API密钥
        
    Returns:
        八字分析结果
    """
    client = BaziClient(api_key)
    return await client.get_bazi_detail(birth_info)

# 示例使用
if __name__ == "__main__":
    async def main():
        # 测试用的出生信息
        test_birth_info = {
            "solarDatetime": "1990-05-15T14:30:00+08:00",  # ISO 8601格式
            "gender": 1  # 1表示男性，0表示女性
        }
        
        try:
            # 从环境变量获取API密钥
            client = BaziClient()
            
            # 测试连接
            print("测试MCP连接...")
            connection_ok = await client.test_connection()
            if not connection_ok:
                print("连接测试失败")
                return
            
            # 获取八字信息
            print("获取八字信息...")
            result = await client.get_bazi_detail(test_birth_info)
            
            print("八字分析结果:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
            # 如果有文本结果，单独显示
            if "text_result" in result and result["text_result"]:
                print("\n八字详细信息:")
                print(result["text_result"])
            
        except Exception as e:
            print(f"错误: {str(e)}")
    
    # 运行测试
    asyncio.run(main()) 
