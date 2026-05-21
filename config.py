"""Runtime configuration helpers for the Bazi analysis app."""

from dataclasses import asdict, dataclass
import logging
import os
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class AIModelConfig:
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    deepseek_max_tokens: int = _env_int("DEEPSEEK_MAX_TOKENS", 8192)
    deepseek_temperature_analysis: float = _env_float("DEEPSEEK_TEMPERATURE_ANALYSIS", 0.3)
    deepseek_temperature_classic: float = _env_float("DEEPSEEK_TEMPERATURE_CLASSIC", 0.2)

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    google_base_url: str = os.getenv("GOOGLE_BASE_URL", "https://api.linkapi.org/v1")
    gemini_flash_model: str = os.getenv("GEMINI_FLASH_MODEL", "gemini-3-flash-preview-thinking-low")
    gemini_pro_model: str = os.getenv("GEMINI_PRO_MODEL", "gemini-3-pro-preview-thinking-high")
    gemini_max_tokens: int = _env_int("GEMINI_MAX_TOKENS", 65536)
    gemini_temperature_wisdom: float = _env_float("GEMINI_TEMPERATURE_WISDOM", 0.7)
    gemini_temperature_master: float = _env_float("GEMINI_TEMPERATURE_MASTER", 0.2)


@dataclass
class FeatureConfig:
    enable_mcp_bazi: bool = _env_bool("ENABLE_MCP_BAZI", True)
    enable_mcp_ziwei: bool = _env_bool("ENABLE_MCP_ZIWEI", False)
    enable_shared_memory: bool = _env_bool("ENABLE_SHARED_MEMORY", True)
    enable_vector_memory: bool = _env_bool("ENABLE_VECTOR_MEMORY", True)
    enable_async_organizer: bool = _env_bool("ENABLE_ASYNC_ORGANIZER", True)
    mock_ai_responses: bool = _env_bool("MOCK_AI_RESPONSES", False)


@dataclass
class ServerConfig:
    flask_env: str = os.getenv("FLASK_ENV", "development")
    flask_debug: bool = _env_bool("FLASK_DEBUG", True)
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _env_int("PORT", 5000)


@dataclass
class DataConfig:
    local_data_dir: str = os.getenv("LOCAL_DATA_DIR", "local_data")
    bazi_data_dir: str = os.getenv("BAZI_DATA_DIR", "local_data/bazi_data")
    analysis_data_dir: str = os.getenv("ANALYSIS_DATA_DIR", "local_data/analysis_data")
    sessions_dir: str = os.getenv("SESSIONS_DIR", "local_data/sessions")


@dataclass
class LogConfig:
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file: str = os.getenv("LOG_FILE", "logs/app.log")


@dataclass
class SecurityConfig:
    session_timeout: int = _env_int("SESSION_TIMEOUT", 3600)
    max_users: int = _env_int("MAX_USERS", 100)
    rate_limit: int = _env_int("RATE_LIMIT", 60)


class SystemConfig:
    def __init__(self):
        self.ai_model = AIModelConfig()
        self.features = FeatureConfig()
        self.server = ServerConfig()
        self.data = DataConfig()
        self.log = LogConfig()
        self.security = SecurityConfig()
        self._create_directories()
        self._setup_logging()

    def _create_directories(self) -> None:
        for directory in (
            self.data.local_data_dir,
            self.data.bazi_data_dir,
            self.data.analysis_data_dir,
            self.data.sessions_dir,
            "logs",
        ):
            os.makedirs(directory, exist_ok=True)

    def _setup_logging(self) -> None:
        logging.basicConfig(
            level=getattr(logging, self.log.log_level, logging.INFO),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    def validate_required_config(self) -> Dict[str, bool]:
        return {
            "deepseek_api_key": bool(self.ai_model.deepseek_api_key),
            "secret_key": bool(self.server.secret_key and self.server.secret_key != "dev-secret-key"),
        }

    def get_config_summary(self) -> Dict[str, Any]:
        return {
            "ai_models": {
                "deepseek_configured": bool(self.ai_model.deepseek_api_key),
                "openai_configured": bool(self.ai_model.openai_api_key),
                "google_configured": bool(self.ai_model.google_api_key),
                "deepseek_model": self.ai_model.deepseek_model,
                "gemini_flash_model": self.ai_model.gemini_flash_model,
                "gemini_pro_model": self.ai_model.gemini_pro_model,
            },
            "features": asdict(self.features),
            "server": asdict(self.server),
            "storage": asdict(self.data),
            "security": asdict(self.security),
        }

    def is_production(self) -> bool:
        return self.server.flask_env == "production"

    def get_ai_model_config(self, model_type: str) -> Dict[str, Any]:
        if model_type == "deepseek":
            return {
                "api_key": self.ai_model.deepseek_api_key,
                "base_url": self.ai_model.deepseek_base_url,
                "model": self.ai_model.deepseek_model,
                "max_tokens": self.ai_model.deepseek_max_tokens,
                "temperature_analysis": self.ai_model.deepseek_temperature_analysis,
                "temperature_classic": self.ai_model.deepseek_temperature_classic,
            }
        if model_type == "openai":
            return {
                "api_key": self.ai_model.openai_api_key,
                "base_url": self.ai_model.openai_base_url,
            }
        if model_type == "google":
            return {
                "api_key": self.ai_model.google_api_key,
                "base_url": self.ai_model.google_base_url,
                "flash_model": self.ai_model.gemini_flash_model,
                "pro_model": self.ai_model.gemini_pro_model,
                "max_tokens": self.ai_model.gemini_max_tokens,
                "temperature_wisdom": self.ai_model.gemini_temperature_wisdom,
                "temperature_master": self.ai_model.gemini_temperature_master,
            }
        return {}


config = SystemConfig()


def check_config_health() -> Dict[str, Any]:
    validation_results = config.validate_required_config()
    return {
        "status": "healthy" if all(validation_results.values()) else "warning",
        "validation_results": validation_results,
        "config_summary": config.get_config_summary(),
        "missing_configs": [key for key, ok in validation_results.items() if not ok],
    }


__all__ = [
    "config",
    "SystemConfig",
    "AIModelConfig",
    "FeatureConfig",
    "ServerConfig",
    "DataConfig",
    "LogConfig",
    "SecurityConfig",
    "check_config_health",
]
