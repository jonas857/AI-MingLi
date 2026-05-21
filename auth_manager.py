import hashlib
import hashlib
import hmac
import json
import os
import secrets
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional


PIN_ITERATIONS = 200_000


class AuthManager:
    def __init__(self, data_dir: str = "user_data"):
        self.data_dir = data_dir
        self.accounts_file = os.path.join(data_dir, "auth_accounts.json")
        os.makedirs(data_dir, exist_ok=True)
        self.accounts: Dict[str, Dict[str, Any]] = self._load_accounts()

    def _load_accounts(self) -> Dict[str, Dict[str, Any]]:
        if not os.path.exists(self.accounts_file):
            return {}
        try:
            with open(self.accounts_file, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            accounts = data.get("accounts", data)
            if isinstance(accounts, dict):
                return accounts
        except Exception:
            return {}
        return {}

    def reload_accounts(self) -> None:
        self.accounts = self._load_accounts()

    def _save_accounts(self) -> None:
        payload = {"accounts": self.accounts, "updated_at": datetime.now().isoformat()}
        with open(self.accounts_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @staticmethod
    def normalize_login_id(login_id: str) -> str:
        return (login_id or "").strip().lower()

    @staticmethod
    def hash_pin(pin: str, salt_hex: Optional[str] = None, iterations: int = PIN_ITERATIONS) -> Dict[str, Any]:
        if not pin or not str(pin).strip():
            raise ValueError("PIN cannot be empty")
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), salt, iterations)
        return {
            "pin_salt": salt.hex(),
            "pin_hash": digest.hex(),
            "pin_iterations": iterations,
        }

    @staticmethod
    def verify_pin(pin: str, salt_hex: str, pin_hash: str, iterations: int = PIN_ITERATIONS) -> bool:
        if not pin or not salt_hex or not pin_hash:
            return False
        try:
            digest = AuthManager.hash_pin(pin, salt_hex=salt_hex, iterations=int(iterations or PIN_ITERATIONS))
            return hmac.compare_digest(digest["pin_hash"], str(pin_hash))
        except Exception:
            return False

    def _find_by_login_key(self, login_key: str) -> Optional[Dict[str, Any]]:
        for account in self.accounts.values():
            if account.get("login_key") == login_key:
                return account
        return None

    def create_account(
        self,
        login_id: str,
        pin: str,
        display_name: Optional[str] = None,
        role: str = "user",
        linked_user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        login_id = (login_id or "").strip()
        login_key = self.normalize_login_id(login_id)
        if not login_key:
            raise ValueError("login_id is required")
        if self._find_by_login_key(login_key):
            raise ValueError("login_id already exists")

        now = datetime.now().isoformat()
        account_id = f"acct_{uuid.uuid4().hex[:16]}"
        pin_payload = self.hash_pin(pin)
        account = {
            "account_id": account_id,
            "login_id": login_id,
            "login_key": login_key,
            "display_name": (display_name or login_id).strip(),
            "role": role or "user",
            "linked_user_id": linked_user_id,
            "pin_salt": pin_payload["pin_salt"],
            "pin_hash": pin_payload["pin_hash"],
            "pin_iterations": pin_payload["pin_iterations"],
            "created_at": now,
            "updated_at": now,
            "last_login_at": None,
            "metadata": metadata or {},
        }
        self.accounts[account_id] = account
        self._save_accounts()
        return deepcopy(account)

    def authenticate(self, login_id: str, pin: str) -> Optional[Dict[str, Any]]:
        account = self._find_by_login_key(self.normalize_login_id(login_id))
        if not account:
            return None
        if not self.verify_pin(pin, account.get("pin_salt"), account.get("pin_hash"), account.get("pin_iterations")):
            return None
        account["last_login_at"] = datetime.now().isoformat()
        account["updated_at"] = account["last_login_at"]
        self._save_accounts()
        return deepcopy(account)

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        account = self.accounts.get(account_id)
        return deepcopy(account) if account else None

    def get_account_by_login_id(self, login_id: str) -> Optional[Dict[str, Any]]:
        account = self._find_by_login_key(self.normalize_login_id(login_id))
        return deepcopy(account) if account else None

    def list_accounts(self) -> List[Dict[str, Any]]:
        return [deepcopy(account) for account in self.accounts.values()]

    def find_account_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        accounts = self.find_accounts_by_user_id(user_id)
        return accounts[0] if accounts else None

    def find_accounts_by_user_id(self, user_id: str) -> List[Dict[str, Any]]:
        matches = [deepcopy(account) for account in self.accounts.values() if account.get("linked_user_id") == user_id]

        def sort_key(account: Dict[str, Any]) -> str:
            return str(account.get("last_login_at") or account.get("updated_at") or account.get("created_at") or "")

        matches.sort(key=sort_key, reverse=True)
        return matches

    def bind_user(self, account_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        account = self.accounts.get(account_id)
        if not account:
            return None
        account["linked_user_id"] = user_id
        metadata = account.get("metadata") if isinstance(account.get("metadata"), dict) else {}
        metadata["conflict_candidates"] = []
        metadata["bound_at"] = datetime.now().isoformat()
        account["metadata"] = metadata
        account["updated_at"] = datetime.now().isoformat()
        self._save_accounts()
        return deepcopy(account)

    def set_conflict_candidates(self, account_id: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        account = self.accounts.get(account_id)
        if not account:
            return None
        metadata = account.get("metadata") if isinstance(account.get("metadata"), dict) else {}
        metadata["conflict_candidates"] = candidates
        metadata["conflict_updated_at"] = datetime.now().isoformat()
        account["metadata"] = metadata
        account["updated_at"] = metadata["conflict_updated_at"]
        self._save_accounts()
        return deepcopy(account)

    def public_account(self, account: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "account_id": account.get("account_id"),
            "login_id": account.get("login_id"),
            "display_name": account.get("display_name"),
            "role": account.get("role"),
            "linked_user_id": account.get("linked_user_id"),
            "created_at": account.get("created_at"),
            "last_login_at": account.get("last_login_at"),
            "metadata": account.get("metadata") if isinstance(account.get("metadata"), dict) else {},
        }
