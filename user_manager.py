import uuid
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import os

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UserStatus(Enum):
    """用户状态枚举"""
    ACTIVE = "active"
    INACTIVE = "inactive" 
    SUSPENDED = "suspended"
    DELETED = "deleted"

class MemoryType(Enum):
    """记忆类型枚举"""
    BAZI_INFO = "bazi_info"
    LIUYAO_INFO = "liuyao_info"
    QIMEN_INFO = "qimen_info"
    ANALYSIS_RESULT = "analysis_result"
    USER_PREFERENCE = "user_preference"
    CONSULTATION_HISTORY = "consultation_history"
    CUSTOM = "custom"

@dataclass
class UserProfile:
    """用户档案数据类"""
    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    created_at: str = None
    last_active: str = None
    status: UserStatus = UserStatus.ACTIVE
    preferences: Dict[str, Any] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.last_active is None:
            self.last_active = datetime.now().isoformat()
        if self.preferences is None:
            self.preferences = {}
        if self.metadata is None:
            self.metadata = {}

@dataclass
class MemoryRecord:
    """记忆记录数据类"""
    memory_id: str
    user_id: str
    memory_type: MemoryType
    content: str
    metadata: Dict[str, Any]
    created_at: str
    expires_at: Optional[str] = None
    tags: List[str] = None
    importance: int = 1  # 1-10，重要性评分
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []

