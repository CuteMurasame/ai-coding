"""C++ translator agent for converting Python to competitive programming style C++."""

import json
import os
import re
import time

from openai import OpenAI

CPP_TRANSLATOR_PROMPT = """# Role
你是一个资深的 C++ 算法竞赛（Competitive Programming）选手。你的任务是将输入的 Python 算法代码翻译成 C++ 代码。

# Target Style Guidelines
请严格遵守以下代码风格和模版约定：

1. **主函数模版：**
   `main` 函数开头必须包含 IO 加速：
   ```cpp
   ios_base::sync_with_stdio(false);
   cin.tie(0);
   cout.tie(0);
   ```

# Output Format
- 只输出 C++ 代码，不要任何解释或说明
- 代码用 ```cpp 包裹
- 必须输出完整代码，不准截断
"""


class CppTranslator:
    """将 Python 算法代码翻译成 C++ 竞赛风格代码。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("API key required.")

        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def translate(self, python_code: str) -> str | None:
        """将 Python 代码翻译成 C++ 竞赛风格代码。

        Args:
            python_code: Python 源代码

        Returns:
            C++ 代码，失败返回 None
        """
        print("\n" + "=" * 60)
        print("  翻译 Python -> C++")
        print("=" * 60)

        user_prompt = f"""```python
{python_code}
```"""

        messages = [
            {"role": "system", "content": CPP_TRANSLATOR_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        response = None
        for retry in range(30):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=1.0,
                )
                break
            except Exception as e:
                print(f"[翻译] 请求失败 (重试 {retry + 1}/30): {e}")
                if retry == 29:
                    print("[翻译] 翻译失败")
                    return None
                time.sleep(5)

        if not response:
            return None

        choice = response.choices[0] if response.choices else None
        if not choice or not choice.message:
            print("[翻译] 无响应内容")
            return None

        response_text = choice.message.content or ""
        if not response_text.strip():
            print("[翻译] 无有效输出")
            return None

        # 提取 C++ 代码
        cpp_code = self._extract_cpp_code(response_text)

        if not cpp_code:
            print("[翻译] 未能提取 C++ 代码")
            return None

        print(f"[翻译] 成功 ({len(cpp_code)} 字符)")
        return cpp_code

    def _extract_cpp_code(self, text: str) -> str | None:
        """从响应文本中提取 C++ 代码。

        Args:
            text: 响应文本

        Returns:
            提取的 C++ 代码，失败返回 None
        """
        # 尝试匹配 ```cpp 代码块
        patterns = [
            r"```cpp\s*\n(.*?)```",
            r"```c\+\+\s*\n(.*?)```",
            r"```\s*\n(.*?)```",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
            if matches:
                return matches[0].strip()

        # 如果没有代码块，尝试直接返回（可能整个响应就是代码）
        if "#include" in text:
            return text.strip()

        return None
