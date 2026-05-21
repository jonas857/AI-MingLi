import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from memory_manager import BaziMemoryManager


def main():
    user_id = os.getenv("TEST_USER_ID") or "user_f139a41f97ffa566"
    dimension = os.getenv("TEST_DIM") or "事业运势分析"
    query = os.getenv("TEST_QUERY") or "事业 方向 建议"
    mm = BaziMemoryManager()
    ctx = mm.build_shared_memory_context(user_id=user_id, dimension=dimension, query=query, limit=6)
    print("len", len(ctx))
    print(ctx)


if __name__ == "__main__":
    main()

