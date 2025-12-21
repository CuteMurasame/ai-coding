"""Judge validator - validates generator and judge code with fresh AI session."""

import os

from google import genai
from google.genai import types

VALIDATOR_SYSTEM_PROMPT = """你是一名**代码审查专家**，专门审查交互题的评测机和数据生成器。

你的任务是检查以下代码是否正确实现了题目要求的交互协议。

## 检查要点

### 数据生成器
1. 是否生成符合题目约束的数据？
2. 是否使用随机数生成不同的测试数据？
3. 输出格式是否正确？

### 评测机
1. 是否正确读取测试数据（从 sys.argv[1] 指定的文件）？
2. 是否正确实现交互协议？
3. 是否使用正确的退出码？
   - exit(0) = AC（通过）
   - exit(1) = WA（答案错误）
   - exit(2) = PE（协议错误）
4. 是否所有 print 语句都使用 flush=True？
5. 是否正确处理选手的各种回复？
6. 是否有逻辑错误或边界情况遗漏？

## 输出格式

如果代码没有问题，只输出：
VALID

如果有问题，输出问题描述，格式：
INVALID: <问题描述>

不要输出其他内容。
"""


class JudgeValidator:
    """Validates generator and judge code with a fresh AI session."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("API key required")

        self.base_url = base_url or os.environ.get("GEMINI_BASE_URL")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

        if self.base_url:
            self.client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(base_url=self.base_url),
            )
        else:
            self.client = genai.Client(api_key=self.api_key)

    def validate(
        self,
        problem_text: str,
        generator_code: str,
        judge_code: str,
    ) -> tuple[bool, str]:
        """Validate generator and judge code.

        Args:
            problem_text: The problem statement
            generator_code: Data generator code
            judge_code: Judge/interactor code

        Returns:
            (is_valid, issues_or_empty) tuple
        """
        config = types.GenerateContentConfig(
            system_instruction=VALIDATOR_SYSTEM_PROMPT,
            temperature=0.5,  # Lower temperature for more consistent validation
            thinking_config=types.ThinkingConfig(thinking_level="medium"),
        )

        prompt = f"""请审查以下交互题的数据生成器和评测机代码。

## 题目

{problem_text}

## 数据生成器代码

```python
{generator_code}
```

## 评测机代码

```python
{judge_code}
```

请检查代码是否正确实现了题目要求的交互协议。如果没有问题，输出 VALID；如果有问题，输出 INVALID: <问题描述>。
"""

        contents = [types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )]

        for retry in range(5):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as e:
                print(f"  验证请求失败 (重试 {retry + 1}/5): {e}")
                if retry == 4:
                    return False, f"验证请求失败: {e}"
                import time
                time.sleep(2)

        if not response or not response.candidates:
            return False, "验证无响应"

        candidate = response.candidates[0]
        if not candidate.content:
            return False, "验证无内容"

        response_text = ""
        for part in candidate.content.parts:
            if part.text:
                response_text += part.text

        response_text = response_text.strip()

        if "VALID" in response_text and "INVALID" not in response_text:
            return True, ""

        # Extract issues
        if "INVALID:" in response_text:
            issues = response_text.split("INVALID:", 1)[1].strip()
            return False, issues

        # If unclear, treat as invalid
        return False, response_text
