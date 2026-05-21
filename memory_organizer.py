import threading
import time
from typing import Optional, Set

from feature_flags import DEBUG_MODE


class MemoryOrganizer:
    def __init__(self, memory_manager, batch_size: int = 1, idle_sleep_s: float = 0.5):
        self.memory_manager = memory_manager
        self.batch_size = batch_size
        self.idle_sleep_s = idle_sleep_s
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._pending_users: Set[str] = set()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="memory-organizer", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout_s)

    def notify(self, user_id: str) -> None:
        if not user_id:
            return
        with self._lock:
            self._pending_users.add(user_id)
        self._wake.set()

    def process_once(self) -> int:
        users = []
        with self._lock:
            if self._pending_users:
                users = list(self._pending_users)
                self._pending_users.clear()
        processed_total = 0
        for uid in users:
            processed_total += self._process_user(uid)
        return processed_total

    def _process_user(self, user_id: str) -> int:
        processed_total = 0
        while not self._stop.is_set():
            res = self.memory_manager.process_pending_events(user_id=user_id, max_events=self.batch_size)
            processed = int(res.get("processed") or 0)
            pending = int(res.get("pending") or 0)
            processed_total += processed
            if processed <= 0 or pending <= 0:
                break
        return processed_total

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=self.idle_sleep_s)
            self._wake.clear()
            try:
                self.process_once()
            except Exception:
                if DEBUG_MODE:
                    raise
            time.sleep(self.idle_sleep_s)


def start_memory_organizer(memory_manager) -> MemoryOrganizer:
    org = MemoryOrganizer(memory_manager=memory_manager)
    org.start()
    return org

