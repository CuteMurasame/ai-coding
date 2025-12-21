"""Interactive problem preprocessor - generates data generator and judge."""

import os
import re

from google import genai
from google.genai import types

PREPROCESSOR_SYSTEM_PROMPT = """你是一名**顶级 ICPC / CCPC 竞赛出题人**。
你的任务是为交互题生成**数据生成器**和**评测机（Judge/Interactor）**。

---

## 交互题评测机规范

### 评测机结构
评测机需要：
1. 从命令行参数获取测试数据文件路径：`sys.argv[1]`
2. 读取测试数据
3. 与选手程序进行交互（通过 stdin/stdout）
4. 根据交互结果退出：
   - `exit(0)` = AC（通过）
   - `exit(1)` = WA（答案错误）
   - `exit(2)` = PE（协议错误）

### 评测机模板
```python
import sys

def main():
    # 读取测试数据
    with open(sys.argv[1], 'r') as f:
        # 解析测试数据
        ...

    # 交互循环
    while not finished:
        # 发送信息给选手
        print(message, flush=True)

        # 读取选手回复
        try:
            response = input()
        except EOFError:
            exit(2)  # 协议错误

        # 处理回复
        ...

    # 判定结果
    if correct:
        exit(0)  # AC
    else:
        exit(1)  # WA

if __name__ == "__main__":
    main()
```

### 数据生成器规范
数据生成器需要：
1. 生成随机测试数据
2. 输出到 stdout
3. 使用 `random` 模块，每次运行生成不同数据

---

## 输出格式

你必须输出两段完整的 Python 代码：

1. **数据生成器**：用 ```generator 和 ``` 包裹
2. **评测机**：用 ```judge 和 ``` 包裹

代码必须完整、自包含、可直接运行。
"""


class InteractivePreprocessor:
    """Generates data generator and judge for interactive problems."""

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

    def generate(
        self,
        problem_text: str,
        max_attempts: int = 10,
    ) -> tuple[str, str] | None:
        """Generate data generator and judge code.

        Args:
            problem_text: The problem statement
            max_attempts: Maximum attempts to generate valid code

        Returns:
            (generator_code, judge_code) tuple or None if failed
        """
        from AICodeforcer.interactive.agents.judge_validator import JudgeValidator

        validator = JudgeValidator(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
        )

        config = types.GenerateContentConfig(
            system_instruction=PREPROCESSOR_SYSTEM_PROMPT,
            temperature=1.0,
            thinking_config=types.ThinkingConfig(thinking_level="high"),
        )

        contents: list[types.Content] = []

        initial_prompt = f"""请为以下交互题生成数据生成器和评测机：

{problem_text}

请仔细分析题目的交互协议，然后生成：
1. 数据生成器（用 ```generator 包裹）
2. 评测机（用 ```judge 包裹）

确保：
- 数据生成器生成符合题目约束的随机数据
- 评测机正确实现交互协议
- 评测机使用正确的退出码（0=AC, 1=WA, 2=PE）
- 所有 print 语句都使用 flush=True
"""

        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=initial_prompt)],
        ))

        for attempt in range(max_attempts):
            print(f"\n[预处理] 生成评测机和数据生成器 (尝试 {attempt + 1}/{max_attempts})...")

            response = None
            for retry in range(10):
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    break
                except Exception as e:
                    print(f"  请求失败 (重试 {retry + 1}/10): {e}")
                    if retry == 9:
                        return None
                    import time
                    time.sleep(3)

            if not response or not response.candidates:
                continue

            candidate = response.candidates[0]
            if not candidate.content:
                continue

            response_text = ""
            for part in candidate.content.parts:
                if part.text:
                    response_text += part.text

            # Extract generator and judge code
            generator_code = self._extract_code(response_text, "generator")
            judge_code = self._extract_code(response_text, "judge")

            if not generator_code or not judge_code:
                print("  未能提取到完整代码，重试...")
                contents.append(candidate.content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(
                        text="请确保输出完整的代码，用 ```generator 和 ```judge 分别包裹数据生成器和评测机代码。"
                    )],
                ))
                continue

            print(f"  生成器: {len(generator_code)} 字符")
            print(f"  评测机: {len(judge_code)} 字符")

            # Validate with fresh AI session
            print("  验证评测机...")
            is_valid, issues = validator.validate(problem_text, generator_code, judge_code)

            if is_valid:
                print("  验证通过!")
                return generator_code, judge_code

            print(f"  验证发现问题: {issues[:200]}...")

            # Add feedback and retry
            contents.append(candidate.content)
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(
                    text=f"""验证器发现以下问题：

{issues}

请修正这些问题，重新生成数据生成器和评测机代码。"""
                )],
            ))

        print("[预处理] 生成失败，已达最大尝试次数")
        return None

    def _extract_code(self, text: str, code_type: str) -> str | None:
        """Extract code block of specific type."""

        def _strip_leading_markers(code: str, marker: str) -> str:
            """Remove redundant leading marker lines like 'generator'/'judge'."""
            lines = code.splitlines()
            result = []
            for line in lines:
                # Skip lines that are just the marker word (with optional whitespace)
                if line.strip().lower() == marker.lower():
                    continue
                result.append(line)
            return "\n".join(result).strip()

        # Try specific marker first
        # Pattern captures: ```generator (optional same-line content) \n (code body) ```
        # Group 1: same-line content after marker, Group 2: code body
        pattern = rf"```[ \t]*{re.escape(code_type)}[ \t]*([^\n]*)\r?\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        if matches:
            same_line, body = matches[-1]
            # Prepend same-line content if it looks like code (not empty/whitespace)
            if same_line.strip():
                body = same_line.strip() + "\n" + body
            candidate = _strip_leading_markers(body, code_type)
            if candidate:
                return candidate

        # Fallback to python blocks if only one type requested
        if code_type == "generator":
            # Look for generator-related code
            pattern = r"```python[ \t]*([^\n]*)\r?\n(.*?)```"
            matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
            for same_line, body in matches:
                if same_line.strip():
                    body = same_line.strip() + "\n" + body
                candidate = _strip_leading_markers(body, code_type)
                if "random" in candidate and "print" in candidate:
                    return candidate

        elif code_type == "judge":
            # Look for judge-related code
            pattern = r"```python[ \t]*([^\n]*)\r?\n(.*?)```"
            matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
            for same_line, body in matches:
                if same_line.strip():
                    body = same_line.strip() + "\n" + body
                candidate = _strip_leading_markers(body, code_type)
                if "sys.argv" in candidate or "exit(" in candidate:
                    return candidate

        return None
