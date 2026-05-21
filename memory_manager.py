import os
from typing import Dict, Any, List, Optional
import json
import logging
from datetime import date, datetime, timedelta
import uuid
import re
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

# 导入用户管理器
from user_manager import UserManager, UserProfile, MemoryType, UserStatus
from feature_flags import SHARED_MEMORY_ENABLED, VECTOR_MEMORY_ENABLED
try:
    import numpy as np
except Exception:
    np = None
try:
    import openai
except Exception:
    openai = None
try:
    import portalocker
except Exception:
    portalocker = None

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MEMORY_EVENT_STATUSES = {
    "pending",
    "processing",
    "ready",
    "failed_retryable",
    "failed_final",
    "discarded",
}
MEMORY_EVENT_RETRY_DELAYS = (30, 120, 600)


def _memory_env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _memory_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

_LIUYAO_DOMAIN_TOKENS = (
    "六爻",
    "liuyao",
    "liuyao_chat",
    "\u934f\ue160\u57e2\u9357\u72b2\u5d2a",  # mojibake for 六爻占卜 in older route constants
)
_QIMEN_DOMAIN_TOKENS = (
    "奇门",
    "qimen",
    "qimen_chat",
    "\u6fc2\u56e9\u68ec\u95ac\u4f7a\u6573",  # mojibake for 奇门遁甲 in older route constants
)
_ZIWEI_DOMAIN_TOKENS = (
    "紫微",
    "ziwei",
    "ziwei_chat",
    "\u7ef1\ue0a2\u4e95\u93c2\u6941\u669f",  # mojibake for 紫微斗数 in older route constants
)


def _memory_domain_from_text(*parts: Any) -> Optional[str]:
    text = "|".join(str(part or "") for part in parts).lower()
    if any(token.lower() in text for token in _LIUYAO_DOMAIN_TOKENS):
        return "liuyao"
    if any(token.lower() in text for token in _QIMEN_DOMAIN_TOKENS):
        return "qimen"
    if any(token.lower() in text for token in _ZIWEI_DOMAIN_TOKENS):
        return "ziwei"
    return None

