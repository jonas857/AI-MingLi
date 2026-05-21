import os


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


# 记忆系统配置
USE_LOCAL_VECTOR_MEMORY = True  # 是否使用本地向量记忆（基于numpy+openai）
DEBUG_MODE = _env_bool("DEBUG_MODE", True)
DEEPSEEK_ENABLED = _env_bool("DEEPSEEK_ENABLED", True)
GEMINI_ENABLED = _env_bool("GEMINI_ENABLED", True)
MCP_BAZI_ENABLED = _env_bool("ENABLE_MCP_BAZI", True)
MCP_ZIWEI_ENABLED = _env_bool("ENABLE_MCP_ZIWEI", False)
LOCAL_STORAGE_ENABLED = _env_bool("LOCAL_STORAGE_ENABLED", True)

SHARED_MEMORY_ENABLED = _env_bool("ENABLE_SHARED_MEMORY", True)
VECTOR_MEMORY_ENABLED = _env_bool("ENABLE_VECTOR_MEMORY", True)
ASYNC_ORGANIZER_ENABLED = _env_bool("ENABLE_ASYNC_ORGANIZER", True)

print(
    f"[功能开关] UseLocalVec:{USE_LOCAL_VECTOR_MEMORY} MCP:{MCP_BAZI_ENABLED} ZiweiMCP:{MCP_ZIWEI_ENABLED} SharedMemory:{SHARED_MEMORY_ENABLED} "
    f"VectorMemory:{VECTOR_MEMORY_ENABLED} AsyncOrganizer:{ASYNC_ORGANIZER_ENABLED}"
)