class UserManager:
    """用户管理器"""
    
    def __init__(self, data_dir: str = "user_data"):
        """
        初始化用户管理器
        
        Args:
            data_dir: 用户数据存储目录
        """
        self.data_dir = data_dir
        self.users_file = os.path.join(data_dir, "users.json")
        self.memories_file = os.path.join(data_dir, "memories.json")
        
        # 确保数据目录存在
        os.makedirs(data_dir, exist_ok=True)
        
        # 加载现有数据
        self.users: Dict[str, UserProfile] = self._load_users()
        self.memories: Dict[str, MemoryRecord] = self._load_memories()
        
        logger.info(f"用户管理器初始化完成，已加载 {len(self.users)} 个用户，{len(self.memories)} 条记忆")
    
    def _load_users(self) -> Dict[str, UserProfile]:
        """加载用户数据"""
        if not os.path.exists(self.users_file):
            return {}
        
        try:
            with open(self.users_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                users = {}
                for user_id, user_data in data.items():
                    user_data['status'] = UserStatus(user_data.get('status', 'active'))
                    users[user_id] = UserProfile(**user_data)
                return users
        except Exception as e:
            logger.error(f"加载用户数据失败: {e}")
            return {}
    
    def _load_memories(self) -> Dict[str, MemoryRecord]:
        """加载记忆数据"""
        if not os.path.exists(self.memories_file):
            return {}
        
        try:
            with open(self.memories_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                memories = {}
                for memory_id, memory_data in data.items():
                    memory_data['memory_type'] = MemoryType(memory_data.get('memory_type', 'custom'))
                    memories[memory_id] = MemoryRecord(**memory_data)
                return memories
        except Exception as e:
            logger.error(f"加载记忆数据失败: {e}")
            return {}
    
    def _save_users(self):
        """保存用户数据"""
        try:
            data = {}
            for user_id, user in self.users.items():
                user_dict = asdict(user)
                user_dict['status'] = user.status.value
                data[user_id] = user_dict
            
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户数据失败: {e}")
    
    def _save_memories(self):
        """保存记忆数据"""
        try:
            data = {}
            for memory_id, memory in self.memories.items():
                memory_dict = asdict(memory)
                memory_dict['memory_type'] = memory.memory_type.value
                data[memory_id] = memory_dict
            
            with open(self.memories_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存记忆数据失败: {e}")
    
    def generate_user_id(self, identifier: Optional[str] = None) -> str:
        """
        生成唯一用户ID
        
        Args:
            identifier: 可选的标识符（如手机号、邮箱等）
            
        Returns:
            唯一的用户ID
        """
        if identifier:
            # 基于标识符生成确定性ID
            hash_obj = hashlib.sha256(identifier.encode('utf-8'))
            return f"user_{hash_obj.hexdigest()[:16]}"
        else:
            # 生成随机UUID
            return f"user_{uuid.uuid4().hex[:16]}"
    
    def create_user(self, 
                   identifier: Optional[str] = None,
                   username: Optional[str] = None,
                   email: Optional[str] = None,
                   phone: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> UserProfile:
        """
        创建新用户
        
        Args:
            identifier: 用户标识符
            username: 用户名
            email: 邮箱
            phone: 手机号
            metadata: 额外元数据
            
        Returns:
            用户档案
        """
        user_id = self.generate_user_id(identifier)
        
        # 检查用户是否已存在
        if user_id in self.users:
            logger.info(f"用户已存在: {user_id}")
            return self.users[user_id]
        
        # 创建新用户
        user = UserProfile(
            user_id=user_id,
            username=username,
            email=email,
            phone=phone,
            metadata=metadata or {}
        )
        
        self.users[user_id] = user
        self._save_users()
        
        logger.info(f"创建新用户: {user_id}")
        return user
    
    def get_user(self, user_id: str) -> Optional[UserProfile]:
        """获取用户信息"""
        return self.users.get(user_id)
    
    def update_user(self, user_id: str, **kwargs) -> bool:
        """
        更新用户信息
        
        Args:
            user_id: 用户ID
            **kwargs: 要更新的字段
            
        Returns:
            是否更新成功
        """
        if user_id not in self.users:
            return False
        
        user = self.users[user_id]
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        
        user.last_active = datetime.now().isoformat()
        self._save_users()
        
        logger.info(f"更新用户信息: {user_id}")
        return True
    
    def delete_user(self, user_id: str, soft_delete: bool = True) -> bool:
        """
        删除用户
        
        Args:
            user_id: 用户ID
            soft_delete: 是否软删除（仅标记为删除状态）
            
        Returns:
            是否删除成功
        """
        if user_id not in self.users:
            return False
        
        if soft_delete:
            self.users[user_id].status = UserStatus.DELETED
            self._save_users()
        else:
            # 硬删除：删除用户及其所有记忆
            del self.users[user_id]
            self.delete_user_memories(user_id)
            self._save_users()
        
        logger.info(f"删除用户: {user_id} (软删除: {soft_delete})")
        return True
    
    def add_memory(self, 
                   user_id: str,
                   content: str,
                   memory_type: MemoryType = MemoryType.CUSTOM,
                   metadata: Optional[Dict[str, Any]] = None,
                   tags: Optional[List[str]] = None,
                   importance: int = 1,
                   expires_in_days: Optional[int] = None) -> str:
        """
        为用户添加记忆
        
        Args:
            user_id: 用户ID
            content: 记忆内容
            memory_type: 记忆类型
            metadata: 元数据
            tags: 标签
            importance: 重要性（1-10）
            expires_in_days: 过期天数
            
        Returns:
            记忆ID
        """
        if user_id not in self.users:
            raise ValueError(f"用户不存在: {user_id}")
        
        memory_id = f"mem_{uuid.uuid4().hex[:16]}"
        
        expires_at = None
        if expires_in_days:
            expires_at = (datetime.now() + timedelta(days=expires_in_days)).isoformat()
        
        memory = MemoryRecord(
            memory_id=memory_id,
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            metadata=metadata or {},
            created_at=datetime.now().isoformat(),
            expires_at=expires_at,
            tags=tags or [],
            importance=max(1, min(10, importance))
        )
        
        self.memories[memory_id] = memory
        self._save_memories()
        
        logger.info(f"为用户 {user_id} 添加记忆: {memory_id}")
        return memory_id
    
    def get_user_memories(self, 
                         user_id: str,
                         memory_type: Optional[MemoryType] = None,
                         include_expired: bool = False,
                         limit: Optional[int] = None) -> List[MemoryRecord]:
        """
        获取用户记忆
        
        Args:
            user_id: 用户ID
            memory_type: 记忆类型过滤
            include_expired: 是否包含过期记忆
            limit: 限制数量
            
        Returns:
            记忆列表
        """
        memories = []
        now = datetime.now()
        
        for memory in self.memories.values():
            if memory.user_id != user_id:
                continue
            
            if memory_type and memory.memory_type != memory_type:
                continue
            
            # 检查是否过期
            if not include_expired and memory.expires_at:
                expires_at = datetime.fromisoformat(memory.expires_at)
                if now > expires_at:
                    continue
            
            memories.append(memory)
        
        memories.sort(key=lambda x: (x.importance, x.created_at), reverse=True)
        
        if limit:
            memories = memories[:limit]
        
        return memories
    
    def search_user_memories(self, 
                           user_id: str,
                           query: str,
                           memory_type: Optional[MemoryType] = None,
                           tags: Optional[List[str]] = None) -> List[MemoryRecord]:
        """
        搜索用户记忆
        
        Args:
            user_id: 用户ID
            query: 搜索查询
            memory_type: 记忆类型过滤
            tags: 标签过滤
            
        Returns:
            匹配的记忆列表
        """
        memories = self.get_user_memories(user_id, memory_type)
        results = []
        
        query_lower = query.lower()
        
        for memory in memories:
            # 内容匹配
            if query_lower in memory.content.lower():
                results.append(memory)
                continue
            
            # 标签匹配
            if tags:
                if any(tag in memory.tags for tag in tags):
                    results.append(memory)
                    continue
            
            # 元数据匹配
            metadata_str = json.dumps(memory.metadata, ensure_ascii=False).lower()
            if query_lower in metadata_str:
                results.append(memory)
        
        return results
    
    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
        if memory_id in self.memories:
            del self.memories[memory_id]
            self._save_memories()
            logger.info(f"删除记忆: {memory_id}")
            return True
        return False
    
    def delete_user_memories(self, 
                           user_id: str,
                           memory_type: Optional[MemoryType] = None) -> int:
        """
        删除用户的记忆
        
        Args:
            user_id: 用户ID
            memory_type: 记忆类型过滤
            
        Returns:
            删除的记忆数量
        """
        to_delete = []
        
        for memory_id, memory in self.memories.items():
            if memory.user_id == user_id:
                if memory_type is None or memory.memory_type == memory_type:
                    to_delete.append(memory_id)
        
        for memory_id in to_delete:
            del self.memories[memory_id]
        
        if to_delete:
            self._save_memories()
        
        logger.info(f"删除用户 {user_id} 的 {len(to_delete)} 条记忆")
        return len(to_delete)
    
    def cleanup_expired_memories(self) -> int:
        """
        清理过期记忆
        
        Returns:
            清理的记忆数量
        """
        now = datetime.now()
        to_delete = []
        
        for memory_id, memory in self.memories.items():
            if memory.expires_at:
                expires_at = datetime.fromisoformat(memory.expires_at)
                if now > expires_at:
                    to_delete.append(memory_id)
        
        for memory_id in to_delete:
            del self.memories[memory_id]
        
        if to_delete:
            self._save_memories()
        
        logger.info(f"清理了 {len(to_delete)} 条过期记忆")
        return len(to_delete)
    
    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户统计信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            统计信息字典
        """
        if user_id not in self.users:
            return {}
        
        user = self.users[user_id]
        memories = self.get_user_memories(user_id, include_expired=True)
        
        # 按类型统计记忆
        memory_by_type = {}
        expired_count = 0
        total_importance = 0
        
        now = datetime.now()
        
        for memory in memories:
            memory_type = memory.memory_type.value
            memory_by_type[memory_type] = memory_by_type.get(memory_type, 0) + 1
            total_importance += memory.importance
            
            if memory.expires_at:
                expires_at = datetime.fromisoformat(memory.expires_at)
                if now > expires_at:
                    expired_count += 1
        
        return {
            "user_id": user_id,
            "username": user.username,
            "status": user.status.value,
            "created_at": user.created_at,
            "last_active": user.last_active,
            "total_memories": len(memories),
            "active_memories": len(memories) - expired_count,
            "expired_memories": expired_count,
            "memory_by_type": memory_by_type,
            "average_importance": total_importance / len(memories) if memories else 0,
            "preferences": user.preferences,
            "metadata": user.metadata
        }
    
    def batch_update_memories(self, 
                            user_id: str,
                            updates: Dict[str, Any],
                            memory_type: Optional[MemoryType] = None,
                            tags: Optional[List[str]] = None) -> int:
        """
        批量更新记忆
        
        Args:
            user_id: 用户ID
            updates: 要更新的字段
            memory_type: 记忆类型过滤
            tags: 标签过滤
            
        Returns:
            更新的记忆数量
        """
        updated_count = 0
        
        for memory in self.memories.values():
            if memory.user_id != user_id:
                continue
            
            if memory_type and memory.memory_type != memory_type:
                continue
            
            if tags and not any(tag in memory.tags for tag in tags):
                continue
            
            # 更新字段
            for key, value in updates.items():
                if hasattr(memory, key):
                    setattr(memory, key, value)
            
            updated_count += 1
        
        if updated_count > 0:
            self._save_memories()
        
        logger.info(f"批量更新用户 {user_id} 的 {updated_count} 条记忆")
        return updated_count
    
    def export_user_data(self, user_id: str) -> Dict[str, Any]:
        """
        导出用户数据
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户完整数据
        """
        if user_id not in self.users:
            return {}
        
        user = self.users[user_id]
        memories = self.get_user_memories(user_id, include_expired=True)
        
        # 转换用户档案，处理枚举类型
        user_profile = asdict(user)
        user_profile['status'] = user.status.value
        
        # 转换记忆数据，处理枚举类型
        memories_data = []
        for memory in memories:
            memory_dict = asdict(memory)
            memory_dict['memory_type'] = memory.memory_type.value
            memories_data.append(memory_dict)
        
        return {
            "user_profile": user_profile,
            "memories": memories_data,
            "stats": self.get_user_stats(user_id),
            "export_time": datetime.now().isoformat()
        }
    
    def get_all_users(self, 
                     status: Optional[UserStatus] = None,
                     limit: Optional[int] = None) -> List[UserProfile]:
        """
        获取所有用户
        
        Args:
            status: 状态过滤
            limit: 限制数量
            
        Returns:
            用户列表
        """
        users = list(self.users.values())
        
        if status:
            users = [user for user in users if user.status == status]
        
        # 按最后活跃时间排序
        users.sort(key=lambda x: x.last_active, reverse=True)
        
        if limit:
            users = users[:limit]
        
        return users
    
    def get_user_count(self) -> int:
        """获取用户总数"""
        return len(self.users) 
