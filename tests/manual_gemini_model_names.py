import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_analyzer import AIAnalyzer


def main():
    a = AIAnalyzer()
    tests = [
        "gemini-3-pro-preview-thinking-high",
        "gemini-3-flash-preview-thinking-low",
        "gemini-3-flash-preview-thinking-minimal",
        "gemini-3-pro-preview",
    ]
    for t in tests:
        print(t, "=>", a._normalize_gemini_model_name_for_native(t))


if __name__ == "__main__":
    main()