class LocalVectorMemory:
    def __init__(
        self,
        storage_dir: str = "local_data/vector_memory",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ):
        if np is None:
            raise RuntimeError("缺少numpy依赖，无法启用本地向量记忆。请安装numpy后重试。")
        if openai is None:
            raise RuntimeError("缺少openai依赖，无法启用本地向量记忆。请安装openai后重试。")
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

        self.base_url = self._normalize_base_url(
            base_url or os.getenv("EMBEDDINGS_BASE_URL") or "https://api.linkapi.org/v1"
        )
        self.api_key = (
            api_key
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("EMBEDDINGS_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.embedding_model = embedding_model or os.getenv("EMBEDDINGS_MODEL") or "text-embedding-v4"

        self._client = None
        if self.api_key:
            self._client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        key_source = (
            "arg"
            if api_key
            else "DASHSCOPE_API_KEY"
            if os.getenv("DASHSCOPE_API_KEY")
            else "EMBEDDINGS_API_KEY"
            if os.getenv("EMBEDDINGS_API_KEY")
            else "OPENAI_API_KEY"
            if os.getenv("OPENAI_API_KEY")
            else "none"
        )
        logger.info(
            f"LocalVectorMemory 初始化完成：base_url={self.base_url!r}, model={self.embedding_model!r}, api_key_source={key_source}"
        )

    def _normalize_base_url(self, base_url: str) -> str:
        url = base_url.strip()
        if url.endswith("/embeddings"):
            url = url[: -len("/embeddings")]
        return url.rstrip("/")

    def _paths(self, user_id: str) -> Dict[str, str]:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in user_id)
        return {
            "meta": os.path.join(self.storage_dir, f"{safe}.jsonl"),
            "vec": os.path.join(self.storage_dir, f"{safe}.npy"),
        }

    def _load(self, user_id: str) -> tuple[list[dict], Optional[Any]]:
        paths = self._paths(user_id)
        metas: list[dict] = []
        vecs: Optional[np.ndarray] = None

        if os.path.exists(paths["meta"]):
            with open(paths["meta"], "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        metas.append(json.loads(line))
                    except Exception:
                        continue

        if os.path.exists(paths["vec"]):
            try:
                vecs = np.load(paths["vec"])
            except Exception:
                vecs = None

        if vecs is not None and vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)

        if vecs is not None and len(metas) != vecs.shape[0]:
            return [], None

        return metas, vecs

    def _save(self, user_id: str, metas: list[dict], vecs: Any) -> None:
        paths = self._paths(user_id)
        tmp_meta = f"{paths['meta']}.{uuid.uuid4().hex}.tmp"
        with open(tmp_meta, "w", encoding="utf-8") as f:
            for m in metas:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        os.replace(tmp_meta, paths["meta"])

        tmp_vec = f"{paths['vec']}.{uuid.uuid4().hex}.tmp"
        np.save(tmp_vec, vecs)
        if not tmp_vec.endswith(".npy"):
            tmp_vec = f"{tmp_vec}.npy"
        os.replace(tmp_vec, paths["vec"])

    def _embed(self, text: str) -> Any:
        if not self._client:
            raise RuntimeError("Embedding客户端未配置，请设置EMBEDDINGS_API_KEY（或DASHSCOPE_API_KEY）。")
        text = (text or "").strip()
        if not text:
            raise ValueError("Embedding文本为空")
        resp = self._client.embeddings.create(model=self.embedding_model, input=text)
        vec = resp.data[0].embedding
        return np.asarray(vec, dtype=np.float32)

    def add(
        self,
        user_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        memory_id = (metadata or {}).get("memory_id") or f"vm_{uuid.uuid4().hex}"
        meta = {
            "memory_id": memory_id,
            "user_id": user_id,
            "text": text,
            "metadata": metadata or {},
            "created_at": datetime.now().isoformat(),
        }
        vec = self._embed(text)

        metas, vecs = self._load(user_id)
        if vecs is None:
            vecs = vec.reshape(1, -1)
            metas = [meta]
        else:
            vecs = np.vstack([vecs, vec.reshape(1, -1)])
            metas.append(meta)

        self._save(user_id, metas, vecs)
        return memory_id

    def upsert(
        self,
        user_id: str,
        memory_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        metas, vecs = self._load(user_id)
        vec = self._embed(text)
        now = datetime.now().isoformat()

        meta = {
            "memory_id": memory_id,
            "user_id": user_id,
            "text": text,
            "metadata": metadata or {},
            "created_at": now,
        }

        if vecs is None or not metas:
            vecs = vec.reshape(1, -1)
            metas = [meta]
            self._save(user_id, metas, vecs)
            return memory_id

        idx = None
        for i, m in enumerate(metas):
            if m.get("memory_id") == memory_id:
                idx = i
                break

        if idx is None:
            vecs = np.vstack([vecs, vec.reshape(1, -1)])
            metas.append(meta)
        else:
            vecs[idx] = vec
            metas[idx] = meta

        self._save(user_id, metas, vecs)
        return memory_id

    def search(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        filter_type: Optional[str] = None,
        filter_dimension: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        metas, vecs = self._load(user_id)
        if vecs is None or not metas:
            return []

        q = self._embed(query)
        denom = (np.linalg.norm(vecs, axis=1) * (np.linalg.norm(q) + 1e-12)) + 1e-12
        scores = (vecs @ q) / denom

        candidates: list[tuple[int, float]] = []
        for i, meta in enumerate(metas):
            m = meta.get("metadata") or {}
            if filter_type and m.get("type") != filter_type:
                continue
            if filter_dimension and m.get("dimension") != filter_dimension:
                continue
            candidates.append((i, float(scores[i])))

        candidates.sort(key=lambda x: x[1], reverse=True)
        top = candidates[: max(0, limit)]
        results: List[Dict[str, Any]] = []
        for i, s in top:
            meta = metas[i]
            results.append(
                {
                    "memory": meta.get("text", ""),
                    "metadata": meta.get("metadata", {}),
                    "score": s,
                    "memory_id": meta.get("memory_id"),
                    "created_at": meta.get("created_at"),
                }
            )
        return results

    def ping(self, text: str = "ping") -> Dict[str, Any]:
        try:
            vec = self._embed(text)
            dim = int(vec.shape[0]) if hasattr(vec, "shape") and len(getattr(vec, "shape", [])) > 0 else None
            return {"ok": True, "dim": dim}
        except Exception as e:
            msg = str(e)
            if len(msg) > 500:
                msg = msg[:500] + "..."
            return {"ok": False, "error_type": type(e).__name__, "error": msg}


class MemoryContextBuilder:
    """Layered memory-context builder for user-facing astrological prompts."""

    def __init__(self, manager: "BaziMemoryManager"):
        self.manager = manager

    @staticmethod
    def _domain_from_dimension(dimension: str) -> str:
        return _memory_domain_from_text(dimension) or "bazi"

    @staticmethod
    def _item_domain(item: Dict[str, Any]) -> str:
        domain = str(item.get("domain") or "").lower()
        source_domain = str(((item.get("extra") or {}).get("source_domain")) or "").lower()
        event_type = str(((item.get("extra") or {}).get("event_type")) or "").lower()
        inferred = _memory_domain_from_text(domain, source_domain, event_type, item.get("dimension"))
        if inferred:
            return inferred
        if domain in ("global", ""):
            return "global"
        return domain or "global"

    def _item_allowed_for_domain(self, item: Dict[str, Any], context_domain: str) -> bool:
        item_domain = self._item_domain(item)
        if context_domain == "bazi":
            return item_domain in ("bazi", "global")
        return item_domain == context_domain

    def build(
        self,
        user_id: str,
        dimension: str,
        query: Optional[str] = None,
        task_type: str = "analysis",
        budget_chars: Optional[int] = None,
        vector_limit: int = 8,
    ) -> str:
        if not SHARED_MEMORY_ENABLED:
            return ""

        task = (task_type or "analysis").strip().lower()
        budget = int(budget_chars or (5200 if task == "chat" else 6500))
        budget = max(2200, min(budget, 7000))
        remaining = budget
        sections: List[str] = []

        def compact(text: str, max_len: int) -> str:
            s = (text or "").strip().replace("\r\n", "\n")
            if not s:
                return ""
            lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
            if lines:
                s = "\n".join(lines[:40])
            if len(s) > max_len:
                return s[:max_len].rstrip() + "..."
            return s

        def add_section(name: str, body: str, max_len: int) -> None:
            nonlocal remaining
            content = compact(body, min(max_len, max(0, remaining - len(name) - 16)))
            if not content or remaining <= 0:
                return
            block = f"<{name}>\n{content}\n</{name}>"
            if len(block) > remaining:
                block = block[:remaining].rstrip() + "..."
            sections.append(block)
            remaining -= len(block) + 2

        prefs = self.manager.get_memory_preferences(user_id)
        if prefs.get("memory_enabled") is False:
            return ""
        context_domain = self._domain_from_dimension(dimension)

        def matches_context_dimension(item: Dict[str, Any]) -> bool:
            item_dimension = str(item.get("dimension") or "")
            item_domain = str(item.get("domain") or "")
            if item_dimension == dimension or item_domain == dimension:
                return True
            if context_domain != "bazi" and self._item_domain(item) == context_domain:
                return True
            return False

        items = self.manager.get_memory_items(
            user_id,
            include_disabled=False,
            limit=200,
            allow_legacy_backfill=False,
        )
        emotional_enabled = prefs.get("emotional_memory_enabled", True)
        pinned = [
            it
            for it in items
            if it.get("pinned") and not (it.get("type") == "support_profile" and not emotional_enabled)
            and self._item_allowed_for_domain(it, context_domain)
        ]
        support_items = [
            it
            for it in items
            if it.get("type") == "support_profile"
            and self._item_allowed_for_domain(it, context_domain)
        ]
        domain_items = [
            it
            for it in items
            if it.get("type") == "domain_insight"
            and self._item_allowed_for_domain(it, context_domain)
            and matches_context_dimension(it)
        ]
        episode_items = [
            it
            for it in items
            if it.get("type") == "episode"
            and self._item_allowed_for_domain(it, context_domain)
            and matches_context_dimension(it)
        ]

        if pinned:
            lines = [self.manager.format_memory_item_text(it, max_len=240) for it in pinned[:5]]
            add_section("pinned_memories", "\n".join([x for x in lines if x]), 700)

        cf = self.manager.get_chart_facts(user_id) if context_domain == "bazi" else None
        if isinstance(cf, dict):
            chart_text = self.manager.format_chart_facts_context(cf, max_dayun_items=12)
            if chart_text:
                add_section(
                    "chart_facts",
                    f"[chart_fact][全局][ref=chart_fact_current]\n{chart_text}",
                    2600,
                )

        if emotional_enabled:
            profile_text = ""
            if context_domain == "bazi":
                profile_doc = self.manager.get_profile_doc(user_id)
                profile_text = self.manager.format_profile_text(profile_doc, max_len=520).strip()
            support_lines = [self.manager.format_memory_item_text(it, max_len=220) for it in support_items[:5]]
            if profile_text:
                profile_text = f"[profile][全局][ref=profile_current]\n[profile][鍏ㄥ眬][ref=profile_current]\n{profile_text}"
            support_body = "\n".join([x for x in [profile_text] + support_lines if x])
            add_section("support_profile", support_body, 760 if task == "chat" else 620)

        latest = ""
        if context_domain == "bazi":
            latest = self.manager.get_latest_dimension_insight(user_id=user_id, dimension=dimension).strip()
        domain_lines = [self.manager.format_memory_item_text(it, max_len=260) for it in domain_items[:3]]
        domain_body = "\n".join([x for x in [latest] + domain_lines if x])
        if domain_body:
            add_section("domain_insights", f"[insight][{dimension}]\n{domain_body}", 760)

        if episode_items:
            ep_lines = [self.manager.format_memory_item_text(it, max_len=260) for it in episode_items[:4]]
            add_section("episodes", "\n".join([x for x in ep_lines if x]), 620 if task == "chat" else 520)

        if self.manager.vector_memory and remaining > 260:
            vector_body = self._build_vector_supplement(user_id, dimension, query, vector_limit, remaining, context_domain)
            add_section("vector_supplement", vector_body, remaining)

        if not sections:
            return ""
        instruction = (
            "Use this memory only as background. The current user message has priority. "
            "Do not reveal internal refs, ids, or memory labels directly."
        )
        return "<memory_context>\n" + "\n\n".join(sections) + f"\n\n<instruction>{instruction}</instruction>\n</memory_context>"

    def _build_vector_supplement(
        self,
        user_id: str,
        dimension: str,
        query: Optional[str],
        limit: int,
        max_len: int,
        context_domain: str,
    ) -> str:
        q = query or f"{dimension} user concern advice chart facts"
        try:
            results = self.manager.vector_memory.search(user_id=user_id, query=q, limit=limit)
        except Exception:
            return ""
        lines: List[str] = []
        seen = set()
        for r in results:
            md = r.get("metadata") or {}
            t = md.get("type") or "memory"
            if t in ("chart_fact", "profile"):
                continue
            vector_domain = str(md.get("domain") or "").lower()
            vector_dimension = str(md.get("dimension") or "")
            inferred_domain = self._domain_from_dimension(vector_dimension)
            if context_domain != "bazi":
                if vector_domain != context_domain and inferred_domain != context_domain:
                    continue
            elif vector_domain in ("liuyao", "qimen", "ziwei") or inferred_domain in ("liuyao", "qimen", "ziwei"):
                continue
            mid = (r.get("memory_id") or "").strip()
            if mid and mid in seen:
                continue
            if mid:
                seen.add(mid)
            text = (r.get("memory") or "").strip()
            if not text:
                continue
            if len(text) > 300:
                text = text[:300].rstrip() + "..."
            lines.append(f"[{t}][{md.get('dimension') or dimension}] {text}")
            if len("\n".join(lines)) >= max_len:
                break
        return "\n".join(lines).strip()


class BaziMemoryManager:
    """八字记忆管理器 - 集成用户管理和高级功能"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, user_data_dir: str = "user_data"):
        """
        初始化记忆管理器
        
        Args:
            config: 保留的兼容参数，当前使用本地文件和本地向量记忆
            user_data_dir: 用户数据存储目录
        """
        # 初始化用户管理器
        self.user_manager = UserManager(user_data_dir)
        if VECTOR_MEMORY_ENABLED:
            try:
                self.vector_memory = LocalVectorMemory()
            except Exception as e:
                self.vector_memory = None
                logger.warning(f"本地向量记忆不可用，将跳过向量检索与写入: {e}")
        else:
            self.vector_memory = None
        self.context_builder = MemoryContextBuilder(self)
        self._legacy_backfill_in_progress = set()

        logger.info("BaziMemoryManager 初始化完成（本地向量记忆/文件存储）")

    def vector_ping(self, text: str = "ping") -> Dict[str, Any]:
        if not self.vector_memory:
            return {"ok": False, "error_type": "disabled", "error": "vector_memory is None"}
        if hasattr(self.vector_memory, "ping"):
            return self.vector_memory.ping(text=text)
        return {"ok": False, "error_type": "unsupported", "error": "vector_memory has no ping"}

    def _reload_users_if_needed(self):
        try:
            self.user_manager.users = self.user_manager._load_users()
        except Exception:
            return

    def _ensure_user(self, user_id: str, username: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        if self.user_manager.get_user(user_id):
            return
        self._reload_users_if_needed()
        if self.user_manager.get_user(user_id):
            return
        user = UserProfile(
            user_id=user_id,
            username=username,
            metadata=metadata or {},
        )
        self.user_manager.users[user_id] = user
        try:
            self.user_manager._save_users()
        except Exception:
            return

    def _safe_user_id(self, user_id: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in user_id)

    def _chart_facts_path(self, user_id: str) -> str:
        safe = self._safe_user_id(user_id)
        os.makedirs("local_data/chart_facts", exist_ok=True)
        return os.path.join("local_data", "chart_facts", f"{safe}_chart_facts.json")

    def get_chart_facts(self, user_id: str) -> Optional[Dict[str, Any]]:
        path = self._chart_facts_path(user_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                chart_facts = json.load(f)
            self._normalize_chart_facts_dayun(chart_facts)
            return chart_facts
        except Exception:
            return None

    def save_chart_facts(self, user_id: str, chart_facts: Dict[str, Any]) -> str:
        path = self._chart_facts_path(user_id)
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(chart_facts, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def _insights_path(self, user_id: str) -> str:
        safe = self._safe_user_id(user_id)
        os.makedirs("local_data/insights", exist_ok=True)
        return os.path.join("local_data", "insights", f"{safe}_insights.json")

    def _profile_path(self, user_id: str) -> str:
        safe = self._safe_user_id(user_id)
        os.makedirs("local_data/profile", exist_ok=True)
        return os.path.join("local_data", "profile", f"{safe}_profile.json")

    def get_profile_doc(self, user_id: str) -> Dict[str, Any]:
        path = self._profile_path(user_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = json.load(f)
                if isinstance(doc, dict):
                    doc.setdefault("schema_version", "profile_v1")
                    doc.setdefault("user_id", user_id)
                    doc.setdefault("background", {})
                    doc.setdefault("preferences", {})
                    doc.setdefault("tags", [])
                    doc.setdefault("feedback", [])
                    doc.setdefault("updated_at", doc.get("updated_at") or datetime.now().isoformat())
                    return doc
            except Exception:
                pass
        return {
            "schema_version": "profile_v1",
            "user_id": user_id,
            "background": {},
            "preferences": {},
            "tags": [],
            "feedback": [],
            "updated_at": datetime.now().isoformat(),
        }

    def save_profile_doc(self, user_id: str, doc: Dict[str, Any]) -> str:
        path = self._profile_path(user_id)
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def _memory_items_path(self, user_id: str) -> str:
        safe = self._safe_user_id(user_id)
        os.makedirs("local_data/memory_items", exist_ok=True)
        return os.path.join("local_data", "memory_items", f"{safe}_memory_v2.json")

    def get_memory_items_doc(self, user_id: str) -> Dict[str, Any]:
        path = self._memory_items_path(user_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = json.load(f)
                if isinstance(doc, dict):
                    doc.setdefault("schema_version", "memory_v2")
                    doc.setdefault("user_id", user_id)
                    doc.setdefault("items", [])
                    doc.setdefault("preferences", {})
                    prefs = doc["preferences"] if isinstance(doc.get("preferences"), dict) else {}
                    prefs.setdefault("memory_enabled", True)
                    prefs.setdefault("emotional_memory_enabled", True)
                    prefs.setdefault("disabled_types", [])
                    doc["preferences"] = prefs
                    return doc
            except Exception:
                pass
        return {
            "schema_version": "memory_v2",
            "user_id": user_id,
            "items": [],
            "preferences": {
                "memory_enabled": True,
                "emotional_memory_enabled": True,
                "disabled_types": [],
            },
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

    def save_memory_items_doc(self, user_id: str, doc: Dict[str, Any]) -> str:
        doc["schema_version"] = "memory_v2"
        doc["user_id"] = user_id
        doc["updated_at"] = datetime.now().isoformat()
        path = self._memory_items_path(user_id)
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def _archive_json_file(self, path: str, suffix: str) -> Optional[str]:
        if not os.path.exists(path):
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = f"{path}.{suffix}.{stamp}.bak"
        try:
            os.replace(path, archive_path)
            return archive_path
        except Exception:
            return None

    def invalidate_chart_dependent_memory(
        self,
        user_id: str,
        reason: str = "chart_changed",
        old_chart_signature: Optional[str] = None,
        new_chart_signature: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        result: Dict[str, Any] = {
            "reason": reason,
            "old_chart_signature": old_chart_signature,
            "new_chart_signature": new_chart_signature,
            "at": now,
            "archives": {},
            "deleted_user_memories": 0,
        }

        insights_path = self._insights_path(user_id)
        archived_insights = self._archive_json_file(insights_path, "chart_invalidated")
        if archived_insights:
            result["archives"]["insights"] = archived_insights
        self.save_insights_doc(
            user_id,
            {
                "schema_version": "insights_v1",
                "user_id": user_id,
                "dimensions": {},
                "invalidated_at": now,
                "invalidation_reason": reason,
                "old_chart_signature": old_chart_signature,
                "new_chart_signature": new_chart_signature,
            },
        )

        memory_doc = self.get_memory_items_doc(user_id)
        memory_items = memory_doc.get("items") if isinstance(memory_doc.get("items"), list) else []
        if memory_items:
            archived_memory = self._archive_json_file(self._memory_items_path(user_id), "chart_invalidated")
            if archived_memory:
                result["archives"]["memory_items"] = archived_memory
        self.save_memory_items_doc(
            user_id,
            {
                "schema_version": "memory_v2",
                "user_id": user_id,
                "items": [],
                "preferences": memory_doc.get("preferences") if isinstance(memory_doc.get("preferences"), dict) else {
                    "memory_enabled": True,
                    "emotional_memory_enabled": True,
                    "disabled_types": [],
                },
                "invalidated_at": now,
                "invalidation_reason": reason,
                "old_chart_signature": old_chart_signature,
                "new_chart_signature": new_chart_signature,
            },
        )

        for label, path in (("events", self._events_path(user_id)), ("events_state", self._events_state_path(user_id))):
            archived = self._archive_json_file(path, "chart_invalidated")
            if archived:
                result["archives"][label] = archived

        try:
            result["deleted_user_memories"] = self.user_manager.delete_user_memories(
                user_id,
                memory_type=MemoryType.ANALYSIS_RESULT,
            )
        except Exception:
            pass

        if self.vector_memory:
            try:
                paths = self.vector_memory._paths(user_id)
                for label, path in paths.items():
                    archived = self._archive_json_file(path, "chart_invalidated")
                    if archived:
                        result["archives"][f"vector_{label}"] = archived
            except Exception:
                pass

        return result

    def _brief_text(self, text: str, max_len: int = 260) -> str:
        s = self._sanitize_memory_content(text, max_len=max_len * 2)
        if not s:
            return ""
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) <= max_len:
            return s
        cut = max(s.rfind("。", 0, max_len), s.rfind("；", 0, max_len), s.rfind(".", 0, max_len))
        if cut >= 40:
            return s[: cut + 1].strip()
        return s[:max_len].rstrip() + "..."

    def _select_sentences(self, text: str, keywords: tuple[str, ...], limit: int = 3, max_len: int = 360) -> List[str]:
        s = self._sanitize_memory_content(text, max_len=5000)
        if not s:
            return []
        chunks = re.split(r"(?<=[。！？!?；;])\s*|\n+", s)
        picked: List[str] = []
        for chunk in chunks:
            c = chunk.strip(" \t-•*")
            if len(c) < 4:
                continue
            if keywords and not any(k in c for k in keywords):
                continue
            picked.append(self._brief_text(c, max_len=max_len))
            if len(picked) >= limit:
                return picked
        if not picked and chunks:
            for chunk in chunks:
                c = chunk.strip(" \t-•*")
                if len(c) >= 4:
                    picked.append(self._brief_text(c, max_len=max_len))
                if len(picked) >= limit:
                    break
        return picked

    def _format_legacy_profile_summary(self, doc: Dict[str, Any]) -> str:
        if not isinstance(doc, dict):
            return ""
        parts: List[str] = []
        prefs = doc.get("preferences") if isinstance(doc.get("preferences"), dict) else {}
        tags = doc.get("tags") if isinstance(doc.get("tags"), list) else []
        feedback = doc.get("feedback") if isinstance(doc.get("feedback"), list) else []
        if prefs:
            pref_parts = [f"{k}: {v}" for k, v in prefs.items() if v not in (None, "")]
            if pref_parts:
                parts.append("沟通偏好: " + "；".join(pref_parts[:6]))
        if tags:
            clean_tags = [str(t).strip() for t in tags if str(t).strip()]
            if clean_tags:
                parts.append("长期关注主题: " + "、".join(clean_tags[:10]))
        if feedback:
            snippets = []
            for fb in feedback[-5:]:
                if isinstance(fb, dict) and str(fb.get("text") or "").strip():
                    snippets.append(self._brief_text(str(fb.get("text") or ""), max_len=180))
            if snippets:
                parts.append("表达反馈: " + "；".join(snippets[-3:]))
        return "\n".join(parts).strip()

    def _iter_legacy_insight_currents(self, user_id: str) -> List[Dict[str, Any]]:
        doc = self.get_insights_doc(user_id)
        dims = doc.get("dimensions") if isinstance(doc, dict) else {}
        out: List[Dict[str, Any]] = []
        if not isinstance(dims, dict):
            return out
        for dimension, dim_doc in dims.items():
            if not isinstance(dim_doc, dict):
                continue
            versions = dim_doc.get("versions") if isinstance(dim_doc.get("versions"), dict) else {}
            for version, bucket in versions.items():
                if not isinstance(bucket, dict):
                    continue
                current = bucket.get("current")
                if isinstance(current, dict):
                    out.append({
                        "dimension": str(dimension),
                        "version": str(version),
                        "current": current,
                        "updated_at": current.get("updated_at") or bucket.get("updated_at"),
                        "importance": bucket.get("importance"),
                    })
        out.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        return out

    def _legacy_chat_paths(self, user_id: str) -> List[tuple[str, str, str]]:
        safe = self._safe_user_id(user_id)
        return [
            ("ziwei_chat", "紫微斗数", os.path.join("local_data", "ziwei_chat", f"{safe}_ziwei_chat.json")),
            ("liuyao_chat", "六爻占卜", os.path.join("local_data", "liuyao_chat", f"{safe}_liuyao_chat.json")),
            ("qimen_chat", "奇门遁甲", os.path.join("local_data", "qimen_chat", f"{safe}_qimen_chat.json")),
        ]

    def _load_legacy_chat_messages(self, path: str, kind: str) -> List[Dict[str, Any]]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if kind == "ziwei_chat" and isinstance(data, dict):
            messages = data.get("messages")
        else:
            messages = data
        return messages if isinstance(messages, list) else []

    def _legacy_chat_episode_summary(self, messages: List[Dict[str, Any]]) -> str:
        if not messages:
            return ""
        user_texts: List[str] = []
        assistant_texts: List[str] = []
        for msg in messages[-12:]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").lower()
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                user_texts.append(content)
            elif role in ("assistant", "ai"):
                assistant_texts.append(content)
        concern_keywords = ("担心", "焦虑", "压力", "迷茫", "希望", "想", "需要", "事业", "关系", "感情", "财", "工作")
        advice_keywords = ("建议", "适合", "可以", "优先", "避免", "留意", "方向", "选择", "行动", "保持")
        user_points = self._select_sentences("。".join(user_texts), concern_keywords, limit=2, max_len=180)
        advice_points = self._select_sentences("。".join(assistant_texts), advice_keywords, limit=2, max_len=180)
        lines: List[str] = []
        if user_points:
            lines.append("用户关切: " + "；".join(user_points))
        if advice_points:
            lines.append("建议方向: " + "；".join(advice_points))
        return "\n".join(lines).strip()

    def _organizer_model_name(self) -> str:
        return os.getenv("MEMORY_ORGANIZER_MODEL") or "deepseek-v4-flash"

    def _can_use_deepseek_organizer(self) -> bool:
        return bool(os.getenv("DEEPSEEK_API_KEY") and openai is not None)

    def _repair_organizer_json_with_model(
        self,
        client: Any,
        organizer_model: str,
        raw_text: str,
        schema_hint: str,
        max_tokens: int = 900,
    ) -> Optional[Dict[str, Any]]:
        raw = str(raw_text or "").strip()
        if not raw:
            return None
        try:
            resp = client.chat.completions.create(
                model=organizer_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Convert the user's text into one strict JSON object matching the schema. "
                            "Do not add markdown fences, comments, or explanatory text. "
                            "If the text contains multiple candidate objects, keep the most complete one."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "schema": schema_hint,
                                "text_to_convert": raw[:6000],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0,
                max_tokens=max_tokens,
            )
            return self._extract_json_object((resp.choices[0].message.content or "").strip())
        except Exception as e:
            logger.warning("Memory organizer JSON repair failed: %s", e)
            return None

    def _organize_memory_block_with_deepseek(
        self,
        source_type: str,
        target_type: str,
        dimension: str,
        raw_text: str,
        max_input_chars: int = 9000,
    ) -> Optional[Dict[str, Any]]:
        raw = self._sanitize_memory_content(raw_text, max_len=max_input_chars).strip()
        if not raw or not self._can_use_deepseek_organizer():
            return None

        organizer_model = self._organizer_model_name()
        deepseek_base = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com"
        try:
            client = openai.OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=deepseek_base)
            payload = {
                "source_type": source_type,
                "target_type": target_type,
                "dimension": dimension,
                "raw_text": raw,
            }
            resp = client.chat.completions.create(
                model=organizer_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是命理服务的长期记忆整理器。请先评估输入是否值得长期保存，再决定保存类型。"
                            "必须返回严格 JSON，字段：should_store(boolean), "
                            "memory_type(domain_insight|support_profile|episode|discard), "
                            "content(3-6条中文短要点数组), confidence(0-1), sensitivity(normal|sensitive), "
                            "merge_strategy(append|merge|replace|discard), reason, evidence_refs。"
                            "不要复制原文长段；不要保存 PIN/API key/密码/token；不要做医学或心理诊断。"
                            "命理分析优先保存结论、依据、建议；对话优先保存用户关切、情绪主题、已给建议、未完成问题。"
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.1,
                max_tokens=900,
            )
            text = (resp.choices[0].message.content or "").strip()
            obj = self._extract_json_object(text)
            if not isinstance(obj, dict):
                obj = self._repair_organizer_json_with_model(
                    client,
                    organizer_model,
                    text,
                    "should_store, memory_type, content, confidence, sensitivity, merge_strategy, reason, evidence_refs",
                    max_tokens=900,
                )
            assessment = self.normalize_memory_assessment(
                obj,
                fallback_type=target_type,
                evidence_refs=[],
            )
            if assessment:
                assessment["model"] = organizer_model
                assessment["ai_used"] = True
                return assessment
        except Exception as e:
            logger.warning("DeepSeek memory organize failed source=%s dimension=%s: %s", source_type, dimension, e)
            return None

    def _organize_or_fallback(
        self,
        source_type: str,
        target_type: str,
        dimension: str,
        raw_text: str,
        fallback_text: str,
        fallback_confidence: float = 0.55,
    ) -> Dict[str, Any]:
        organized = self._organize_memory_block_with_deepseek(
            source_type=source_type,
            target_type=target_type,
            dimension=dimension,
            raw_text=raw_text,
        )
        if organized:
            return organized
        fallback = self.normalize_memory_assessment(
            {
                "should_store": bool(fallback_text),
                "memory_type": target_type,
                "content": fallback_text,
                "confidence": fallback_confidence,
                "sensitivity": "normal",
                "merge_strategy": "merge",
                "reason": "local fallback",
            },
            fallback_type=target_type,
            evidence_refs=[],
        )
        if not fallback:
            fallback = {
                "should_store": False,
                "memory_type": "discard",
                "content": "",
                "confidence": fallback_confidence,
                "sensitivity": "normal",
                "merge_strategy": "discard",
                "reason": "empty fallback",
                "evidence_refs": [],
            }
        fallback["model"] = "local_fallback"
        fallback["ai_used"] = False
        return fallback

    def backfill_memory_items_from_legacy(self, user_id: str, force: bool = False) -> Dict[str, Any]:
        if not user_id:
            return {"backfilled": 0, "skipped": True}
        if user_id in self._legacy_backfill_in_progress:
            return {"backfilled": 0, "skipped": True, "reason": "in_progress"}
        doc = self.get_memory_items_doc(user_id)
        meta = doc.get("legacy_backfill") if isinstance(doc.get("legacy_backfill"), dict) else {}
        prefs = doc.get("preferences") if isinstance(doc.get("preferences"), dict) else {}
        if prefs.get("memory_enabled") is False:
            return {"backfilled": 0, "skipped": True, "reason": "memory_disabled"}
        if meta.get("completed") and not force:
            current_model = self._organizer_model_name()
            should_upgrade = self._can_use_deepseek_organizer() and (
                meta.get("organizer_model") != current_model
                or meta.get("ai_used") is not True
            )
            if not should_upgrade:
                return {"backfilled": 0, "skipped": True, "reason": "already_completed"}

        self._legacy_backfill_in_progress.add(user_id)
        written = 0
        ai_used = False
        try:
            profile_summary = self._format_legacy_profile_summary(self.get_profile_doc(user_id))
            if profile_summary:
                profile_org = self._organize_or_fallback(
                    source_type="legacy_profile",
                    target_type="support_profile",
                    dimension="全局",
                    raw_text=profile_summary,
                    fallback_text=profile_summary,
                    fallback_confidence=0.65,
                )
                ai_used = ai_used or bool(profile_org.get("ai_used"))
                if self.upsert_memory_item(
                    user_id,
                    {
                        "type": "support_profile",
                        "domain": "global",
                        "dimension": "全局",
                        "content": profile_org["content"],
                        "evidence_refs": ["legacy:profile"],
                        "confidence": profile_org["confidence"],
                        "sensitivity": profile_org["sensitivity"],
                        "model": profile_org["model"],
                        "dedupe_key": "legacy|support_profile|global|profile",
                    },
                ):
                    written += 1

            for row in self._iter_legacy_insight_currents(user_id):
                current = row.get("current")
                if not isinstance(current, dict):
                    continue
                raw_content = json.dumps(current, ensure_ascii=False)
                fallback_content = self.format_dimension_insight_text(current, max_len=5000)
                if not fallback_content:
                    continue
                insight_org = self._organize_or_fallback(
                    source_type="legacy_insight",
                    target_type="domain_insight",
                    dimension=str(row.get("dimension") or ""),
                    raw_text=raw_content,
                    fallback_text=fallback_content,
                    fallback_confidence=current.get("confidence") if isinstance(current.get("confidence"), (int, float)) else 0.6,
                )
                ai_used = ai_used or bool(insight_org.get("ai_used"))
                if self.upsert_memory_item(
                    user_id,
                    {
                        "type": "domain_insight",
                        "domain": "bazi",
                        "dimension": row.get("dimension"),
                        "content": insight_org["content"],
                        "evidence_refs": [f"legacy:insight:{row.get('dimension')}:{row.get('version')}"],
                        "confidence": insight_org["confidence"],
                        "sensitivity": insight_org["sensitivity"],
                        "model": insight_org["model"],
                        "extra": {"version": row.get("version")},
                        "dedupe_key": f"legacy|domain_insight|{row.get('dimension')}|{row.get('version')}",
                    },
                ):
                    written += 1

            for kind, dimension, path in self._legacy_chat_paths(user_id):
                messages = self._load_legacy_chat_messages(path, kind)
                summary = self._legacy_chat_episode_summary(messages)
                if not summary:
                    continue
                raw_messages = json.dumps(messages[-20:], ensure_ascii=False)
                chat_org = self._organize_or_fallback(
                    source_type=kind,
                    target_type="episode",
                    dimension=dimension,
                    raw_text=raw_messages,
                    fallback_text=summary,
                    fallback_confidence=0.55,
                )
                ai_used = ai_used or bool(chat_org.get("ai_used"))
                if self.upsert_memory_item(
                    user_id,
                    {
                        "type": "episode",
                        "domain": kind,
                        "dimension": dimension,
                        "content": chat_org["content"],
                        "evidence_refs": [f"legacy:{kind}"],
                        "confidence": chat_org["confidence"],
                        "sensitivity": chat_org["sensitivity"],
                        "model": chat_org["model"],
                        "dedupe_key": f"legacy|episode|{kind}",
                    },
                ):
                    written += 1

            final_doc = self.get_memory_items_doc(user_id)
            final_doc["legacy_backfill"] = {
                "completed": True,
                "updated_at": datetime.now().isoformat(),
                "written": written,
                "organizer_model": self._organizer_model_name(),
                "ai_used": ai_used,
            }
            self.save_memory_items_doc(user_id, final_doc)
            return {"backfilled": written, "skipped": False, "organizer_model": self._organizer_model_name(), "ai_used": ai_used}
        finally:
            self._legacy_backfill_in_progress.discard(user_id)

    def get_memory_preferences(self, user_id: str) -> Dict[str, Any]:
        doc = self.get_memory_items_doc(user_id)
        prefs = doc.get("preferences") if isinstance(doc, dict) else {}
        return prefs if isinstance(prefs, dict) else {}

    def update_memory_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
        doc = self.get_memory_items_doc(user_id)
        prefs = doc.setdefault("preferences", {})
        if not isinstance(prefs, dict):
            prefs = {}
            doc["preferences"] = prefs
        for key in ("memory_enabled", "emotional_memory_enabled"):
            if key in preferences:
                prefs[key] = bool(preferences.get(key))
        if "disabled_types" in preferences and isinstance(preferences.get("disabled_types"), list):
            prefs["disabled_types"] = [
                str(x).strip()
                for x in preferences.get("disabled_types", [])
                if str(x).strip()
            ][:20]
        self.save_memory_items_doc(user_id, doc)
        return prefs

    def _sanitize_memory_content(self, text: str, max_len: int = 1200) -> str:
        s = (text or "").strip()
        if not s:
            return ""
        s = re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "[redacted_api_key]", s)
        s = re.sub(r"(?i)(api[_ -]?key|secret|token|pin|password)\s*[:=]\s*\S+", r"\1: [redacted]", s)
        if len(s) > max_len:
            s = s[:max_len].rstrip() + "..."
        return s

    def format_assessed_memory_content(self, content: Any) -> str:
        if isinstance(content, list):
            lines = []
            for item in content:
                text = self._sanitize_memory_content(str(item or ""), max_len=360).strip(" \t-•*")
                if text:
                    lines.append(f"- {text}")
                if len(lines) >= 6:
                    break
            return "\n".join(lines)
        text = self._sanitize_memory_content(str(content or ""), max_len=1200)
        if not text:
            return ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) > 1:
            normalized = []
            for ln in lines[:6]:
                clean = ln.strip(" \t-•*")
                if clean:
                    normalized.append(f"- {clean}")
            return "\n".join(normalized)
        return text

    def normalize_memory_assessment(
        self,
        raw: Any,
        fallback_type: str = "episode",
        evidence_refs: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None

        allowed_types = {"domain_insight", "support_profile", "episode", "discard"}
        allowed_merge = {"append", "merge", "replace", "discard"}
        memory_type = str(raw.get("memory_type") or raw.get("type") or fallback_type or "episode").strip()
        if memory_type not in allowed_types:
            memory_type = fallback_type if fallback_type in allowed_types else "episode"

        should_store = raw.get("should_store")
        if should_store is None:
            should_store = memory_type != "discard"
        should_store = bool(should_store) and memory_type != "discard"

        content = self.format_assessed_memory_content(raw.get("content"))
        if not content and raw.get("episode_summary"):
            content = self.format_assessed_memory_content(raw.get("episode_summary"))
        if not content and isinstance(raw.get("summary_points"), list):
            content = self.format_assessed_memory_content(raw.get("summary_points"))

        confidence = raw.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = 0.5
        confidence = max(0.0, min(float(confidence), 1.0))

        sensitivity = str(raw.get("sensitivity") or "normal").strip().lower()
        if sensitivity not in ("normal", "sensitive"):
            sensitivity = "normal"

        merge_strategy = str(raw.get("merge_strategy") or "merge").strip().lower()
        if merge_strategy not in allowed_merge:
            merge_strategy = "merge"
        if merge_strategy == "discard":
            should_store = False
            memory_type = "discard"
        if not should_store:
            merge_strategy = "discard"

        refs = []
        for src in (evidence_refs or [], raw.get("evidence_refs") if isinstance(raw.get("evidence_refs"), list) else []):
            for ref in src:
                if isinstance(ref, str) and ref.strip() and ref.strip() not in refs:
                    refs.append(ref.strip())

        return {
            "should_store": should_store,
            "memory_type": memory_type if should_store else "discard",
            "content": content,
            "confidence": confidence,
            "sensitivity": sensitivity,
            "merge_strategy": merge_strategy,
            "reason": self._sanitize_memory_content(str(raw.get("reason") or ""), max_len=240),
            "evidence_refs": refs[:12],
            "model": raw.get("model"),
            "ai_used": bool(raw.get("ai_used")),
        }

    def _event_memory_domain(self, event: Dict[str, Any]) -> str:
        event_type = str(event.get("type") or "").lower()
        dimension = str(event.get("dimension") or "").lower()
        source = str((event.get("extra") or {}).get("source") or "").lower()
        return _memory_domain_from_text(event_type, dimension, source) or "bazi"

    def memory_assessment_to_item(
        self,
        user_id: str,
        event: Dict[str, Any],
        assessment: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(assessment, dict) or not assessment.get("should_store"):
            return None
        memory_type = str(assessment.get("memory_type") or "episode")
        if memory_type == "discard":
            return None

        event_type = str(event.get("type") or "")
        dimension = str(event.get("dimension") or "")
        source = str((event.get("extra") or {}).get("source") or "")
        source_domain = self._event_memory_domain(event)
        domain = source_domain
        event_id = str(event.get("event_id") or "")
        refs = assessment.get("evidence_refs") if isinstance(assessment.get("evidence_refs"), list) else []
        if event_id and event_id not in refs:
            refs = [event_id] + refs

        item = {
            "type": memory_type,
            "domain": domain,
            "dimension": dimension,
            "content": assessment.get("content") or "",
            "evidence_refs": refs,
            "confidence": assessment.get("confidence"),
            "sensitivity": assessment.get("sensitivity") or "normal",
            "model": assessment.get("model") or event.get("model_used"),
            "extra": {
                "event_type": event_type,
                "source": source,
                "source_domain": source_domain,
                "merge_strategy": assessment.get("merge_strategy"),
                "reason": assessment.get("reason"),
            },
        }

        if assessment.get("merge_strategy") == "replace":
            item["dedupe_key"] = f"assessment|{memory_type}|{domain}|{dimension}"
        return item

    def _memory_dedupe_key(self, item: Dict[str, Any]) -> str:
        raw = "|".join(
            [
                str(item.get("type") or ""),
                str(item.get("domain") or ""),
                str(item.get("dimension") or ""),
                str(item.get("content") or "")[:180],
            ]
        ).lower()
        return re.sub(r"\s+", " ", raw).strip()

    def upsert_memory_item(self, user_id: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict):
            return None
        prefs = self.get_memory_preferences(user_id)
        if prefs.get("memory_enabled") is False:
            return None
        item_type = str(item.get("type") or "episode").strip()
        if item_type == "support_profile" and prefs.get("emotional_memory_enabled") is False:
            return None
        disabled_types = prefs.get("disabled_types") if isinstance(prefs.get("disabled_types"), list) else []
        if item_type in disabled_types:
            return None

        content = self._sanitize_memory_content(str(item.get("content") or ""), max_len=1200)
        if not content:
            return None

        now = datetime.now().isoformat()
        doc = self.get_memory_items_doc(user_id)
        items = doc.setdefault("items", [])
        if not isinstance(items, list):
            items = []
            doc["items"] = items

        incoming = {
            "id": str(item.get("id") or f"mem_{uuid.uuid4().hex}"),
            "user_id": user_id,
            "type": item_type,
            "domain": str(item.get("domain") or "global"),
            "dimension": str(item.get("dimension") or ""),
            "content": content,
            "evidence_refs": item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else [],
            "confidence": item.get("confidence") if isinstance(item.get("confidence"), (int, float)) else None,
            "sensitivity": str(item.get("sensitivity") or "normal"),
            "pinned": bool(item.get("pinned", False)),
            "disabled": bool(item.get("disabled", False)),
            "created_at": str(item.get("created_at") or now),
            "updated_at": now,
            "expires_at": item.get("expires_at"),
            "model": item.get("model"),
            "extra": item.get("extra") if isinstance(item.get("extra"), dict) else {},
        }
        incoming["dedupe_key"] = item.get("dedupe_key") or self._memory_dedupe_key(incoming)

        existing = None
        for current in items:
            if not isinstance(current, dict):
                continue
            if current.get("id") == incoming["id"] or current.get("dedupe_key") == incoming["dedupe_key"]:
                existing = current
                break

        if existing:
            existing["content"] = incoming["content"]
            existing["updated_at"] = now
            existing["domain"] = incoming["domain"] or existing.get("domain")
            existing["dimension"] = incoming["dimension"] or existing.get("dimension")
            existing["sensitivity"] = incoming["sensitivity"] or existing.get("sensitivity")
            if incoming["confidence"] is not None:
                existing["confidence"] = incoming["confidence"]
            if incoming.get("model"):
                existing["model"] = incoming.get("model")
            refs = []
            for src in (existing.get("evidence_refs"), incoming.get("evidence_refs")):
                if isinstance(src, list):
                    for ref in src:
                        if isinstance(ref, str) and ref not in refs:
                            refs.append(ref)
            existing["evidence_refs"] = refs[-12:]
            existing.setdefault("pinned", False)
            existing.setdefault("disabled", False)
            result = existing
        else:
            items.insert(0, incoming)
            result = incoming

        doc["items"] = [it for it in items if isinstance(it, dict)][:500]
        self.save_memory_items_doc(user_id, doc)
        return result

    def get_memory_items(
        self,
        user_id: str,
        include_disabled: bool = False,
        memory_type: Optional[str] = None,
        limit: Optional[int] = None,
        allow_legacy_backfill: bool = True,
    ) -> List[Dict[str, Any]]:
        if allow_legacy_backfill:
            try:
                self.backfill_memory_items_from_legacy(user_id=user_id, force=False)
            except Exception:
                pass
        doc = self.get_memory_items_doc(user_id)
        items = doc.get("items") if isinstance(doc, dict) else []
        if not isinstance(items, list):
            return []
        out = []
        normalized = False
        for item in items:
            if not isinstance(item, dict):
                continue
            inferred_domain = self._domain_from_memory_item_fields(item)
            if inferred_domain in ("liuyao", "qimen", "ziwei") and item.get("domain") != inferred_domain:
                item["domain"] = inferred_domain
                item.setdefault("extra", {})
                if isinstance(item["extra"], dict):
                    item["extra"]["source_domain"] = inferred_domain
                normalized = True
            if not include_disabled and item.get("disabled"):
                continue
            if memory_type and item.get("type") != memory_type:
                continue
            out.append(item)
        if normalized:
            try:
                self.save_memory_items_doc(user_id, doc)
            except Exception:
                pass
        out.sort(key=lambda x: (bool(x.get("pinned")), str(x.get("updated_at") or "")), reverse=True)
        if limit is not None:
            out = out[: max(0, int(limit))]
        return out

    def set_memory_item_pin(self, user_id: str, memory_id: str, pinned: bool = True) -> Optional[Dict[str, Any]]:
        doc = self.get_memory_items_doc(user_id)
        for item in doc.get("items", []):
            if isinstance(item, dict) and item.get("id") == memory_id:
                item["pinned"] = bool(pinned)
                item["updated_at"] = datetime.now().isoformat()
                self.save_memory_items_doc(user_id, doc)
                return item
        return None

    def delete_memory_item(self, user_id: str, memory_id: str) -> bool:
        doc = self.get_memory_items_doc(user_id)
        for item in doc.get("items", []):
            if isinstance(item, dict) and item.get("id") == memory_id:
                item["disabled"] = True
                item["deleted_at"] = datetime.now().isoformat()
                item["updated_at"] = item["deleted_at"]
                self.save_memory_items_doc(user_id, doc)
                return True
        return False

    def format_memory_item_text(self, item: Dict[str, Any], max_len: int = 360) -> str:
        if not isinstance(item, dict) or item.get("disabled"):
            return ""
        typ = item.get("type") or "memory"
        dim = item.get("dimension") or item.get("domain") or "global"
        text = self._sanitize_memory_content(str(item.get("content") or ""), max_len=max_len)
        if not text:
            return ""
        pin = " pinned" if item.get("pinned") else ""
        conf = item.get("confidence")
        conf_text = f" confidence={conf:.2f}" if isinstance(conf, (int, float)) else ""
        return f"[{typ}][{dim}{pin}{conf_text}][ref={item.get('id')}] {text}"

    def _domain_from_memory_item_fields(self, item: Dict[str, Any]) -> str:
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        text = "|".join(
            [
                str(item.get("domain") or ""),
                str(item.get("dimension") or ""),
                str(extra.get("event_type") or ""),
                str(extra.get("source") or ""),
                str(extra.get("source_domain") or ""),
            ]
        )
        inferred = _memory_domain_from_text(text)
        if inferred:
            return inferred
        return str(item.get("domain") or "global")

    def get_memory_summary(self, user_id: str) -> Dict[str, Any]:
        doc = self.get_memory_items_doc(user_id)
        items = self.get_memory_items(user_id, include_disabled=False, limit=200, allow_legacy_backfill=False)
        counts: Dict[str, int] = {}
        for item in items:
            typ = str(item.get("type") or "memory")
            counts[typ] = counts.get(typ, 0) + 1
        chart_facts = self.get_chart_facts(user_id)
        profile_doc = self.get_profile_doc(user_id)
        insights = self.get_insights_doc(user_id)
        categories = {}
        for typ in ("pinned", "support_profile", "domain_insight", "episode"):
            if typ == "pinned":
                bucket = [it for it in items if it.get("pinned")]
            else:
                bucket = [it for it in items if it.get("type") == typ]
            categories[typ] = {
                "count": len(bucket),
                "items": bucket[:20],
            }
        return {
            "success": True,
            "schema_version": doc.get("schema_version", "memory_v2"),
            "user_id": user_id,
            "preferences": doc.get("preferences") or {},
            "counts": counts,
            "categories": categories,
            "chart_facts": {
                "exists": isinstance(chart_facts, dict),
                "summary": ((chart_facts or {}).get("summary") or {}).get("chart_facts_text") if isinstance(chart_facts, dict) else "",
            },
            "profile": {
                "exists": bool(profile_doc),
                "summary": self.format_profile_text(profile_doc, max_len=700),
            },
            "insights": insights,
            "organizer_status": self.get_memory_status(user_id),
        }

    def _summarize_event_memory_legacy_fallback(self, user_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        event_type = str(event.get("type") or "").strip()
        dimension = str(event.get("dimension") or "").strip()
        content = self._sanitize_memory_content(str(event.get("content") or ""), max_len=5000)
        if not content:
            return {}

        organizer_model = os.getenv("MEMORY_ORGANIZER_MODEL") or "deepseek-v4-flash"
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        deepseek_base = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com"
        if deepseek_key and openai is not None:
            try:
                client = openai.OpenAI(api_key=deepseek_key, base_url=deepseek_base)
                payload = {
                    "event_type": event_type,
                    "dimension": dimension,
                    "content": content[:7000],
                    "task": "assess whether this interaction should become durable memory for an astrology service",
                }
                resp = client.chat.completions.create(
                    model=organizer_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Return strict JSON with keys: should_store, memory_type, content, confidence, "
                                "sensitivity, merge_strategy, reason, evidence_refs. "
                                "memory_type must be one of domain_insight, support_profile, episode, discard. "
                                "content must be 3-6 short Chinese bullet points as an array. "
                                "Use domain_insight for durable analysis conclusions, support_profile for stable user "
                                "concerns/preferences/emotional support needs, episode for useful interaction summaries, "
                                "discard for transient or unsafe content. Do not diagnose mental/medical conditions. "
                                "Do not store secrets, PINs, API keys, passwords, tokens, or raw private transcripts."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.1,
                    max_tokens=700,
                )
                text = (resp.choices[0].message.content or "").strip()
                obj = self._extract_json_object(text)
                assessment = self.normalize_memory_assessment(
                    obj,
                    fallback_type="domain_insight" if event_type in ("analysis", "interpretation", "followup") else "episode",
                    evidence_refs=[str(event.get("event_id") or "")],
                )
                if assessment:
                    assessment["model"] = organizer_model
                    assessment["ai_used"] = True
                    assessment["updated_at"] = now
                    return assessment
            except Exception:
                pass

        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        user_lines: List[str] = []
        assistant_lines: List[str] = []
        for ln in lines:
            low = ln.lower()
            if low.startswith("user:") or ln.startswith("用户：") or ln.startswith("用户:"):
                user_lines.append(ln.split(":", 1)[-1].split("：", 1)[-1].strip())
            elif low.startswith("assistant:") or ln.startswith("助手：") or ln.startswith("助手:") or ln.startswith("AI：") or ln.startswith("AI:"):
                assistant_lines.append(ln.split(":", 1)[-1].split("：", 1)[-1].strip())
        user_summary = " ".join(user_lines)[:220].strip()
        assistant_summary = " ".join(assistant_lines)[:260].strip()
        fallback_parts = []
        if user_summary:
            fallback_parts.append(f"User concern: {user_summary}")
        if assistant_summary:
            fallback_parts.append(f"Advice direction: {assistant_summary}")
        if not fallback_parts:
            fallback_parts = lines[:2]
        first_lines = "\n".join(fallback_parts)[:520]
        support_terms = ("担心", "焦虑", "压力", "迷茫", "害怕", "希望", "喜欢", "不喜欢", "需要", "关系", "事业", "情感")
        support_items = []
        if user_summary and any(term in user_summary for term in support_terms):
            support_items.append(user_summary[:260])
        fallback_type = "episode"
        if event_type in ("analysis", "interpretation", "followup"):
            fallback_type = "domain_insight"
        fallback = self.normalize_memory_assessment(
            {
                "should_store": bool(first_lines),
                "memory_type": fallback_type,
                "content": first_lines,
                "confidence": 0.45,
                "sensitivity": "normal",
                "merge_strategy": "merge",
                "reason": "local fallback",
                "evidence_refs": [str(event.get("event_id") or "")],
            },
            fallback_type=fallback_type,
            evidence_refs=[str(event.get("event_id") or "")],
        ) or {}
        fallback.update({
            "episode_summary": first_lines[:520],
            "support_profile_items": support_items[:3],
            "emotional_themes": [],
            "advice_given": [],
            "open_questions": [],
            "confidence": 0.45,
            "sensitivity": "normal",
            "model": "fallback",
            "updated_at": now,
        })
        return fallback

    def summarize_event_memory(self, user_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        event_type = str(event.get("type") or "").strip()
        dimension = str(event.get("dimension") or "").strip()
        content = self._sanitize_memory_content(str(event.get("content") or ""), max_len=5000)
        if not content:
            return {
                "should_store": False,
                "memory_type": "discard",
                "content": [],
                "confidence": 1.0,
                "sensitivity": "normal",
                "merge_strategy": "discard",
                "reason": "empty event",
                "evidence_refs": [str(event.get("event_id") or "")],
                "model": "system",
                "ai_used": True,
                "updated_at": now,
            }

        organizer_model = os.getenv("MEMORY_ORGANIZER_MODEL") or "deepseek-v4-flash"
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        deepseek_base = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com"
        if not deepseek_key or openai is None:
            raise RuntimeError("AI memory organizer is unavailable")

        timeout_s = _memory_env_float("MEMORY_ORGANIZER_TIMEOUT_S", 18.0)
        client = openai.OpenAI(api_key=deepseek_key, base_url=deepseek_base, timeout=timeout_s)
        payload = {
            "event_type": event_type,
            "dimension": dimension,
            "content": content[:7000],
            "task": "assess whether this interaction should become durable memory for an astrology service",
        }
        resp = client.chat.completions.create(
            model=organizer_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return strict JSON with keys: should_store, memory_type, content, confidence, "
                        "sensitivity, merge_strategy, reason, evidence_refs. "
                        "For chat events, memory_type must be one of support_profile, episode, discard. "
                        "content must be 3-6 short Chinese bullet points as an array. "
                        "Use support_profile for stable user concerns/preferences/emotional support needs, "
                        "episode for useful interaction summaries, discard for transient or unsafe content. "
                        "Return a single JSON object, with no markdown fences or explanatory text. "
                        "Do not diagnose mental/medical conditions. Do not store secrets, PINs, API keys, "
                        "passwords, tokens, or raw private transcripts."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.1,
            max_tokens=700,
        )
        text = (resp.choices[0].message.content or "").strip()
        obj = self._extract_json_object(text)
        if not isinstance(obj, dict):
            obj = self._repair_organizer_json_with_model(
                client,
                organizer_model,
                text,
                "should_store, memory_type, content, confidence, sensitivity, merge_strategy, reason, evidence_refs",
                max_tokens=700,
            )
        assessment = self.normalize_memory_assessment(
            obj,
            fallback_type="episode",
            evidence_refs=[str(event.get("event_id") or "")],
        )
        if not assessment:
            raise ValueError("AI memory organizer returned invalid JSON")
        if assessment.get("memory_type") == "domain_insight":
            assessment["memory_type"] = "episode"
        assessment["model"] = organizer_model
        assessment["ai_used"] = True
        assessment["updated_at"] = now
        return assessment

    def upsert_event_memory_items(self, user_id: str, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        summary = self.summarize_event_memory(user_id, event)
        if not isinstance(summary, dict):
            return []
        if summary.get("ai_used") is not True:
            return []
        event_type = str(event.get("type") or "")
        dimension = str(event.get("dimension") or "")
        source_domain = self._event_memory_domain(event)
        domain = source_domain
        evidence = [str(event.get("event_id") or "")]
        model = summary.get("model") or event.get("model_used")
        confidence = summary.get("confidence") if isinstance(summary.get("confidence"), (int, float)) else 0.5
        sensitivity = str(summary.get("sensitivity") or "normal")
        written: List[Dict[str, Any]] = []
        assessed_type = None

        if "memory_type" in summary or "should_store" in summary:
            assessed_type = str(summary.get("memory_type") or "")
            item_data = self.memory_assessment_to_item(user_id=user_id, event=event, assessment=summary)
            if item_data:
                item = self.upsert_memory_item(user_id, item_data)
                if item:
                    written.append(item)
            if summary.get("memory_type") == "discard" or summary.get("should_store") is False:
                return written

        support_sources: List[str] = []
        for key in ("support_profile_items", "emotional_themes"):
            values = summary.get(key)
            if isinstance(values, list):
                support_sources.extend([str(x).strip() for x in values if str(x).strip()])
        if support_sources:
            item = self.upsert_memory_item(
                user_id,
                {
                    "type": "support_profile",
                    "domain": source_domain,
                    "dimension": dimension,
                    "content": "\n".join(support_sources[:5]),
                    "evidence_refs": evidence,
                    "confidence": confidence,
                    "sensitivity": sensitivity,
                    "model": model,
                    "extra": {"event_type": event_type, "source_domain": source_domain},
                },
            )
            if item:
                written.append(item)

        episode_summary = str(summary.get("episode_summary") or "").strip()
        advice = summary.get("advice_given") if isinstance(summary.get("advice_given"), list) else []
        open_questions = summary.get("open_questions") if isinstance(summary.get("open_questions"), list) else []
        episode_parts = [episode_summary]
        if advice:
            episode_parts.append("Advice given: " + "; ".join([str(x).strip() for x in advice if str(x).strip()][:4]))
        if open_questions:
            episode_parts.append("Open questions: " + "; ".join([str(x).strip() for x in open_questions if str(x).strip()][:4]))
        episode_content = "\n".join([x for x in episode_parts if x]).strip()
        if episode_content and assessed_type != "episode":
            item = self.upsert_memory_item(
                user_id,
                {
                    "type": "episode",
                    "domain": domain,
                    "dimension": dimension,
                    "content": episode_content,
                    "evidence_refs": evidence,
                    "confidence": confidence,
                    "sensitivity": sensitivity,
                    "model": model,
                    "extra": {"event_type": event_type, "source_domain": source_domain},
                },
            )
            if item:
                written.append(item)
        return written

    def normalize_insight_patch(
        self,
        raw: Any,
        dimension: str,
        version: str,
        model_used: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        summary_points = self._normalize_str_list(raw.get("summary_points"))
        evidence_points = self._normalize_str_list(raw.get("evidence_points"))
        advice_points = self._normalize_str_list(raw.get("advice_points"))
        if not (summary_points or evidence_points or advice_points):
            return None
        confidence = raw.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = None
        now = datetime.now().isoformat()
        return {
            "dimension": str(raw.get("dimension") or dimension),
            "version": str(raw.get("version") or version or "classic"),
            "summary_points": summary_points[:7],
            "evidence_points": evidence_points[:7],
            "advice_points": advice_points[:5],
            "confidence": confidence,
            "updated_at": now,
            "sources": [{"model": model_used or self._organizer_model_name(), "time": now}],
        }

    def upsert_structured_insight_patch(
        self,
        user_id: str,
        dimension: str,
        version: str,
        incoming: Dict[str, Any],
        model_used: Optional[str] = None,
        importance: int = 8,
    ) -> Optional[Dict[str, Any]]:
        patch = self.normalize_insight_patch(incoming, dimension=dimension, version=version, model_used=model_used)
        if not patch:
            return None
        doc = self.get_insights_doc(user_id)
        dims = doc.setdefault("dimensions", {})
        d = dims.setdefault(dimension, {})
        vs = d.setdefault("versions", {})
        bucket = vs.setdefault(version, {"current": None, "history": []})
        current = bucket.get("current")
        merged = self.merge_dimension_insight(current, patch)
        if current and isinstance(current, dict):
            history = bucket.get("history") or []
            history = [h for h in history if isinstance(h, dict)] if isinstance(history, list) else []
            history.insert(0, current)
            bucket["history"] = history[:3]
        bucket["current"] = merged
        bucket["updated_at"] = merged.get("updated_at")
        bucket["importance"] = importance
        self.save_insights_doc(user_id, doc)
        if self.vector_memory:
            try:
                safe_dim = self._safe_user_id(dimension)[:64]
                mem_id = f"insight_{safe_dim}_{version}_current"
                self.vector_memory.upsert(
                    user_id=user_id,
                    memory_id=mem_id,
                    text=self.format_dimension_insight_text(merged, max_len=1200),
                    metadata={
                        "type": "insight",
                        "dimension": dimension,
                        "version": version,
                        "model_used": model_used,
                        "importance": importance,
                        "updated_at": merged.get("updated_at"),
                    },
                )
            except Exception:
                pass
        return merged

    def organize_analysis_event_memory(self, user_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        event_type = str(event.get("type") or "").strip()
        dimension = str(event.get("dimension") or "").strip()
        version = str(event.get("version") or "classic")
        content = self._sanitize_memory_content(str(event.get("content") or ""), max_len=9000)
        if not content:
            return {"discard_reason": "empty event", "ai_used": True, "memory_items": [], "profile_patch": {}, "insight_patch": None}
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if not deepseek_key or openai is None:
            raise RuntimeError("AI memory organizer is unavailable")
        organizer_model = self._organizer_model_name()
        deepseek_base = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com"
        timeout_s = _memory_env_float("MEMORY_ORGANIZER_TIMEOUT_S", 18.0)
        cf = self.get_chart_facts(user_id)
        cf_text = ""
        if isinstance(cf, dict):
            cf_text = ((cf.get("summary") or {}).get("chart_facts_text") or "").strip()[:1200]
        payload = {
            "event_type": event_type,
            "dimension": dimension,
            "version": version,
            "chart_facts_summary": cf_text,
            "content": content,
            "user_background": event.get("user_background") if isinstance(event.get("user_background"), dict) else {},
        }
        client = openai.OpenAI(api_key=deepseek_key, base_url=deepseek_base, timeout=timeout_s)
        resp = client.chat.completions.create(
            model=organizer_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a durable memory organizer for an astrology product. Return strict JSON only. "
                        "Schema: insight_patch or null, memory_items array, profile_patch object, discard_reason string. "
                        "insight_patch fields: summary_points(3-7), evidence_points(0-7), advice_points(0-5), confidence(0-1). "
                        "memory_items entries have memory_type(domain_insight|support_profile|episode|discard), "
                        "content(3-6 short Chinese bullet points array), confidence, sensitivity, merge_strategy, reason. "
                        "profile_patch may include background object, preferences object, tags array, feedback_text string. "
                        "Return a single JSON object, with no markdown fences or explanatory text. "
                        "Do not store secrets, passwords, tokens, PINs, raw transcripts, or medical/mental diagnoses."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.1,
            max_tokens=1200,
        )
        text = (resp.choices[0].message.content or "").strip()
        obj = self._extract_json_object(text)
        if not isinstance(obj, dict):
            obj = self._repair_organizer_json_with_model(
                client,
                organizer_model,
                text,
                (
                    "insight_patch or null, memory_items array, profile_patch object, "
                    "discard_reason string"
                ),
                max_tokens=1200,
            )
        if not isinstance(obj, dict):
            raise ValueError("AI memory organizer returned invalid JSON")

        insight_raw = obj.get("insight_patch") or obj.get("insightPatch") or obj.get("insight")
        insight_patch = self.normalize_insight_patch(
            insight_raw,
            dimension=dimension,
            version=version,
            model_used=event.get("model_used") or organizer_model,
        )
        normalized_items: List[Dict[str, Any]] = []
        raw_items_any = obj.get("memory_items") or obj.get("memoryItems") or obj.get("items")
        raw_items = raw_items_any if isinstance(raw_items_any, list) else []
        for raw_item in raw_items[:6]:
            assessment = self.normalize_memory_assessment(
                raw_item,
                fallback_type="domain_insight" if event_type in ("analysis", "interpretation", "followup") else "episode",
                evidence_refs=[str(event.get("event_id") or "")],
            )
            if not assessment or not assessment.get("should_store"):
                continue
            assessment["ai_used"] = True
            assessment["model"] = organizer_model
            item_data = self.memory_assessment_to_item(user_id=user_id, event=event, assessment=assessment)
            if item_data:
                normalized_items.append(item_data)

        profile_raw = obj.get("profile_patch") or obj.get("profilePatch") or obj.get("profile")
        profile_patch = profile_raw if isinstance(profile_raw, dict) else {}
        discard_reason = self._sanitize_memory_content(
            str(obj.get("discard_reason") or obj.get("discardReason") or obj.get("reason") or ""),
            max_len=240,
        )
        if not insight_patch and not normalized_items and not profile_patch and not discard_reason:
            raise ValueError("AI memory organizer produced no usable memory payload")
        return {
            "ai_used": True,
            "model": organizer_model,
            "insight_patch": insight_patch,
            "memory_items": normalized_items,
            "profile_patch": profile_patch,
            "discard_reason": discard_reason,
        }

    def apply_organized_analysis_event(self, user_id: str, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        organized = self.organize_analysis_event_memory(user_id=user_id, event=event)
        written: List[Dict[str, Any]] = []
        event_type = str(event.get("type") or "")
        dimension = str(event.get("dimension") or "")
        version = str(event.get("version") or "classic")
        model_used = event.get("model_used") or organized.get("model")
        importance = event.get("importance") if isinstance(event.get("importance"), int) else 8

        profile_patch = organized.get("profile_patch") if isinstance(organized.get("profile_patch"), dict) else {}
        if profile_patch:
            self.update_profile(
                user_id=user_id,
                background=profile_patch.get("background") if isinstance(profile_patch.get("background"), dict) else {},
                preferences=profile_patch.get("preferences") if isinstance(profile_patch.get("preferences"), dict) else {},
                add_tags=profile_patch.get("tags") if isinstance(profile_patch.get("tags"), list) else [dimension, event_type],
                feedback_text=profile_patch.get("feedback_text") if isinstance(profile_patch.get("feedback_text"), str) else None,
                feedback_meta={"source": "memory_organizer", "event_id": event.get("event_id")},
            )

        insight_patch = organized.get("insight_patch")
        if isinstance(insight_patch, dict):
            self.upsert_structured_insight_patch(
                user_id=user_id,
                dimension=dimension,
                version=version,
                incoming=insight_patch,
                model_used=model_used,
                importance=importance,
            )

        for item_data in organized.get("memory_items") or []:
            item = self.upsert_memory_item(user_id, item_data)
            if item:
                written.append(item)
        return written

    def _merge_kv_overwrite(self, base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(base or {})
        for k, v in (incoming or {}).items():
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            out[k] = v
        return out

    def _merge_tags(self, base: Any, incoming: Any, limit: int = 50) -> List[str]:
        out: List[str] = []
        seen = set()
        for src in (base, incoming):
            if not isinstance(src, list):
                continue
            for x in src:
                if not isinstance(x, str):
                    continue
                t = x.strip()
                if not t:
                    continue
                k = t.lower()
                if k in seen:
                    continue
                seen.add(k)
                out.append(t)
                if len(out) >= limit:
                    return out
        return out

    def update_profile(
        self,
        user_id: str,
        background: Optional[Dict[str, Any]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        add_tags: Optional[List[str]] = None,
        feedback_text: Optional[str] = None,
        feedback_meta: Optional[Dict[str, Any]] = None,
        importance: int = 7,
    ) -> Dict[str, Any]:
        doc = self.get_profile_doc(user_id)
        doc["background"] = self._merge_kv_overwrite(doc.get("background") or {}, background or {})
        doc["preferences"] = self._merge_kv_overwrite(doc.get("preferences") or {}, preferences or {})
        doc["tags"] = self._merge_tags(doc.get("tags"), add_tags or [], limit=50)

        if feedback_text and isinstance(feedback_text, str) and feedback_text.strip():
            fb = {
                "text": feedback_text.strip(),
                "time": datetime.now().isoformat(),
                "meta": feedback_meta or {},
            }
            fbs = doc.get("feedback")
            if not isinstance(fbs, list):
                fbs = []
            fbs.append(fb)
            doc["feedback"] = fbs[-20:]

        doc["updated_at"] = datetime.now().isoformat()
        self.save_profile_doc(user_id, doc)

        if self.vector_memory:
            try:
                text = self.format_profile_text(doc, max_len=900)
                self.vector_memory.upsert(
                    user_id=user_id,
                    memory_id="profile_current",
                    text=text,
                    metadata={
                        "type": "profile",
                        "dimension": "全局",
                        "importance": importance,
                        "updated_at": doc.get("updated_at"),
                    },
                )
            except Exception:
                pass

        return doc

    def format_profile_text(self, doc: Dict[str, Any], max_len: int = 900) -> str:
        bg = doc.get("background") if isinstance(doc, dict) else None
        pf = doc.get("preferences") if isinstance(doc, dict) else None
        tags = doc.get("tags") if isinstance(doc, dict) else None
        fbs = doc.get("feedback") if isinstance(doc, dict) else None

        lines = ["用户画像："]
        if isinstance(bg, dict) and bg:
            lines.append("背景：")
            for k, v in bg.items():
                if v is None:
                    continue
                if isinstance(v, str) and not v.strip():
                    continue
                lines.append(f"- {k}：{v}")
        if isinstance(pf, dict) and pf:
            lines.append("偏好：")
            for k, v in pf.items():
                if v is None:
                    continue
                if isinstance(v, str) and not v.strip():
                    continue
                lines.append(f"- {k}：{v}")
        if isinstance(tags, list) and tags:
            lines.append("标签：")
            lines.append("、".join([t for t in tags if isinstance(t, str) and t.strip()])[:200])
        if isinstance(fbs, list) and fbs:
            last = fbs[-1]
            if isinstance(last, dict):
                t = (last.get("text") or "").strip()
                if t:
                    lines.append("最新反馈：")
                    lines.append(t[:200])

        text = "\n".join(lines).strip()
        if len(text) > max_len:
            return text[:max_len] + "..."
        return text

    def _events_path(self, user_id: str) -> str:
        safe = self._safe_user_id(user_id)
        os.makedirs("local_data/events", exist_ok=True)
        return os.path.join("local_data", "events", f"{safe}.jsonl")

    def _events_state_path(self, user_id: str) -> str:
        safe = self._safe_user_id(user_id)
        os.makedirs("local_data/events", exist_ok=True)
        return os.path.join("local_data", "events", f"{safe}.state.json")

    def _load_events_state(self, user_id: str) -> Dict[str, Any]:
        path = self._events_state_path(user_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = json.load(f)
                if isinstance(doc, dict):
                    doc.setdefault("schema_version", "memory_events_state_v2")
                    doc.setdefault("user_id", user_id)
                    doc.setdefault("last_line", 0)
                    if not isinstance(doc.get("events"), dict):
                        doc["events"] = {}
                    return doc
            except Exception:
                pass
        return {
            "schema_version": "memory_events_state_v2",
            "user_id": user_id,
            "last_line": 0,
            "events": {},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

    def _save_events_state(self, user_id: str, doc: Dict[str, Any]) -> str:
        doc["schema_version"] = "memory_events_state_v2"
        doc["user_id"] = user_id
        doc["updated_at"] = datetime.now().isoformat()
        if not isinstance(doc.get("events"), dict):
            doc["events"] = {}
        path = self._events_state_path(user_id)
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def _event_status_record(
        self,
        event_id: str,
        status: str = "pending",
        line_no: Optional[int] = None,
        queued_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        return {
            "event_id": event_id,
            "status": status if status in MEMORY_EVENT_STATUSES else "pending",
            "attempts": 0,
            "queued_at": queued_at or now,
            "started_at": None,
            "finished_at": None,
            "last_error": None,
            "memory_item_ids": [],
            "line_no": line_no,
            "next_retry_at": None,
        }

    def _read_all_events(self, user_id: str) -> List[Dict[str, Any]]:
        path = self._events_path(user_id)
        if not os.path.exists(path):
            return []
        events: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    obj["_line_no"] = idx
                    events.append(obj)
        return events

    def _ensure_event_state_records(self, user_id: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        doc = self._load_events_state(user_id)
        records = doc.setdefault("events", {})
        raw_events = self._read_all_events(user_id)
        changed = False
        for evt in raw_events:
            event_id = str(evt.get("event_id") or "").strip()
            if not event_id:
                continue
            event_type = str(evt.get("type") or "")
            dimension = str(evt.get("dimension") or "")
            rec = records.get(event_id)
            if not isinstance(rec, dict):
                records[event_id] = self._event_status_record(
                    event_id=event_id,
                    status="pending",
                    line_no=evt.get("_line_no"),
                    queued_at=evt.get("created_at"),
                )
                records[event_id]["event_type"] = event_type
                records[event_id]["dimension"] = dimension
                records[event_id]["version"] = evt.get("version")
                changed = True
                continue
            if rec.get("status") not in MEMORY_EVENT_STATUSES:
                rec["status"] = "pending"
                changed = True
            rec.setdefault("event_id", event_id)
            rec.setdefault("attempts", 0)
            rec.setdefault("queued_at", evt.get("created_at") or datetime.now().isoformat())
            rec.setdefault("started_at", None)
            rec.setdefault("finished_at", None)
            rec.setdefault("last_error", None)
            rec.setdefault("memory_item_ids", [])
            rec.setdefault("line_no", evt.get("_line_no"))
            rec.setdefault("next_retry_at", None)
            if event_type and not rec.get("event_type"):
                rec["event_type"] = event_type
                changed = True
            if dimension and not rec.get("dimension"):
                rec["dimension"] = dimension
                changed = True
            if evt.get("version") and not rec.get("version"):
                rec["version"] = evt.get("version")
                changed = True
        doc["last_line"] = max([int(e.get("_line_no") or 0) for e in raw_events] or [0])
        if changed:
            self._save_events_state(user_id, doc)
        return doc, raw_events

    @staticmethod
    def _parse_iso_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    def _retry_delay_seconds(self, attempts: int) -> int:
        idx = max(0, min(len(MEMORY_EVENT_RETRY_DELAYS) - 1, max(1, int(attempts)) - 1))
        return MEMORY_EVENT_RETRY_DELAYS[idx]

    def _event_retry_due(self, rec: Dict[str, Any], now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        status = rec.get("status")
        if status == "pending":
            return True
        if status == "failed_retryable":
            due = self._parse_iso_datetime(rec.get("next_retry_at"))
            return due is None or due <= now
        if status == "processing":
            started = self._parse_iso_datetime(rec.get("started_at"))
            timeout_s = _memory_env_float("MEMORY_ORGANIZER_TIMEOUT_S", 18.0)
            return started is not None and (now - started).total_seconds() > max(timeout_s * 2, 120)
        return False

    def _set_event_status(
        self,
        doc: Dict[str, Any],
        event_id: str,
        status: str,
        **updates: Any,
    ) -> Dict[str, Any]:
        records = doc.setdefault("events", {})
        rec = records.get(event_id)
        if not isinstance(rec, dict):
            rec = self._event_status_record(event_id=event_id)
            records[event_id] = rec
        rec["status"] = status if status in MEMORY_EVENT_STATUSES else "pending"
        for key, value in updates.items():
            rec[key] = value
        return rec

    def get_memory_status(self, user_id: str) -> Dict[str, Any]:
        doc, raw_events = self._ensure_event_state_records(user_id)
        records = doc.get("events") if isinstance(doc.get("events"), dict) else {}
        counts = {status: 0 for status in MEMORY_EVENT_STATUSES}
        latest: List[Dict[str, Any]] = []
        for rec in records.values():
            if not isinstance(rec, dict):
                continue
            status = rec.get("status") if rec.get("status") in MEMORY_EVENT_STATUSES else "pending"
            counts[status] = counts.get(status, 0) + 1
            latest.append({
                "event_id": rec.get("event_id"),
                "status": status,
                "event_type": rec.get("event_type"),
                "dimension": rec.get("dimension"),
                "version": rec.get("version"),
                "attempts": rec.get("attempts", 0),
                "queued_at": rec.get("queued_at"),
                "started_at": rec.get("started_at"),
                "finished_at": rec.get("finished_at"),
                "last_error": rec.get("last_error"),
                "memory_item_ids": rec.get("memory_item_ids") if isinstance(rec.get("memory_item_ids"), list) else [],
                "next_retry_at": rec.get("next_retry_at"),
                "line_no": rec.get("line_no"),
            })
        latest.sort(key=lambda x: str(x.get("queued_at") or ""), reverse=True)
        active = counts.get("pending", 0) + counts.get("processing", 0) + counts.get("failed_retryable", 0)
        return {
            "success": True,
            "schema_version": doc.get("schema_version", "memory_events_state_v2"),
            "user_id": user_id,
            "counts": counts,
            "active_count": active,
            "pending_count": counts.get("pending", 0) + counts.get("failed_retryable", 0),
            "processing_count": counts.get("processing", 0),
            "failed_count": counts.get("failed_retryable", 0) + counts.get("failed_final", 0),
            "ready_count": counts.get("ready", 0),
            "discarded_count": counts.get("discarded", 0),
            "latest": latest[:10],
            "raw_event_count": len(raw_events),
            "updated_at": doc.get("updated_at"),
        }

    def append_raw_event(
        self,
        user_id: str,
        event_type: str,
        dimension: str,
        version: Optional[str],
        content: str,
        model_used: Optional[str] = None,
        user_background: Optional[Dict[str, Any]] = None,
        importance: int = 6,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        event_id = f"evt_{uuid.uuid4().hex}"
        evt = {
            "event_id": event_id,
            "type": event_type,
            "dimension": dimension,
            "version": version,
            "content": (content or ""),
            "model_used": model_used,
            "user_background": user_background or {},
            "importance": importance,
            "created_at": datetime.now().isoformat(),
            "extra": extra or {},
        }
        path = self._events_path(user_id)
        line = json.dumps(evt, ensure_ascii=False)
        if portalocker:
            with portalocker.Lock(path, mode="a", encoding="utf-8", timeout=5) as f:
                f.write(line + "\n")
        else:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        try:
            doc = self._load_events_state(user_id)
            raw_line = len(self._read_all_events(user_id))
            self._set_event_status(
                doc,
                event_id,
                "pending",
                queued_at=evt.get("created_at"),
                started_at=None,
                finished_at=None,
                last_error=None,
                memory_item_ids=[],
                line_no=raw_line,
                next_retry_at=None,
                event_type=event_type,
                dimension=dimension,
                version=version,
            )
            doc["last_line"] = max(int(doc.get("last_line") or 0), raw_line)
            self._save_events_state(user_id, doc)
        except Exception:
            pass
        return event_id

    def _get_event_cursor(self, user_id: str) -> int:
        path = self._events_state_path(user_id)
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            v = s.get("last_line") if isinstance(s, dict) else 0
            return int(v) if isinstance(v, int) or (isinstance(v, str) and v.isdigit()) else 0
        except Exception:
            return 0

    def _set_event_cursor(self, user_id: str, last_line: int) -> None:
        doc = self._load_events_state(user_id)
        doc["last_line"] = int(last_line)
        self._save_events_state(user_id, doc)

    def _read_events_since(self, user_id: str, start_line: int, limit: int) -> tuple[List[Dict[str, Any]], int]:
        path = self._events_path(user_id)
        if not os.path.exists(path):
            return [], start_line
        events: List[Dict[str, Any]] = []
        idx = 0
        new_cursor = start_line
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if idx < start_line:
                    idx += 1
                    continue
                s = line.strip()
                idx += 1
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    events.append(obj)
                    new_cursor = idx
                if len(events) >= limit:
                    break
        return events, new_cursor

    def get_pending_event_count(self, user_id: str) -> int:
        status = self.get_memory_status(user_id)
        counts = status.get("counts") if isinstance(status.get("counts"), dict) else {}
        return int(counts.get("pending", 0) or 0) + int(counts.get("failed_retryable", 0) or 0)

    def retry_memory_event(self, user_id: str, event_id: str) -> Optional[Dict[str, Any]]:
        event_id = str(event_id or "").strip()
        if not event_id:
            return None
        doc, raw_events = self._ensure_event_state_records(user_id)
        raw_ids = {str(evt.get("event_id") or "") for evt in raw_events if isinstance(evt, dict)}
        if event_id not in raw_ids:
            return None
        records = doc.get("events") if isinstance(doc.get("events"), dict) else {}
        rec = records.get(event_id)
        if not isinstance(rec, dict):
            return None
        updated = self._set_event_status(
            doc,
            event_id,
            "pending",
            attempts=0,
            started_at=None,
            finished_at=None,
            last_error=None,
            memory_item_ids=[],
            next_retry_at=None,
            queued_at=rec.get("queued_at") or datetime.now().isoformat(),
        )
        self._save_events_state(user_id, doc)
        return updated

    def get_latest_raw_event_text(self, user_id: str, dimension: str, max_len: int = 800) -> str:
        path = self._events_path(user_id)
        if not os.path.exists(path):
            return ""
        last = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("dimension") != dimension:
                    continue
                last = obj
        if not isinstance(last, dict):
            return ""
        t = (last.get("type") or "").strip()
        c = (last.get("content") or "").strip()
        if not c:
            return ""
        text = f"{t}：\n{c}".strip()
        if len(text) > max_len:
            return text[:max_len] + "..."
        return text

    def process_pending_events(self, user_id: str, max_events: int = 5) -> Dict[str, Any]:
        path = self._events_path(user_id)
        if portalocker:
            lock_path = f"{path}.lock"
            lock_ctx = portalocker.Lock(lock_path, timeout=5)
        else:
            lock_ctx = None

        def _run() -> Dict[str, Any]:
            doc, raw_events = self._ensure_event_state_records(user_id)
            event_by_id = {
                str(evt.get("event_id") or ""): evt
                for evt in raw_events
                if isinstance(evt, dict) and str(evt.get("event_id") or "").strip()
            }
            records = doc.get("events") if isinstance(doc.get("events"), dict) else {}
            now = datetime.now()
            selected: List[tuple[str, Dict[str, Any]]] = []
            for event_id, rec in sorted(
                records.items(),
                key=lambda item: int((item[1] or {}).get("line_no") or 0),
            ):
                if len(selected) >= max(1, int(max_events or 1)):
                    break
                if not isinstance(rec, dict) or event_id not in event_by_id:
                    continue
                if self._event_retry_due(rec, now=now):
                    selected.append((event_id, event_by_id[event_id]))

            processed = 0
            ready = 0
            discarded = 0
            failed = 0
            max_attempts = _memory_env_int("MEMORY_EVENT_MAX_ATTEMPTS", 3)
            for event_id, evt in selected:
                doc = self._load_events_state(user_id)
                rec = (doc.get("events") or {}).get(event_id) if isinstance(doc.get("events"), dict) else None
                attempts = int((rec or {}).get("attempts") or 0) + 1
                start_time = datetime.now().isoformat()
                self._set_event_status(
                    doc,
                    event_id,
                    "processing",
                    attempts=attempts,
                    started_at=start_time,
                    finished_at=None,
                    last_error=None,
                    memory_item_ids=[],
                    next_retry_at=None,
                )
                self._save_events_state(user_id, doc)

                et = (evt.get("type") or "").strip()
                content = (evt.get("content") or "").strip()
                item_ids: List[str] = []
                final_status = "discarded"
                try:
                    if et in ("analysis", "interpretation", "followup") and content:
                        dimension = str(evt.get("dimension") or "")
                        before_insight = self.get_latest_dimension_insight(
                            user_id=user_id,
                            dimension=dimension,
                        ).strip()
                        before_profile = json.dumps(
                            self.get_profile_doc(user_id),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        written = self.apply_organized_analysis_event(user_id=user_id, event=evt)
                        item_ids = [str(x.get("id")) for x in written if isinstance(x, dict) and x.get("id")]
                        after_insight = self.get_latest_dimension_insight(
                            user_id=user_id,
                            dimension=dimension,
                        ).strip()
                        after_profile = json.dumps(
                            self.get_profile_doc(user_id),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        imported = bool(item_ids) or after_insight != before_insight or after_profile != before_profile
                        final_status = "ready" if imported else "discarded"
                    elif et in ("ziwei_chat", "liuyao_chat", "qimen_chat") and content:
                        written = self.upsert_event_memory_items(user_id=user_id, event=evt)
                        item_ids = [str(x.get("id")) for x in written if isinstance(x, dict) and x.get("id")]
                        final_status = "ready" if item_ids else "discarded"
                    else:
                        final_status = "discarded"

                    doc = self._load_events_state(user_id)
                    self._set_event_status(
                        doc,
                        event_id,
                        final_status,
                        finished_at=datetime.now().isoformat(),
                        last_error=None,
                        memory_item_ids=item_ids,
                        next_retry_at=None,
                    )
                    self._save_events_state(user_id, doc)
                    if final_status == "ready":
                        ready += 1
                    else:
                        discarded += 1
                except Exception as exc:
                    err = self._sanitize_memory_content(str(exc), max_len=500)
                    status = "failed_final" if attempts >= max_attempts else "failed_retryable"
                    next_retry_at = None
                    if status == "failed_retryable":
                        next_retry_at = (
                            datetime.now() + timedelta(seconds=self._retry_delay_seconds(attempts))
                        ).isoformat()
                    doc = self._load_events_state(user_id)
                    self._set_event_status(
                        doc,
                        event_id,
                        status,
                        finished_at=datetime.now().isoformat(),
                        last_error=err,
                        memory_item_ids=[],
                        next_retry_at=next_retry_at,
                    )
                    self._save_events_state(user_id, doc)
                    failed += 1
                processed += 1

            status_doc, _raw_events = self._ensure_event_state_records(user_id)
            try:
                self._set_event_cursor(user_id, int(status_doc.get("last_line") or 0))
            except Exception:
                pass
            status = self.get_memory_status(user_id)
            return {
                "processed": processed,
                "pending": status.get("pending_count", 0),
                "cursor": status_doc.get("last_line", 0),
                "ready": ready,
                "discarded": discarded,
                "failed": failed,
            }

        if lock_ctx:
            with lock_ctx:
                return _run()
        return _run()

    def get_insights_doc(self, user_id: str) -> Dict[str, Any]:
        path = self._insights_path(user_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = json.load(f)
                if isinstance(doc, dict):
                    doc.setdefault("schema_version", "insights_v1")
                    doc.setdefault("user_id", user_id)
                    doc.setdefault("dimensions", {})
                    return doc
            except Exception:
                pass
        return {"schema_version": "insights_v1", "user_id": user_id, "dimensions": {}}

    def save_insights_doc(self, user_id: str, doc: Dict[str, Any]) -> str:
        path = self._insights_path(user_id)
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def _extract_json_object(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        candidates = [str(text).strip()]
        s = candidates[0]
        if "```" in s:
            parts = s.split("```")
            candidates.extend(part.strip() for part in parts if part.strip())
            for part in parts:
                cleaned = part.strip()
                if cleaned.lower().startswith("json"):
                    candidates.append(cleaned[4:].strip())

        decoder = json.JSONDecoder()
        for candidate in candidates:
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            return item
            except Exception:
                pass

            start = candidate.find("{")
            while start != -1:
                try:
                    parsed, _end = decoder.raw_decode(candidate[start:])
                    if isinstance(parsed, dict):
                        return parsed
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict):
                                return item
                except Exception:
                    pass
                start = candidate.find("{", start + 1)

        return None

    def _normalize_str_list(self, v: Any) -> List[str]:
        out: List[str] = []
        if isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    t = x.strip()
                    if t:
                        out.append(t)
        return out

    def summarize_dimension_insight(
        self,
        user_id: str,
        dimension: str,
        version: str,
        analysis_content: str,
        model_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        cf = self.get_chart_facts(user_id)
        cf_text = ""
        if isinstance(cf, dict):
            cf_text = ((cf.get("summary") or {}).get("chart_facts_text") or "").strip()
        if len(cf_text) > 1200:
            cf_text = cf_text[:1200]

        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        deepseek_base = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com"
        organizer_model = os.getenv("MEMORY_ORGANIZER_MODEL") or "deepseek-v4-flash"
        if deepseek_key and openai is not None:
            try:
                client = openai.OpenAI(api_key=deepseek_key, base_url=deepseek_base)
                payload = {
                    "dimension": dimension,
                    "version": version,
                    "chart_facts_summary": cf_text,
                    "analysis_content": (analysis_content or "")[:9000],
                }
                prompt = json.dumps(payload, ensure_ascii=False)
                resp = client.chat.completions.create(
                    model=organizer_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是八字维度结论整理器。将输入中的分析内容整理为严格JSON对象，字段：dimension, version, summary_points(3-7), evidence_points(0-7，尽量引用命盘事实层关键词：日主/十神/五行/大运/神煞/刑冲合会), advice_points(0-5), confidence(0-1，可选), updated_at(ISO8601), sources([{model,time}]).只输出JSON，不要额外文本。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=900,
                )
                text = (resp.choices[0].message.content or "").strip()
                obj = self._extract_json_object(text)
                if obj:
                    summary_points = self._normalize_str_list(obj.get("summary_points"))
                    evidence_points = self._normalize_str_list(obj.get("evidence_points"))
                    advice_points = self._normalize_str_list(obj.get("advice_points"))
                    confidence = obj.get("confidence")
                    if not isinstance(confidence, (int, float)):
                        confidence = None
                    result = {
                        "dimension": dimension,
                        "version": version,
                        "summary_points": summary_points[:7],
                        "evidence_points": evidence_points[:7],
                        "advice_points": advice_points[:5],
                        "confidence": confidence,
                        "updated_at": now,
                        "sources": [{"model": model_used or organizer_model, "time": now}],
                    }
                    return result
            except Exception:
                pass

        content = (analysis_content or "").strip()
        lines = [ln.strip(" \t-•").strip() for ln in content.splitlines() if ln.strip()]
        summary_points = []
        for ln in lines:
            if len(ln) < 6:
                continue
            summary_points.append(ln)
            if len(summary_points) >= 5:
                break
        evidence_points = []
        for ln in lines:
            if any(k in ln for k in ["日主", "十神", "五行", "大运", "流年", "神煞", "刑", "冲", "合", "会"]):
                evidence_points.append(ln)
            if len(evidence_points) >= 5:
                break
        advice_points = []
        for ln in lines:
            if "建议" in ln or "宜" in ln or "避免" in ln:
                advice_points.append(ln)
            if len(advice_points) >= 4:
                break
        if not advice_points:
            advice_points = summary_points[3:5]
        return {
            "dimension": dimension,
            "version": version,
            "summary_points": summary_points[:7],
            "evidence_points": evidence_points[:7],
            "advice_points": advice_points[:5],
            "confidence": None,
            "updated_at": now,
            "sources": [{"model": model_used or "fallback", "time": now}],
        }

    def _merge_unique(self, items: List[str], limit: int) -> List[str]:
        out: List[str] = []
        seen = set()
        for x in items:
            t = (x or "").strip()
            if not t:
                continue
            k = t.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(t)
            if len(out) >= limit:
                break
        return out

    def merge_dimension_insight(self, current: Optional[Dict[str, Any]], incoming: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(current, dict):
            return incoming
        merged = dict(current)
        merged["dimension"] = incoming.get("dimension") or current.get("dimension")
        merged["version"] = incoming.get("version") or current.get("version")
        merged["updated_at"] = incoming.get("updated_at") or datetime.now().isoformat()

        sp = self._merge_unique(
            self._normalize_str_list(current.get("summary_points")) + self._normalize_str_list(incoming.get("summary_points")),
            7,
        )
        ep = self._merge_unique(
            self._normalize_str_list(current.get("evidence_points")) + self._normalize_str_list(incoming.get("evidence_points")),
            7,
        )
        ap = self._merge_unique(
            self._normalize_str_list(current.get("advice_points")) + self._normalize_str_list(incoming.get("advice_points")),
            5,
        )

        merged["summary_points"] = sp
        merged["evidence_points"] = ep
        merged["advice_points"] = ap

        conf = incoming.get("confidence")
        if isinstance(conf, (int, float)):
            merged["confidence"] = conf

        src = []
        for s in (current.get("sources") or []):
            if isinstance(s, dict):
                src.append(s)
        for s in (incoming.get("sources") or []):
            if isinstance(s, dict):
                src.append(s)
        merged["sources"] = src[-6:]
        return merged

    def format_dimension_insight_text(self, insight: Dict[str, Any], max_len: int = 1200) -> str:
        dim = insight.get("dimension") or ""
        ver = insight.get("version") or ""
        sp = self._normalize_str_list(insight.get("summary_points"))
        ep = self._normalize_str_list(insight.get("evidence_points"))
        ap = self._normalize_str_list(insight.get("advice_points"))
        lines = []
        if dim or ver:
            lines.append(f"维度：{dim}（{ver}）".strip())
        if sp:
            lines.append("结论要点：")
            for x in sp:
                lines.append(f"- {x}")
        if ep:
            lines.append("依据点：")
            for x in ep:
                lines.append(f"- {x}")
        if ap:
            lines.append("建议：")
            for x in ap:
                lines.append(f"- {x}")
        text = "\n".join(lines).strip()
        if len(text) > max_len:
            return text[:max_len] + "..."
        return text

    def upsert_structured_insight(
        self,
        user_id: str,
        dimension: str,
        version: str,
        analysis_content: str,
        model_used: Optional[str] = None,
        importance: int = 8,
    ) -> Dict[str, Any]:
        incoming = self.summarize_dimension_insight(
            user_id=user_id,
            dimension=dimension,
            version=version,
            analysis_content=analysis_content,
            model_used=model_used,
        )

        doc = self.get_insights_doc(user_id)
        dims = doc.setdefault("dimensions", {})
        d = dims.setdefault(dimension, {})
        vs = d.setdefault("versions", {})
        bucket = vs.setdefault(version, {"current": None, "history": []})
        current = bucket.get("current")
        merged = self.merge_dimension_insight(current, incoming)

        if current and isinstance(current, dict):
            history = bucket.get("history") or []
            if isinstance(history, list):
                history = [h for h in history if isinstance(h, dict)]
            else:
                history = []
            history.insert(0, current)
            bucket["history"] = history[:3]

        bucket["current"] = merged
        bucket["updated_at"] = merged.get("updated_at")
        bucket["importance"] = importance
        self.save_insights_doc(user_id, doc)

        if self.vector_memory:
            try:
                safe_dim = self._safe_user_id(dimension)[:64]
                mem_id = f"insight_{safe_dim}_{version}_current"
                text = self.format_dimension_insight_text(merged, max_len=1200)
                self.vector_memory.upsert(
                    user_id=user_id,
                    memory_id=mem_id,
                    text=text,
                    metadata={
                        "type": "insight",
                        "dimension": dimension,
                        "version": version,
                        "model_used": model_used,
                        "importance": importance,
                        "updated_at": merged.get("updated_at"),
                    },
                )
            except Exception:
                pass

        return merged

    def get_latest_dimension_insight(self, user_id: str, dimension: str) -> str:
        doc = self.get_insights_doc(user_id)
        dims = doc.get("dimensions") if isinstance(doc, dict) else None
        if isinstance(dims, dict):
            d = dims.get(dimension)
            if isinstance(d, dict):
                vs = d.get("versions")
                best = None
                best_ts = ""
                if isinstance(vs, dict):
                    for v, b in vs.items():
                        if not isinstance(b, dict):
                            continue
                        cur = b.get("current")
                        ts = (cur.get("updated_at") if isinstance(cur, dict) else None) or ""
                        if ts > best_ts:
                            best_ts = ts
                            best = cur
                if isinstance(best, dict):
                    return self.format_dimension_insight_text(best, max_len=1800)

        try:
            memories = self.user_manager.get_user_memories(user_id, limit=200)
            latest = None
            for m in memories:
                md = m.metadata or {}
                if md.get("dimension") == dimension:
                    latest = m
                    break
            return latest.content if latest else ""
        except Exception:
            return ""

    def _stem_to_element(self, stem_char: str) -> Optional[str]:
        m = {
            "甲": "木",
            "乙": "木",
            "丙": "火",
            "丁": "火",
            "戊": "土",
            "己": "土",
            "庚": "金",
            "辛": "金",
            "壬": "水",
            "癸": "水",
        }
        return m.get(stem_char)

    @staticmethod
    def _parse_date_value(value: Any) -> Optional[date]:
        if not value:
            return None
        text = str(value).strip()
        match = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", text)
        if not match:
            return None
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return BaziMemoryManager._safe_date(year, month, day)

    @staticmethod
    def _safe_date(year: int, month: int, day: int) -> Optional[date]:
        try:
            return date(int(year), int(month), int(day))
        except Exception:
            # Handles leap-day anchors by falling back to the closest valid day.
            for fallback_day in range(min(int(day), 28), 0, -1):
                try:
                    return date(int(year), int(month), fallback_day)
                except Exception:
                    continue
        return None

    @classmethod
    def _annotate_dayun_dates(cls, dayun_list: List[Dict[str, Any]], start_date: Any) -> None:
        anchor = cls._parse_date_value(start_date)
        if not anchor or not isinstance(dayun_list, list):
            return

        starts: List[tuple[Dict[str, Any], date]] = []
        for item in dayun_list:
            if not isinstance(item, dict):
                continue
            start_year = item.get("start_year")
            if not isinstance(start_year, int):
                continue
            exact_start = cls._safe_date(start_year, anchor.month, anchor.day)
            if not exact_start:
                continue
            item["start_date"] = exact_start.isoformat()
            starts.append((item, exact_start))

        for idx, (item, _) in enumerate(starts):
            next_start = starts[idx + 1][1] if idx + 1 < len(starts) else None
            if not next_start:
                end_year = item.get("end_year")
                if isinstance(end_year, int):
                    next_start = cls._safe_date(end_year + 1, anchor.month, anchor.day)
            if next_start:
                item["end_date"] = (next_start - timedelta(days=1)).isoformat()
            elif isinstance(item.get("end_year"), int):
                item["end_date"] = f"{item.get('end_year')}-12-31"

    @staticmethod
    def _select_current_dayun(dayun_list: List[Dict[str, Any]], as_of: Optional[date] = None) -> Optional[Dict[str, Any]]:
        if not isinstance(dayun_list, list) or not dayun_list:
            return None

        today = as_of or date.today()
        for item in dayun_list:
            if not isinstance(item, dict):
                continue
            start = BaziMemoryManager._parse_date_value(item.get("start_date"))
            end = BaziMemoryManager._parse_date_value(item.get("end_date"))
            if start and end and start <= today <= end:
                return {
                    "ganzhi": item.get("ganzhi"),
                    "start_year": item.get("start_year"),
                    "end_year": item.get("end_year"),
                    "start_date": item.get("start_date"),
                    "end_date": item.get("end_date"),
                }

        current_year = today.year
        for item in dayun_list:
            if not isinstance(item, dict):
                continue
            sy = item.get("start_year")
            ey = item.get("end_year")
            if isinstance(sy, int) and isinstance(ey, int) and sy <= current_year <= ey:
                return {"ganzhi": item.get("ganzhi"), "start_year": sy, "end_year": ey}
        return None

    def _normalize_chart_facts_dayun(self, chart_facts: Any) -> None:
        if not isinstance(chart_facts, dict):
            return
        dayun = chart_facts.get("dayun")
        if not isinstance(dayun, dict):
            return
        dayun_list = dayun.get("list")
        if not isinstance(dayun_list, list):
            return
        self._annotate_dayun_dates(dayun_list, dayun.get("start_date"))
        current = self._select_current_dayun(dayun_list)
        if current:
            dayun["current"] = current

    def build_chart_facts_v1(
        self,
        user_id: str,
        user_info: Dict[str, Any],
        raw_data: Dict[str, Any],
        raw_file_path: Optional[str] = None,
        parsed_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        identity = {
            "name": user_info.get("name") or user_info.get("username"),
            "gender": "男" if user_info.get("gender") == 1 else "女" if user_info.get("gender") == 0 else raw_data.get("性别"),
            "birth_time_iso": user_info.get("birth_time"),
            "solar": raw_data.get("阳历"),
            "lunar": raw_data.get("农历"),
        }

        core = {
            "bazi": raw_data.get("八字"),
            "day_master": raw_data.get("日主"),
            "zodiac": raw_data.get("生肖"),
        }

        def pillar_from(raw_pillar: Any) -> Dict[str, Any]:
            if not isinstance(raw_pillar, dict):
                return {}
            stem = raw_pillar.get("天干") or {}
            branch = raw_pillar.get("地支") or {}
            hidden = (branch.get("藏干") or {}) if isinstance(branch, dict) else {}
            hidden_norm = {}
            if isinstance(hidden, dict):
                for k, nk in [("主气", "main"), ("中气", "middle"), ("余气", "rest")]:
                    v = hidden.get(k)
                    if isinstance(v, dict):
                        hidden_norm[nk] = {"char": v.get("天干"), "ten_god": v.get("十神")}

            pillar = {
                "stem": {
                    "char": stem.get("天干") if isinstance(stem, dict) else None,
                    "element": stem.get("五行") if isinstance(stem, dict) else None,
                    "yin_yang": stem.get("阴阳") if isinstance(stem, dict) else None,
                    "ten_god": stem.get("十神") if isinstance(stem, dict) else None,
                },
                "branch": {
                    "char": branch.get("地支") if isinstance(branch, dict) else None,
                    "element": branch.get("五行") if isinstance(branch, dict) else None,
                    "yin_yang": branch.get("阴阳") if isinstance(branch, dict) else None,
                    "hidden_stems": hidden_norm,
                },
                "nayin": raw_pillar.get("纳音"),
                "xun": raw_pillar.get("旬"),
                "kongwang": raw_pillar.get("空亡"),
                "xingyun": raw_pillar.get("星运"),
                "zizuo": raw_pillar.get("自坐"),
            }
            return pillar

        pillars = {
            "year": pillar_from(raw_data.get("年柱")),
            "month": pillar_from(raw_data.get("月柱")),
            "day": pillar_from(raw_data.get("日柱")),
            "hour": pillar_from(raw_data.get("时柱")),
        }

        ten_gods_visible = {
            "year_stem": pillars["year"].get("stem", {}).get("ten_god"),
            "month_stem": pillars["month"].get("stem", {}).get("ten_god"),
            "day_stem": None,
            "hour_stem": pillars["hour"].get("stem", {}).get("ten_god"),
        }

        def hidden_list(p: Dict[str, Any]) -> List[str]:
            hs = (p.get("branch") or {}).get("hidden_stems") or {}
            out: List[str] = []
            if not isinstance(hs, dict):
                return out
            for k in ["main", "middle", "rest"]:
                v = hs.get(k) or {}
                tg = v.get("ten_god") if isinstance(v, dict) else None
                if tg:
                    out.append(tg)
            return out

        ten_gods_hidden = {
            "year_branch": hidden_list(pillars["year"]),
            "month_branch": hidden_list(pillars["month"]),
            "day_branch": hidden_list(pillars["day"]),
            "hour_branch": hidden_list(pillars["hour"]),
        }

        counts: Dict[str, int] = {}
        for v in ten_gods_visible.values():
            if v:
                counts[v] = counts.get(v, 0) + 1
        for lst in ten_gods_hidden.values():
            for v in lst:
                if v:
                    counts[v] = counts.get(v, 0) + 1

        ten_gods = {"visible": ten_gods_visible, "hidden": ten_gods_hidden, "counts": counts}

        method = {
            "stem_weight": 1.0,
            "branch_weight": 1.0,
            "hidden_main_weight": 0.6,
            "hidden_middle_weight": 0.3,
            "hidden_rest_weight": 0.1,
        }
        fe_score: Dict[str, float] = {"木": 0.0, "火": 0.0, "土": 0.0, "金": 0.0, "水": 0.0}

        for key in ["year", "month", "day", "hour"]:
            p = pillars.get(key) or {}
            stem_el = (p.get("stem") or {}).get("element")
            branch_el = (p.get("branch") or {}).get("element")
            if stem_el in fe_score:
                fe_score[stem_el] += method["stem_weight"]
            if branch_el in fe_score:
                fe_score[branch_el] += method["branch_weight"]

            hs = (p.get("branch") or {}).get("hidden_stems") or {}
            if isinstance(hs, dict):
                for hk, w in [("main", method["hidden_main_weight"]), ("middle", method["hidden_middle_weight"]), ("rest", method["hidden_rest_weight"])]:
                    hv = hs.get(hk) or {}
                    hchar = hv.get("char") if isinstance(hv, dict) else None
                    hel = self._stem_to_element(hchar) if hchar else None
                    if hel in fe_score:
                        fe_score[hel] += w

        fe_sorted = sorted(fe_score.items(), key=lambda x: x[1], reverse=True)
        fe_interp = "，".join([f"{k}{v:.1f}" for k, v in fe_sorted if v > 0])
        five_elements = {"score": fe_score, "method": method, "interpretation": fe_interp}

        dayun_raw = raw_data.get("大运") if isinstance(raw_data.get("大运"), dict) else {}
        dayun_list_raw = dayun_raw.get("大运") if isinstance(dayun_raw, dict) else []
        dayun_list: List[Dict[str, Any]] = []
        if isinstance(dayun_list_raw, list):
            for da in dayun_list_raw:
                if not isinstance(da, dict):
                    continue
                item = {
                    "ganzhi": da.get("干支"),
                    "start_year": da.get("开始年份"),
                    "end_year": da.get("结束"),
                    "start_age": da.get("开始年龄"),
                    "end_age": da.get("结束年龄"),
                    "stem_ten_god": da.get("天干十神"),
                    "branch_ten_gods": da.get("地支十神"),
                    "branch_hidden_stems": da.get("地支藏干"),
                }
                dayun_list.append(item)

        start_date = dayun_raw.get("起运日期") if isinstance(dayun_raw, dict) else None
        self._annotate_dayun_dates(dayun_list, start_date)
        current = self._select_current_dayun(dayun_list)

        dayun = {
            "start_date": start_date,
            "start_age": dayun_raw.get("起运年龄") if isinstance(dayun_raw, dict) else None,
            "list": dayun_list,
            "current": current,
        }

        shensha = raw_data.get("神煞") if isinstance(raw_data.get("神煞"), dict) else {}
        shensha_norm = {
            "year": shensha.get("年柱") if isinstance(shensha, dict) else None,
            "month": shensha.get("月柱") if isinstance(shensha, dict) else None,
            "day": shensha.get("日柱") if isinstance(shensha, dict) else None,
            "hour": shensha.get("时柱") if isinstance(shensha, dict) else None,
        }

        relations_raw = raw_data.get("刑冲合会") if isinstance(raw_data.get("刑冲合会"), dict) else {}
        half_combos: List[Dict[str, Any]] = []
        arch: List[Dict[str, Any]] = []
        if isinstance(relations_raw, dict):
            for pillar_key, entry in relations_raw.items():
                if not isinstance(entry, dict):
                    continue
                dz = entry.get("地支") if isinstance(entry.get("地支"), dict) else {}
                half = dz.get("半合") if isinstance(dz, dict) else None
                if isinstance(half, list):
                    for h in half:
                        if not isinstance(h, dict):
                            continue
                        half_combos.append(
                            {
                                "pillar": pillar_key,
                                "with_pillar": h.get("柱"),
                                "element": h.get("元素"),
                                "note": h.get("知识点"),
                            }
                        )
                g = entry.get("拱") if isinstance(entry.get("拱"), dict) else None
                if isinstance(g, dict):
                    arch.append(
                        {
                            "pillar": pillar_key,
                            "with_pillar": g.get("柱"),
                            "target": g.get("拱"),
                            "note": g.get("知识点"),
                        }
                    )

        relations = {"half_combos": half_combos, "arch": arch}

        chart_facts = {
            "schema_version": "chart_facts_v1",
            "user_id": user_id,
            "source": {
                "provider": "bazi_mcp",
                "parsed_time": parsed_time,
                "raw_file": raw_file_path,
            },
            "identity": identity,
            "core": core,
            "pillars": pillars,
            "ten_gods": ten_gods,
            "five_elements": five_elements,
            "dayun": dayun,
            "shensha": shensha_norm,
            "relations": relations,
            "summary": {
                "chart_facts_text": "",
                "updated_at": datetime.now().isoformat(),
                "generator": os.getenv("MEMORY_ORGANIZER_MODEL") or "deepseek-v4-flash",
            },
        }
        return chart_facts

    def generate_chart_facts_summary(self, chart_facts: Dict[str, Any]) -> str:
        identity = chart_facts.get("identity") or {}
        core = chart_facts.get("core") or {}
        fe = (chart_facts.get("five_elements") or {}).get("score") or {}
        dayun = chart_facts.get("dayun") or {}
        current = dayun.get("current") or {}

        use_ai_summary = os.getenv("ENABLE_AI_CHART_FACTS_SUMMARY", "false").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        deepseek_key = os.getenv("DEEPSEEK_API_KEY") if use_ai_summary else None
        if deepseek_key and openai is not None:
            try:
                deepseek_base = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com"
                organizer_model = os.getenv("MEMORY_ORGANIZER_MODEL") or "deepseek-v4-flash"
                client = openai.OpenAI(api_key=deepseek_key, base_url=deepseek_base)
                payload = {
                    "identity": identity,
                    "core": core,
                    "pillars": chart_facts.get("pillars"),
                    "ten_gods": chart_facts.get("ten_gods"),
                    "five_elements": chart_facts.get("five_elements"),
                    "dayun": {"start_age": dayun.get("start_age"), "start_date": dayun.get("start_date"), "current": current},
                    "shensha": chart_facts.get("shensha"),
                    "relations": chart_facts.get("relations"),
                }
                prompt = json.dumps(payload, ensure_ascii=False)
                resp = client.chat.completions.create(
                    model=organizer_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是命盘事实摘要器。基于输入JSON输出一段中文事实摘要（400-800字），只陈述事实，不做吉凶判断；包含：八字、日主、四柱关键信息、十神分布概览、五行评分概览、当前大运。不得输出JSON。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=800,
                )
                text = (resp.choices[0].message.content or "").strip()
                return text
            except Exception:
                pass

        fe_sorted = sorted([(k, v) for k, v in fe.items() if isinstance(v, (int, float))], key=lambda x: x[1], reverse=True)
        fe_text = "，".join([f"{k}{float(v):.1f}" for k, v in fe_sorted if float(v) > 0])
        cur_text = ""
        if current.get("ganzhi"):
            year_part = f"{current.get('start_year')}-{current.get('end_year')}"
            date_part = ""
            if current.get("start_date") or current.get("end_date"):
                date_part = f"，{current.get('start_date') or '未知'}至{current.get('end_date') or '未知'}"
            cur_text = f"当前大运：{current.get('ganzhi')}（{year_part}{date_part}）"
        parts = [
            f"命主：{identity.get('gender') or '未知'}，阳历{identity.get('solar') or '未知'}，农历{identity.get('lunar') or '未知'}",
            f"八字：{core.get('bazi') or '未知'}，日主：{core.get('day_master') or '未知'}，生肖：{core.get('zodiac') or '未知'}",
            f"五行评分（规则权重法）：{fe_text}" if fe_text else "五行评分（规则权重法）：暂无",
            cur_text,
        ]
        return "\n".join([p for p in parts if p]).strip()

    def format_chart_facts_context(self, chart_facts: Dict[str, Any], max_dayun_items: int = 12) -> str:
        """Format stable chart facts for prompt injection, including complete Da Yun rows."""
        if not isinstance(chart_facts, dict):
            return ""

        self._normalize_chart_facts_dayun(chart_facts)
        summary_text = ((chart_facts.get("summary") or {}).get("chart_facts_text") or "").strip()
        dayun = chart_facts.get("dayun") or {}
        current = dayun.get("current") or {}
        dayun_list = dayun.get("list") or []
        lines: List[str] = []

        if summary_text:
            summary_lines = [ln for ln in summary_text.splitlines() if not ln.strip().startswith("当前大运：")]
            lines.append("\n".join(summary_lines).strip())

        dayun_lines: List[str] = []
        start_age = dayun.get("start_age")
        start_date = dayun.get("start_date")
        if start_age is not None:
            dayun_lines.append(f"起运年龄：{start_age}岁")
        if start_date:
            dayun_lines.append(f"起运日期：{start_date}")

        if current.get("ganzhi"):
            year_text = ""
            if current.get("start_year") is not None or current.get("end_year") is not None:
                year_text = f"（{current.get('start_year') or '未知'}-{current.get('end_year') or '未知'}"
                if current.get("start_date") or current.get("end_date"):
                    year_text += f"，{current.get('start_date') or '未知'}至{current.get('end_date') or '未知'}"
                year_text += "）"
            current_line = f"当前大运：{current.get('ganzhi')}{year_text}"
            dayun_lines.append(current_line)

        if isinstance(dayun_list, list) and dayun_list:
            dayun_lines.append("完整大运列表：")
            for idx, item in enumerate(dayun_list[:max_dayun_items], 1):
                if not isinstance(item, dict):
                    continue
                ganzhi = item.get("ganzhi") or "未知"
                start_year = item.get("start_year")
                end_year = item.get("end_year")
                start_age_item = item.get("start_age")
                end_age_item = item.get("end_age")
                year_part = f"{start_year or '未知'}-{end_year or '未知'}"
                if item.get("start_date") or item.get("end_date"):
                    year_part += f"（{item.get('start_date') or '未知'}至{item.get('end_date') or '未知'}）"
                age_part = ""
                if start_age_item is not None or end_age_item is not None:
                    age_part = f"，年龄{start_age_item if start_age_item is not None else '未知'}-{end_age_item if end_age_item is not None else '未知'}"
                god_parts = []
                if item.get("stem_ten_god"):
                    god_parts.append(f"天干十神{item.get('stem_ten_god')}")
                branch_ten_gods = item.get("branch_ten_gods")
                if branch_ten_gods:
                    if isinstance(branch_ten_gods, list):
                        branch_text = "、".join(str(x) for x in branch_ten_gods if x)
                    else:
                        branch_text = str(branch_ten_gods)
                    if branch_text:
                        god_parts.append(f"地支十神{branch_text}")
                god_part = f"，{'，'.join(god_parts)}" if god_parts else ""
                dayun_lines.append(f"{idx}. {ganzhi}：{year_part}{age_part}{god_part}")

        if dayun_lines:
            lines.append("大运信息：\n" + "\n".join(dayun_lines))

        return "\n".join([ln for ln in lines if ln]).strip()

    def update_chart_facts_from_bazi_payload(
        self,
        user_id: str,
        user_info: Dict[str, Any],
        bazi_info: Dict[str, Any],
        raw_file_path: Optional[str] = None,
        parsed_time: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        raw_data = None
        if isinstance(bazi_info, dict):
            raw_data = bazi_info.get("raw_data")
        if not isinstance(raw_data, dict):
            return None

        chart_facts = self.build_chart_facts_v1(
            user_id=user_id,
            user_info=user_info,
            raw_data=raw_data,
            raw_file_path=raw_file_path,
            parsed_time=parsed_time,
        )

        summary_text = self.generate_chart_facts_summary(chart_facts)
        chart_facts["summary"]["chart_facts_text"] = summary_text
        chart_facts["summary"]["updated_at"] = datetime.now().isoformat()
        self.save_chart_facts(user_id, chart_facts)

        if self.vector_memory:
            try:
                self.vector_memory.upsert(
                    user_id=user_id,
                    memory_id="chart_fact_current",
                    text=summary_text,
                    metadata={
                        "type": "chart_fact",
                        "dimension": "全局",
                        "tags": ["命盘", "四柱", "日主", "十神", "五行", "大运", "神煞", "刑冲合会"],
                        "updated_at": chart_facts["summary"]["updated_at"],
                    },
                )
            except Exception:
                pass

        return chart_facts
    
    # ==================== 用户管理方法 ====================
    
    def create_or_get_user(self, 
                          identifier: Optional[str] = None,
                          username: Optional[str] = None,
                          email: Optional[str] = None,
                          phone: Optional[str] = None,
                          metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        创建或获取用户
        
        Args:
            identifier: 用户标识符
            username: 用户名
            email: 邮箱
            phone: 手机号
            metadata: 额外元数据
            
        Returns:
            用户ID
        """
        user = self.user_manager.create_user(
            identifier=identifier,
            username=username,
            email=email,
            phone=phone,
            metadata=metadata
        )
        return user.user_id
    
    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        user = self.user_manager.get_user(user_id)
        if user:
            from dataclasses import asdict
            user_dict = asdict(user)
            user_dict['status'] = user.status.value
            return user_dict
        return None
    
    def update_user_info(self, user_id: str, **kwargs) -> bool:
        """更新用户信息"""
        return self.user_manager.update_user(user_id, **kwargs)
    
    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """获取用户统计信息"""
        return self.user_manager.get_user_stats(user_id)
    
    def cleanup_expired_memories(self) -> int:
        """清理过期记忆"""
        return self.user_manager.cleanup_expired_memories()
        
    def store_bazi_info(self, user_id: str, bazi_data: Dict[str, Any], expires_in_days: Optional[int] = None) -> str:
        """
        存储八字信息到记忆系统
        
        Args:
            user_id: 用户ID
            bazi_data: 八字数据
            expires_in_days: 过期天数
            
        Returns:
            存储结果ID
        """
        try:
            self._ensure_user(user_id=user_id)
            
            # 解析八字数据
            parsed_data = self._parse_bazi_data(bazi_data)
            
            # 构建结构化的记忆内容
            memory_messages = self._build_bazi_memory_messages(parsed_data)
            
            # 存储到向量记忆系统
            if self.vector_memory:
                # 构建简单的文本描述用于向量化
                text_content = f"八字信息: {parsed_data.get('八字', '')}, 生肖: {parsed_data.get('生肖', '')}, 日主: {parsed_data.get('日主', '')}"
                result = self.vector_memory.add(
                    user_id=user_id,
                    text=text_content,
                    metadata={
                        "type": "bazi_info",
                        "category": "personal_astrology",
                        "timestamp": datetime.now().isoformat(),
                        "八字": parsed_data.get('八字', ''),
                        "生肖": parsed_data.get('生肖', ''),
                        "性别": parsed_data.get('性别', ''),
                        "日主": parsed_data.get('日主', ''),
                        "data_source": "mcp_bazi_tool"
                    }
                )
            else:
                # 降级模式：只使用本地文件存储
                result = f"local_storage_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                logger.info("使用降级模式存储八字信息（仅本地文件）")
            
            # 同时存储到用户管理器（用于过期管理和高级功能）
            for message in memory_messages:
                if message["role"] == "user":
                    self.user_manager.add_memory(
                        user_id=user_id,
                        content=message["content"],
                        memory_type=MemoryType.BAZI_INFO,
                        metadata={
                            "八字": parsed_data.get('八字', ''),
                            "生肖": parsed_data.get('生肖', ''),
                            "性别": parsed_data.get('性别', ''),
                            "日主": parsed_data.get('日主', ''),
                            "storage_result": str(result)
                        },
                        tags=["八字", "基本信息", parsed_data.get('生肖', ''), parsed_data.get('日主', '')],
                        importance=9,  # 八字信息重要性很高
                        expires_in_days=expires_in_days
                    )
            
            logger.info(f"八字信息已存储到记忆系统，用户ID: {user_id}")
            return result
                
        except Exception as e:
            logger.error(f"存储八字信息失败: {str(e)}")
            raise

    def store_liuyao_info(self, user_id: str, liuyao_data: Dict[str, Any], expires_in_days: Optional[int] = None) -> str:
        """
        存储六爻信息到记忆系统
        
        Args:
            user_id: 用户ID
            liuyao_data: 六爻数据
            expires_in_days: 过期天数
            
        Returns:
            存储结果ID
        """
        try:
            self._ensure_user(user_id=user_id)
            
            # 构建六爻记忆消息
            memory_messages = []
            original_hexagram = liuyao_data.get("originalHexagram") or liuyao_data.get("original_hexagram") or {}
            changed_hexagram = liuyao_data.get("changedHexagram") or liuyao_data.get("changed_hexagram") or {}
            
            hexagram_info = f"""
我的六爻排盘信息：
- 起卦时间：{liuyao_data.get('timestamp', '未知')}
- 起卦方式：{liuyao_data.get('method', '未知')}
- 本卦：{original_hexagram.get('name', '未知')}
- 变卦：{changed_hexagram.get('name', '无') if isinstance(changed_hexagram, dict) else '无'}
"""
            memory_messages.append({"role": "user", "content": hexagram_info})
            
            # 存储到向量记忆系统
            if self.vector_memory:
                # 使用本地向量记忆
                result = self.vector_memory.add(
                    user_id=user_id,
                    text=hexagram_info,
                    metadata={
                        "type": "liuyao_info",
                        "domain": "liuyao",
                        "dimension": "六爻占卜",
                        "category": "divination",
                        "timestamp": datetime.now().isoformat(),
                        "original_hexagram": original_hexagram.get('name', ''),
                        "data_source": "mcp_liuyao_tool"
                    }
                )
            else:
                result = f"local_liuyao_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                logger.info("使用降级模式存储六爻信息（仅本地文件）")
            
            # 同时存储到用户管理器
            self.user_manager.add_memory(
                user_id=user_id,
                content=hexagram_info,
                memory_type=MemoryType.LIUYAO_INFO,
                metadata={
                    "domain": "liuyao",
                    "dimension": "六爻占卜",
                    "original_hexagram": original_hexagram.get('name', ''),
                    "storage_result": str(result)
                },
                tags=["六爻", "占卜", original_hexagram.get('name', '')],
                importance=8,
                expires_in_days=expires_in_days
            )
            
            logger.info(f"六爻信息已存储到记忆系统，用户ID: {user_id}")
            return result
                
        except Exception as e:
            logger.error(f"存储六爻信息失败: {str(e)}")
            raise

    def store_qimen_info(self, user_id: str, qimen_data: Dict[str, Any], expires_in_days: Optional[int] = None) -> str:
        """
        存储奇门遁甲信息到记忆系统
        
        Args:
            user_id: 用户ID
            qimen_data: 奇门数据
            expires_in_days: 过期天数
            
        Returns:
            存储结果ID
        """
        try:
            self._ensure_user(user_id=user_id)
            
            # 构建奇门记忆消息
            memory_messages = []
            
            chart_info = qimen_data.get('chart', {})
            info = qimen_data.get('info', {})
            
            qimen_text = f"""
我的奇门遁甲排盘信息：
- 时间：{info.get('year')}年{info.get('month')}月{info.get('day')}日 {info.get('hour')}时
- 局数：{info.get('dun_type', '')}{info.get('bureau_number', '')}局
- 值符：{info.get('lead_star', '')}
- 值使：{info.get('lead_door', '')}
"""
            memory_messages.append({"role": "user", "content": qimen_text})
            
            # 存储到向量记忆系统
            if self.vector_memory:
                # 使用本地向量记忆
                result = self.vector_memory.add(
                    user_id=user_id,
                    text=qimen_text,
                    metadata={
                        "type": "qimen_info",
                        "domain": "qimen",
                        "dimension": "奇门遁甲",
                        "category": "divination",
                        "timestamp": datetime.now().isoformat(),
                        "bureau": f"{info.get('dun_type', '')}{info.get('bureau_number', '')}局",
                        "data_source": "mcp_qimen_tool"
                    }
                )
            else:
                result = f"local_qimen_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                logger.info("使用降级模式存储奇门信息（仅本地文件）")
            
            # 同时存储到用户管理器
            self.user_manager.add_memory(
                user_id=user_id,
                content=qimen_text,
                memory_type=MemoryType.QIMEN_INFO,
                metadata={
                    "domain": "qimen",
                    "dimension": "奇门遁甲",
                    "bureau": f"{info.get('dun_type', '')}{info.get('bureau_number', '')}局",
                    "storage_result": str(result)
                },
                tags=["奇门遁甲", "占卜", f"{info.get('dun_type', '')}遁"],
                importance=8,
                expires_in_days=expires_in_days
            )
            
            logger.info(f"奇门信息已存储到记忆系统，用户ID: {user_id}")
            return result
                
        except Exception as e:
            logger.error(f"存储奇门信息失败: {str(e)}")
            raise
    
    def _parse_bazi_data(self, bazi_data: Dict[str, Any]) -> Dict[str, Any]:
        """解析八字数据，支持多种数据格式"""
        parsed_data = {}
        
        # 优先使用raw_data
        if "raw_data" in bazi_data and isinstance(bazi_data["raw_data"], dict):
            parsed_data = bazi_data["raw_data"]
        # 如果没有raw_data，尝试解析text_result
        elif "text_result" in bazi_data:
            try:
                text_result = bazi_data["text_result"]
                if isinstance(text_result, str):
                    parsed_data = json.loads(text_result)
                else:
                    parsed_data = text_result
            except json.JSONDecodeError:
                logger.warning("无法解析text_result JSON，使用原始文本")
                parsed_data = {"原始数据": text_result}
        else:
            # 使用整个bazi_data作为备选
            parsed_data = bazi_data
            
        return parsed_data
    
    def _build_bazi_memory_messages(self, parsed_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """构建八字记忆消息"""
        messages = []
        
        # 基本信息消息
        basic_info = f"""
我的八字基本信息：
- 性别：{parsed_data.get('性别', '未知')}
- 阳历生日：{parsed_data.get('阳历', '未知')}
- 农历生日：{parsed_data.get('农历', '未知')}
- 八字：{parsed_data.get('八字', '未知')}
- 生肖：{parsed_data.get('生肖', '未知')}
- 日主：{parsed_data.get('日主', '未知')}
"""
        messages.append({"role": "user", "content": basic_info})
        
        # 四柱详情
        if all(key in parsed_data for key in ['年柱', '月柱', '日柱', '时柱']):
            pillars_info = "我的四柱详情：\n"
            for pillar_name, pillar_key in [("年柱", "年柱"), ("月柱", "月柱"), ("日柱", "日柱"), ("时柱", "时柱")]:
                pillar = parsed_data.get(pillar_key, {})
                if isinstance(pillar, dict):
                    天干 = pillar.get('天干', {})
                    地支 = pillar.get('地支', {})
                    pillars_info += f"- {pillar_name}：{天干.get('天干', '')} {地支.get('地支', '')} "
                    pillars_info += f"({pillar.get('纳音', '')}) "
                    pillars_info += f"十神：{天干.get('十神', '')}\n"
            
            messages.append({"role": "user", "content": pillars_info})
        
        # 大运信息
        if "大运" in parsed_data and isinstance(parsed_data["大运"], dict):
            dayun = parsed_data["大运"]
            dayun_info = f"""
我的大运信息：
- 起运年龄：{dayun.get('起运年龄', '未知')}岁
- 起运日期：{dayun.get('起运日期', '未知')}
"""
            # 添加当前大运
            dayun_list = dayun.get('大运', [])
            if dayun_list:
                current_year = datetime.now().year
                for da in dayun_list:
                    if da.get('开始年份', 0) <= current_year <= da.get('结束', 0):
                        dayun_info += f"- 当前大运：{da.get('干支', '')} ({da.get('开始年份', '')}-{da.get('结束', '')})\n"
                        break
            
            messages.append({"role": "user", "content": dayun_info})
        
        # 神煞信息
        if "神煞" in parsed_data and isinstance(parsed_data["神煞"], dict):
            shensha = parsed_data["神煞"]
            shensha_info = "我的神煞信息：\n"
            for zhu, sha_list in shensha.items():
                if isinstance(sha_list, list) and sha_list:
                    shensha_info += f"- {zhu}：{', '.join(sha_list)}\n"
            
            if len(shensha_info) > 20:  # 只有当有实际内容时才添加
                messages.append({"role": "user", "content": shensha_info})
        
        return messages
            
    def store_analysis_result(self, user_id: str, analysis: Dict[str, Any], expires_in_days: Optional[int] = 365) -> str:
        """
        存储AI分析结果
        
        Args:
            user_id: 用户ID
            analysis: 分析结果
            expires_in_days: 过期天数，默认365天
            
        Returns:
            存储结果ID
        """
        try:
            self._ensure_user(user_id=user_id)
            
            # 构建分析结果消息
            analysis_messages = []
            
            analysis_content = f"""
AI算命分析结果（{analysis.get('analysis_time', datetime.now().isoformat())}）：

"""
            
            # 添加各个AI的分析结果
            if "deepseek_analysis" in analysis:
                analysis_content += f"DeepSeek分析：\n{analysis['deepseek_analysis']}\n\n"
            
            if "gemini_analysis" in analysis:
                analysis_content += f"Gemini分析：\n{analysis['gemini_analysis']}\n\n"
            
            analysis_messages.append({"role": "assistant", "content": analysis_content})
            
            # 存储到向量记忆系统
            if self.vector_memory:
                result = self.vector_memory.add(
                    user_id=user_id,
                    text=analysis_content,
                    metadata={
                        "type": "analysis_result",
                        "category": "ai_fortune_telling",
                        "timestamp": datetime.now().isoformat(),
                        "has_deepseek": "deepseek_analysis" in analysis,
                        "has_gemini": "gemini_analysis" in analysis,
                        "analysis_count": len([k for k in analysis.keys() if k.endswith('_analysis')])
                    }
                )
            else:
                # 降级模式：只使用本地文件存储
                result = f"local_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                logger.info("使用降级模式存储分析结果（仅本地文件）")
            
            # 同时存储到用户管理器
            self.user_manager.add_memory(
                user_id=user_id,
                content=analysis_content,
                memory_type=MemoryType.ANALYSIS_RESULT,
                metadata={
                    "analysis_time": analysis.get('analysis_time', ''),
                    "ai_models": [k for k in analysis.keys() if k.endswith('_analysis')],
                    "storage_result": str(result)
                },
                tags=["AI分析", "算命结果", "预测"],
                importance=8,  # 分析结果重要性较高
                expires_in_days=expires_in_days
            )
            
            logger.info(f"AI分析结果已存储到记忆系统，用户ID: {user_id}")
            return result
            
        except Exception as e:
            logger.error(f"存储AI分析结果失败: {str(e)}")
            raise
    
    def store_bazi_analysis(self, 
                          user_id: str, 
                          dimension: str,
                          analysis_content: str,
                          analysis_version: str = "classic",
                          bazi_info: Optional[Dict[str, Any]] = None,
                          user_background: Optional[Dict[str, Any]] = None,
                          model_used: Optional[str] = None,
                          importance: int = 8,
                          expires_in_days: Optional[int] = 365) -> str:
        """
        存储八字分析结果到记忆系统
        
        Args:
            user_id: 用户ID
            dimension: 分析维度 (如: 日元核心分析)
            analysis_content: 分析内容
            analysis_version: 分析版本 (classic/wisdom/master)
            bazi_info: 八字信息
            user_background: 用户背景信息
            model_used: 使用的AI模型
            importance: 重要性等级 (1-10)
            expires_in_days: 过期天数
            
        Returns:
            存储结果ID
        """
        try:
            self._ensure_user(
                user_id=user_id,
                username=user_background.get('name', user_id) if user_background else user_id,
                metadata=user_background or {},
            )
            
            # 构建结构化的分析记录
            timestamp = datetime.now().isoformat()
            
            # 构建分析记录内容
            content_parts = [
                f"📊 八字命理分析记录",
                f"🔍 分析维度：{dimension}",
                f"🎯 分析版本：{analysis_version}",
                f"⏰ 分析时间：{timestamp}",
                f"🤖 使用模型：{model_used or '未知'}",
                "",
                "📝 分析内容：",
                analysis_content
            ]
            
            # 如果有用户背景信息，加入记录
            if user_background:
                user_info_parts = []
                if user_background.get('name'):
                    user_info_parts.append(f"姓名：{user_background['name']}")
                if user_background.get('gender'):
                    user_info_parts.append(f"性别：{user_background['gender']}")
                
                if user_info_parts:
                    content_parts.insert(1, f"👤 用户信息：{' | '.join(user_info_parts)}")
            
            memory_content = "\n".join(content_parts)
            
            # 准备消息格式
            messages = [{"role": "assistant", "content": memory_content}]
            
            # 存储到向量记忆系统
            if self.vector_memory:
                result = self.vector_memory.add(
                    user_id=user_id,
                    text=memory_content,
                    metadata={
                        "type": "bazi_analysis",
                        "category": "fortune_telling",
                        "dimension": dimension,
                        "version": analysis_version,
                        "model_used": model_used,
                        "timestamp": timestamp,
                        "importance": importance,
                        "content_length": len(analysis_content)
                    }
                )
            else:
                # 降级模式：只使用本地文件存储
                result = f"local_bazi_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                logger.info("使用降级模式存储八字分析结果（仅本地文件）")
            
            # 同时存储到用户管理器
            self.user_manager.add_memory(
                user_id=user_id,
                content=memory_content,
                memory_type=MemoryType.ANALYSIS_RESULT,
                metadata={
                    "dimension": dimension,
                    "version": analysis_version,
                    "model_used": model_used,
                    "analysis_time": timestamp,
                    "storage_result": str(result)
                },
                tags=["八字分析", dimension, analysis_version, "AI预测"],
                importance=importance,
                expires_in_days=expires_in_days
            )
            
            logger.info(f"✅ 八字分析结果已存储到记忆系统 - 用户: {user_id}, 维度: {dimension}, 版本: {analysis_version}")
            return str(result)
            
        except Exception as e:
            logger.error(f"❌ 存储八字分析结果失败: {str(e)}")
            raise
            
    def get_user_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取用户历史记录
        
        Args:
            user_id: 用户ID
            limit: 返回记录数量限制
            
        Returns:
            用户历史记录列表
        """
        try:
            # 降级模式：从本地文件存储获取
            user_memories = self.user_manager.get_user_memories(user_id, limit=limit)
            result_list = [{"memory": memory.content, "metadata": memory.metadata} for memory in user_memories]
            
            logger.info(f"获取用户历史记录成功，用户ID: {user_id}, 记录数: {len(result_list)}")
            return result_list
        except Exception as e:
            logger.error(f"获取用户历史记录失败: {str(e)}")
            return []
            
    def search_memories(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        搜索相关记忆
        
        Args:
            user_id: 用户ID
            query: 搜索查询
            limit: 返回结果数量限制
            
        Returns:
            相关记忆列表
        """
        try:
            if self.vector_memory:
                result_list = self.vector_memory.search(user_id=user_id, query=query, limit=limit)
            else:
                # 降级：如果无向量记忆，简单的关键词匹配
                result_list = []
                user_memories = self.user_manager.get_user_memories(user_id)
                for memory in user_memories:
                    if query.lower() in memory.content.lower():
                        result_list.append({"memory": memory.content, "metadata": memory.metadata})
                        if len(result_list) >= limit:
                            break
            
            logger.info(f"记忆搜索完成，用户ID: {user_id}, 查询: {query}, 结果数: {len(result_list)}")
            return result_list
        except Exception as e:
            logger.error(f"记忆搜索失败: {str(e)}")
            return []

    def store_shared_dossier(self, user_id: str, dossier_text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        meta = {
            "type": "chart_fact",
            "dimension": "全局",
            "source": "bazi_mcp",
            "importance": 10,
        }
        if metadata:
            meta.update(metadata)
        if not self.vector_memory:
            raise RuntimeError("向量记忆不可用：缺少依赖或未配置embedding。")
        return self.vector_memory.add(user_id=user_id, text=dossier_text, metadata=meta)

    def store_shared_insight(
        self,
        user_id: str,
        dimension: str,
        insight_text: str,
        analysis_version: str,
        model_used: Optional[str] = None,
        importance: int = 8,
    ) -> str:
        meta = {
            "type": "insight",
            "dimension": dimension,
            "version": analysis_version,
            "model_used": model_used,
            "importance": importance,
        }
        if not self.vector_memory:
            raise RuntimeError("向量记忆不可用：缺少依赖或未配置embedding。")
        return self.vector_memory.add(user_id=user_id, text=insight_text, metadata=meta)

    def store_shared_event(
        self,
        user_id: str,
        dimension: str,
        event_text: str,
        event_type: str,
        model_used: Optional[str] = None,
        importance: int = 5,
    ) -> str:
        meta = {
            "type": event_type,
            "dimension": dimension,
            "model_used": model_used,
            "importance": importance,
        }
        if not self.vector_memory:
            raise RuntimeError("向量记忆不可用：缺少依赖或未配置embedding。")
        return self.vector_memory.add(user_id=user_id, text=event_text, metadata=meta)

    def build_shared_memory_context(self, user_id: str, dimension: str, query: Optional[str] = None, limit: int = 8) -> str:
        if not SHARED_MEMORY_ENABLED:
            return ""
        try:
            task_type = "chat" if query else "analysis"
            built = self.context_builder.build(
                user_id=user_id,
                dimension=dimension,
                query=query,
                task_type=task_type,
                budget_chars=5200 if task_type == "chat" else 6500,
                vector_limit=limit,
            )
            if built:
                return built
        except Exception as e:
            logger.warning("memory v2 context builder failed, falling back to legacy context: %s", e)
        budget_chars = 6500
        lines: list[str] = []
        used = 0

        def _append(line: str) -> None:
            nonlocal used
            t = (line or "").strip()
            if not t:
                return
            if used >= budget_chars:
                return
            remaining = budget_chars - used
            if len(t) > remaining:
                t = t[:remaining].rstrip() + "..."
            lines.append(t)
            used += len(t) + 1

        def _compact_text(text: str, max_len: int) -> str:
            s = (text or "").strip()
            if not s:
                return ""
            if "结论要点：" in s:
                start = s.find("结论要点：")
                seg = s[start:]
                keep_lines = []
                for ln in seg.splitlines():
                    t = ln.strip()
                    if not t:
                        continue
                    keep_lines.append(t)
                    if len(keep_lines) >= 16:
                        break
                s2 = "\n".join(keep_lines).strip()
                if s2:
                    return s2[:max_len] + ("..." if len(s2) > max_len else "")
            s = s.replace("\r\n", "\n")
            out_lines = []
            for ln in s.splitlines():
                t = ln.strip()
                if not t:
                    continue
                out_lines.append(t)
                if len(out_lines) >= 10:
                    break
            s2 = "\n".join(out_lines).strip()
            if len(s2) > max_len:
                return s2[:max_len] + "..."
            return s2

        cf = self.get_chart_facts(user_id)
        if isinstance(cf, dict):
            s = self.format_chart_facts_context(cf, max_dayun_items=12)
            if s:
                if len(s) > 2600:
                    s = s[:2600] + "..."
                _append(f"[chart_fact][全局][ref=chart_fact_current] {s}")

        profile_doc = self.get_profile_doc(user_id)
        profile_text = self.format_profile_text(profile_doc, max_len=700).strip()
        if profile_text:
            _append(f"[profile][全局][ref=profile_current] {profile_text}")

        dim_latest = self.get_latest_dimension_insight(user_id=user_id, dimension=dimension).strip()
        if dim_latest:
            if len(dim_latest) > 900:
                dim_latest = dim_latest[:900] + "..."
            _append(f"[insight][{dimension}] {_compact_text(dim_latest, max_len=780)}")

        dim_seed = {
            "事业运势分析": "事业 官杀 印 枭 食伤 财 比劫 平台 贵人 晋升 方向",
            "感情婚姻分析": "感情 婚姻 夫妻宫 桃花 正缘 正官 七杀 正财 偏财 相处 模式",
            "健康状况分析": "健康 五行 体质 木火土金水 过旺 过弱 冲克 养生 脏腑",
            "大运流年分析": "大运 流年 应期 吉凶 冲合 刑害 用神 忌神 节点 年份",
            "用神忌神分析": "用神 忌神 调候 扶抑 通关 旺衰 格局 喜忌",
            "五行生克分析": "五行 旺衰 生克 制化 通关 平衡",
            "日元核心分析": "日主 日元 旺衰 格局 气势 调候 根气",
            "天干十神分析": "天干 十神 透干 官杀 印 枭 食伤 财 比劫",
            "地支藏干分析": "地支 藏干 提纲 根气 刑冲合会 夫妻宫",
            "综合建议": "建议 取舍 重点 趋吉避凶 用神 落地 行动",
        }.get(dimension, "")
        q = query or f"{dimension} {dim_seed} 日主 十神 五行 用神 大运 流年"
        results = []
        if self.vector_memory:
            try:
                results = self.vector_memory.search(user_id=user_id, query=q, limit=limit)
            except Exception:
                results = []

        seen_ids = set()
        per_type = {"chat": 0, "bazi_analysis": 0, "followup": 0, "analysis": 0, "event": 0, "memory": 0}
        for r in results:
            md = r.get("metadata") or {}
            t = md.get("type") or "memory"
            dim = md.get("dimension") or "全局"
            if t == "chart_fact":
                continue
            if t == "profile":
                continue
            if t == "insight" and dim == dimension and dim_latest:
                continue
            mid = (r.get("memory_id") or "").strip()
            if mid:
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
            text = (r.get("memory") or "").strip()
            if not text:
                continue
            if t == "bazi_analysis" and dim_latest:
                continue
            if t == "chat" and per_type.get("chat", 0) >= 2:
                continue
            if t == "bazi_analysis" and per_type.get("bazi_analysis", 0) >= 1:
                continue
            if t == "followup" and per_type.get("followup", 0) >= 1:
                continue

            compact = _compact_text(text, max_len=640 if t == "chat" else 520)
            if not compact:
                continue
            ref = f"[ref={mid}]" if mid else ""
            _append(f"[{t}][{dim}]{ref} {compact}")
            per_type[t] = per_type.get(t, 0) + 1
            if used >= budget_chars:
                break

        if lines:
            _append("注：以上ref仅用于内部追溯，请勿在回答中直接输出ref。")
        return "\n".join(lines).strip()
    
    def get_user_bazi_summary(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取用户八字信息摘要
        
        Args:
            user_id: 用户ID
            
        Returns:
            八字信息摘要
        """
        try:
            # 搜索八字相关记忆
            bazi_memories = self.search_memories(user_id, "八字 生肖 日主", limit=3)
            
            if not bazi_memories:
                return None
            
            # 提取关键信息
            summary = {
                "user_id": user_id,
                "has_bazi_info": True,
                "memories_count": len(bazi_memories),
                "last_update": datetime.now().isoformat()
            }
            
            # 尝试从记忆中提取八字信息
            for memory in bazi_memories:
                content = memory.get("memory", "")
                if "八字：" in content:
                    # 简单的信息提取
                    lines = content.split('\n')
                    for line in lines:
                        if "八字：" in line:
                            summary["八字"] = line.split("八字：")[1].strip()
                        elif "生肖：" in line:
                            summary["生肖"] = line.split("生肖：")[1].strip()
                        elif "性别：" in line:
                            summary["性别"] = line.split("性别：")[1].strip()
            
            return summary
            
        except Exception as e:
            logger.error(f"获取用户八字摘要失败: {str(e)}")
            return None
    
    # ==================== 高级功能方法 ====================
    
    def batch_delete_memories(self, user_id: str, memory_type: Optional[MemoryType] = None, tags: Optional[List[str]] = None) -> int:
        """
        批量删除记忆
        
        Args:
            user_id: 用户ID
            memory_type: 记忆类型过滤
            tags: 标签过滤
            
        Returns:
            删除的记忆数量
        """
        return self.user_manager.delete_user_memories(user_id, memory_type)
    
    def batch_update_memory_importance(self, user_id: str, importance: int, memory_type: Optional[MemoryType] = None) -> int:
        """
        批量更新记忆重要性
        
        Args:
            user_id: 用户ID
            importance: 新的重要性评分（1-10）
            memory_type: 记忆类型过滤
            
        Returns:
            更新的记忆数量
        """
        updates = {"importance": max(1, min(10, importance))}
        return self.user_manager.batch_update_memories(user_id, updates, memory_type)
    
    def set_memory_expiration(self, user_id: str, expires_in_days: int, memory_type: Optional[MemoryType] = None) -> int:
        """
        批量设置记忆过期时间
        
        Args:
            user_id: 用户ID
            expires_in_days: 过期天数
            memory_type: 记忆类型过滤
            
        Returns:
            更新的记忆数量
        """
        from datetime import timedelta
        expires_at = (datetime.now() + timedelta(days=expires_in_days)).isoformat()
        updates = {"expires_at": expires_at}
        return self.user_manager.batch_update_memories(user_id, updates, memory_type)
    
    def search_user_memories_advanced(self, 
                                    user_id: str,
                                    query: str,
                                    memory_type: Optional[MemoryType] = None,
                                    tags: Optional[List[str]] = None,
                                    min_importance: int = 1,
                                    include_expired: bool = False) -> List[Dict[str, Any]]:
        """
        高级记忆搜索
        
        Args:
            user_id: 用户ID
            query: 搜索查询
            memory_type: 记忆类型过滤
            tags: 标签过滤
            min_importance: 最小重要性
            include_expired: 是否包含过期记忆
            
        Returns:
            匹配的记忆列表
        """
        memories = self.user_manager.search_user_memories(user_id, query, memory_type, tags)
        
        # 过滤重要性和过期状态
        filtered_memories = []
        now = datetime.now()
        
        for memory in memories:
            if memory.importance < min_importance:
                continue
            
            if not include_expired and memory.expires_at:
                expires_at = datetime.fromisoformat(memory.expires_at)
                if now > expires_at:
                    continue
            
            # 转换为字典格式
            from dataclasses import asdict
            memory_dict = asdict(memory)
            memory_dict['memory_type'] = memory.memory_type.value
            filtered_memories.append(memory_dict)
        
        return filtered_memories
    
    def get_memory_analytics(self, user_id: str) -> Dict[str, Any]:
        """
        获取记忆分析报告
        
        Args:
            user_id: 用户ID
            
        Returns:
            分析报告
        """
        stats = self.user_manager.get_user_stats(user_id)
        memories = self.user_manager.get_user_memories(user_id, include_expired=True)
        
        # 计算额外统计信息
        now = datetime.now()
        recent_memories = 0
        high_importance_memories = 0
        expiring_soon = 0
        
        for memory in memories:
            # 最近7天的记忆
            created_at = datetime.fromisoformat(memory.created_at)
            if (now - created_at).days <= 7:
                recent_memories += 1
            
            # 高重要性记忆（>=8分）
            if memory.importance >= 8:
                high_importance_memories += 1
            
            # 即将过期的记忆（7天内）
            if memory.expires_at:
                expires_at = datetime.fromisoformat(memory.expires_at)
                if 0 <= (expires_at - now).days <= 7:
                    expiring_soon += 1
        
        analytics = {
            **stats,
            "recent_memories_7days": recent_memories,
            "high_importance_memories": high_importance_memories,
            "expiring_soon_7days": expiring_soon,
            "memory_growth_rate": recent_memories / 7 if recent_memories > 0 else 0,
            "importance_distribution": self._get_importance_distribution(memories)
        }
        
        return analytics
    
    def _get_importance_distribution(self, memories) -> Dict[str, int]:
        """获取重要性分布"""
        distribution = {f"level_{i}": 0 for i in range(1, 11)}
        for memory in memories:
            distribution[f"level_{memory.importance}"] += 1
        return distribution
    
    def export_user_memories(self, user_id: str, format: str = "json") -> Dict[str, Any]:
        """
        导出用户记忆数据
        
        Args:
            user_id: 用户ID
            format: 导出格式（json, csv等）
            
        Returns:
            导出的数据
        """
        return self.user_manager.export_user_data(user_id)
    
    def merge_duplicate_memories(self, user_id: str, similarity_threshold: float = 0.8) -> int:
        """
        合并重复记忆（简化版本）
        
        Args:
            user_id: 用户ID
            similarity_threshold: 相似度阈值
            
        Returns:
            合并的记忆数量
        """
        memories = self.user_manager.get_user_memories(user_id)
        merged_count = 0
        
        # 简单的重复检测：基于内容长度和关键词
        content_groups = {}
        
        for memory in memories:
            content = memory.content.strip()
            content_key = f"{len(content)}_{hash(content[:50])}"
            
            if content_key not in content_groups:
                content_groups[content_key] = []
            content_groups[content_key].append(memory)
        
        # 合并重复组
        for group in content_groups.values():
            if len(group) > 1:
                # 保留重要性最高的，删除其他的
                group.sort(key=lambda x: x.importance, reverse=True)
                for memory in group[1:]:
                    self.user_manager.delete_memory(memory.memory_id)
                    merged_count += 1
        
        logger.info(f"为用户 {user_id} 合并了 {merged_count} 条重复记忆")
        return merged_count
    
    def schedule_memory_cleanup(self, user_id: str, auto_cleanup: bool = True) -> Dict[str, Any]:
        """
        安排记忆清理任务
        
        Args:
            user_id: 用户ID
            auto_cleanup: 是否自动清理
            
        Returns:
            清理计划
        """
        cleanup_plan = {
            "user_id": user_id,
            "auto_cleanup": auto_cleanup,
            "scheduled_at": datetime.now().isoformat(),
            "actions": []
        }
        
        if auto_cleanup:
            # 清理过期记忆
            expired_count = self.user_manager.cleanup_expired_memories()
            cleanup_plan["actions"].append(f"清理了 {expired_count} 条过期记忆")
            
            # 合并重复记忆
            merged_count = self.merge_duplicate_memories(user_id)
            cleanup_plan["actions"].append(f"合并了 {merged_count} 条重复记忆")
        
        return cleanup_plan

# 测试函数
async def test_memory_storage():
    """测试记忆存储功能"""
    print("🧠 开始测试记忆存储功能...")
    
    # 初始化记忆管理器
    memory_manager = BaziMemoryManager()
    
    # 模拟八字数据（基于实际MCP返回的数据结构）
    test_bazi_data = {
        "birth_time": "",
        "four_pillars": {},
        "five_elements": {},
        "ten_gods": {},
        "lunar_info": {},
        "solar_terms": {},
        "text_result": '{"性别":"男","阳历":"1990年5月15日 14:30:00","农历":"农历庚午年四月廿一癸未时","八字":"庚午 辛巳 庚辰 癸未","生肖":"马","日主":"庚"}',
        "raw_data": {
            "性别": "男",
            "阳历": "1990年5月15日 14:30:00",
            "农历": "农历庚午年四月廿一癸未时",
            "八字": "庚午 辛巳 庚辰 癸未",
            "生肖": "马",
            "日主": "庚",
            "年柱": {
                "天干": {"天干": "庚", "五行": "金", "阴阳": "阳", "十神": "比肩"},
                "地支": {"地支": "午", "五行": "火", "阴阳": "阳"},
                "纳音": "路旁土"
            },
            "月柱": {
                "天干": {"天干": "辛", "五行": "金", "阴阳": "阴", "十神": "劫财"},
                "地支": {"地支": "巳", "五行": "火", "阴阳": "阴"},
                "纳音": "白蜡金"
            },
            "日柱": {
                "天干": {"天干": "庚", "五行": "金", "阴阳": "阳"},
                "地支": {"地支": "辰", "五行": "土", "阴阳": "阳"},
                "纳音": "白蜡金"
            },
            "时柱": {
                "天干": {"天干": "癸", "五行": "水", "阴阳": "阴", "十神": "伤官"},
                "地支": {"地支": "未", "五行": "土", "阴阳": "阴"},
                "纳音": "杨柳木"
            },
            "大运": {
                "起运年龄": 8,
                "起运日期": "1997-8-5",
                "大运": [
                    {"干支": "壬午", "开始年份": 1997, "结束": 2006, "天干十神": "食神"},
                    {"干支": "癸未", "开始年份": 2007, "结束": 2016, "天干十神": "伤官"}
                ]
            },
            "神煞": {
                "年柱": ["月德贵人", "福星贵人"],
                "月柱": ["天德贵人", "劫煞"],
                "日柱": ["月德贵人", "国印"],
                "时柱": ["天乙贵人"]
            }
        },
        "parsed_time": "2025-06-07T16:02:45.511495"
    }
    
    try:
        # 测试存储八字信息
        print("📝 测试存储八字信息...")
        result = memory_manager.store_bazi_info("test_user_001", test_bazi_data)
        print(f"✅ 八字信息存储成功: {result}")
        
        # 测试存储分析结果
        print("🔮 测试存储AI分析结果...")
        test_analysis = {
            "analysis_time": datetime.now().isoformat(),
            "deepseek_analysis": "根据您的八字庚午 辛巳 庚辰 癸未，您是金命人，性格坚毅...",
            "gemini_analysis": "从您的生肖马和日主庚来看，您具有领导才能..."
        }
        analysis_result = memory_manager.store_analysis_result("test_user_001", test_analysis)
        print(f"✅ 分析结果存储成功: {analysis_result}")
        
        # 测试搜索记忆
        print("🔍 测试搜索记忆...")
        search_results = memory_manager.search_memories("test_user_001", "八字 庚午")
        print(f"✅ 搜索到 {len(search_results)} 条相关记忆")
        
        # 测试获取历史记录
        print("📚 测试获取历史记录...")
        history = memory_manager.get_user_history("test_user_001")
        print(f"✅ 获取到 {len(history)} 条历史记录")
        
        # 测试获取八字摘要
        print("📋 测试获取八字摘要...")
        summary = memory_manager.get_user_bazi_summary("test_user_001")
        if summary:
            print(f"✅ 八字摘要: {summary}")
        else:
            print("❌ 未能获取八字摘要")
        
        print("🎉 所有测试完成！")
        
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_memory_storage()) 
