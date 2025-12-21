"""Interactive problem solver agent."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

from google import genai
from google.genai import types

from AICodeforcer.interactive.tools import interactive_stress_test
from AICodeforcer.standard.agents.cpp_translator import CppTranslator

SYSTEM_PROMPT = """你是一名**顶级 ICPC / CCPC 竞赛算法助手**，专门解决**交互题**。
你的唯一目标是：**稳定、可复现地解出交互题，并输出可 AC 的最终代码**。

你可以调用工具来**实验、验证、对拍**你的想法与实现。
**核心理念：代码实验优先。**只要出现关键想法/假设/策略，**先写代码验证，再下结论**。

---

## 可用工具

1. `run_python_code(code, test_input)` - 执行代码并返回输出（用于小规模实验、模拟与验证非交互逻辑）
2. `interactive_stress_test(solution_code)` - 交互对拍验证（固定 100 次测试）
   - **注意**：评测机和数据生成器已由系统独立生成，你只需提供 `solution_code`

---

## 1️⃣ 核心原则（不可违反）

* **正确性 > 可验证性 > 复杂度可行性 > 工程实现**
* **实验驱动**：任何未经验证的推断都是"假设"，必须被：
  * 逻辑证明，或
  * Python 小规模实验支持
* **交互策略本质是实验驱动的算法**：必须像竞赛选手一样主动模拟与验证
* 如果你在脑中推导超过 1–2 个关键步骤，**立即写代码实验**
* 贪心 / 二分 / 编码策略：**没有实验验证 = 不可信**

---

## 2️⃣ 强制解题流程（必须体现）

### (1) 题意重述与交互协议抽象
* 用自己的话重述题目与交互协议；
* 明确查询格式、回复格式、结束条件；
* 明确查询次数限制与错误返回（如 `-1`）。

### (2) 候选策略与信息量分析
* 提出 1–3 个策略（如二分、分治、随机、编码等）；
* 估算查询次数上界；
* 标记需要验证的关键点（单调性、编码正确性、可辨识性）。

### (3) Python 实验与模拟验证（必须执行）
你**必须主动使用 `run_python_code`** 完成至少一项：
* 枚举小规模隐藏状态，验证策略能否定位答案；
* 构造本地简化评测机，模拟交互流程；
* 验证查询次数上界、编码解码逻辑；
* 找反例并修正策略。

> **要求**：有想法就写代码验证，禁止只在脑中"自洽"。

### (4) 最终策略确定
* 明确交互流程与查询序列；
* 明确如何根据回复更新状态；
* 给出查询次数上界与复杂度。

### (5) 正确性要点
* 解释为何策略能唯一确定答案；
* 解释终止条件与答案输出的正确性；
* 说明不会超过查询次数限制。

### (6) 交互实现细节（竞赛级）
* 所有输出必须 `flush=True`；
* 处理评测机返回 `-1`；
* 严格遵守输出格式；
* 计数并防止超限查询。

### (7) 交互对拍验证（提交前必须执行）
在输出最终代码前，**必须**调用 `interactive_stress_test(solution_code)`。
* 若失败，阅读交互日志，修正策略与实现，再次对拍。

### (8) 最终提交代码
* 输出完整、可直接提交的 **Python 代码**；
* 不包含调试输出；
* 使用 fast I/O。

---

## 3️⃣ 代码与工具调用规范（极其重要）

### 工具调用隔离性（必须牢记）
- **每次工具调用都是全新解释器环境**
  之前定义的函数/变量（如 `eval_f`、`solve`）在下次调用中**不存在**。
- **禁止跨调用依赖**：每次调用都必须重新定义所有需要的函数/变量/常量。
- 代码必须**完整、自包含、可独立运行**，显式导入标准库。
- **调用前自检**：确认所有使用的函数/变量都已定义，不会抛出 NameError/ImportError/AttributeError

### 代码必须完整自包含（硬性要求）
- **禁止**引用未在该代码块内定义或导入的任何符号（函数、类、变量、常量）
- **所有辅助函数**（如 `check`、`valid`、`ok`、`solve` 等）必须在同一代码块内完整实现
- **显式导入**：所需模块必须显式 `import`，仅使用 Python 标准库，禁止第三方库
- **执行入口**：代码底部必须调用主逻辑，确保有可观察的输出（print）

### 交互输出规范
- **所有 `print` 必须使用 `flush=True`**
- 查询格式通常为 `? ...`，答案格式通常为 `! ...`（以题面为准）
- 收到 `-1` 必须立即退出（`sys.exit()`）
- **输出格式是协议（极其重要）**：
  - 输出必须与题目要求**完全一致**，包括格式、分隔符、换行等
  - **严禁**输出调试信息、额外说明、或任何题目未要求的内容
  - 输出格式错误 = WA，即使算法逻辑正确也会被判错

### 交互代码模板
```python
import sys

def main():
    # 读取初始信息（如果有）
    n = int(input())

    # 交互循环
    while True:
        # 发送查询
        print(f"? {query}", flush=True)

        # 读取回复
        response = input()

        # 处理错误
        if response == "-1":
            sys.exit()

        # 判断是否结束
        if found_answer:
            print(f"! {answer}", flush=True)
            break

if __name__ == "__main__":
    main()
```

---

## 4️⃣ 完成标志

**严格要求**：你**必须**完成以下步骤才能输出 "ALL_TESTS_PASSED"：

1. **必须调用 `run_python_code`** 做至少一次小规模实验或模拟验证
2. **必须调用 `interactive_stress_test`** 进行对拍验证（固定 100 次）
3. **必须看到 "INTERACTIVE STRESS TEST PASSED" 返回**才算对拍通过
4. 只有当上述步骤都完成且通过后，才能输出 "ALL_TESTS_PASSED"

**禁止行为**：
- 禁止不调用工具就声称测试通过
- 禁止跳过对拍验证
- 禁止在没有看到 "INTERACTIVE STRESS TEST PASSED" 的情况下声称对拍通过
- 禁止在没有实际执行实验的情况下输出 "ALL_TESTS_PASSED"
"""

TOOL_DECLARATIONS = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="run_python_code",
            description="执行 Python 代码并返回结果。用于测试非交互逻辑。",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "code": types.Schema(
                        type=types.Type.STRING,
                        description="要执行的 Python 代码",
                    ),
                    "test_input": types.Schema(
                        type=types.Type.STRING,
                        description="提供给代码的测试输入",
                    ),
                },
                required=["code", "test_input"],
            ),
        ),
        types.FunctionDeclaration(
            name="interactive_stress_test",
            description="交互对拍验证工具：运行 100 次交互测试验证你的代码。你只需提供 solution_code，评测机和数据生成器已由系统生成。代码必须完整自包含，所有 print 必须使用 flush=True。",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "solution_code": types.Schema(
                        type=types.Type.STRING,
                        description="要验证的交互代码（完整自包含，所有 print 使用 flush=True）",
                    ),
                },
                required=["solution_code"],
            ),
        ),
    ])
]


class InteractiveSolver:
    """Gemini-powered interactive problem solver."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        log_dir: str | None = None,
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

        self._contents: list[types.Content] = []
        self._config: types.GenerateContentConfig | None = None
        self._last_verified_code: str | None = None
        self._last_code: str | None = None

        # Preprocessed judge and generator
        self._generator_code: str | None = None
        self._judge_code: str | None = None

        # Logging
        self._log_dir = Path(log_dir) if log_dir else Path("logs")
        self._log_file: TextIO | None = None
        self._log_path: Path | None = None

        # C++ translator
        self._cpp_translator = CppTranslator(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
        )
        self._cpp_code: str | None = None

    def _init_log(self, problem_text: str) -> None:
        """Initialize log file."""
        self._log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = self._log_dir / f"interactive_{timestamp}.log"
        self._log_file = open(self._log_path, "w", encoding="utf-8")
        self._log(f"{'='*80}")
        self._log("AICodeforcer 交互题求解日志")
        self._log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._log(f"模型: {self.model}")
        self._log(f"{'='*80}")
        self._log(f"\n{'='*80}")
        self._log("题目内容")
        self._log(f"{'='*80}")
        self._log(problem_text)
        self._log(f"{'='*80}\n")

    def _log(self, message: str) -> None:
        """Write to log."""
        if self._log_file:
            self._log_file.write(message + "\n")
            self._log_file.flush()

    def _log_tool_call(self, func_name: str, func_args: dict, result: str) -> None:
        """Log tool call details."""
        self._log(f"\n{'='*80}")
        self._log(f"工具调用: {func_name}")
        self._log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._log(f"{'='*80}")

        if func_name == "run_python_code":
            self._log("\n--- 代码 ---")
            self._log(func_args.get("code", ""))
            self._log("\n--- 输入 ---")
            self._log(func_args.get("test_input", ""))
        elif func_name == "interactive_stress_test":
            self._log("\n--- 交互代码 (solution_code) ---")
            self._log(func_args.get("solution_code", ""))

        self._log("\n--- 执行结果 ---")
        self._log(result)
        self._log(f"{'='*80}\n")

    def _log_response(self, turn: int, response_text: str) -> None:
        """Log model response."""
        self._log(f"\n{'='*80}")
        self._log(f"Turn {turn} - 模型响应")
        self._log(f"{'='*80}")
        self._log(response_text)
        self._log(f"{'='*80}\n")

    def _close_log(self) -> None:
        """Close log file."""
        if self._log_file:
            self._log(f"\n{'='*80}")
            self._log(f"日志结束: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self._log(f"{'='*80}")
            self._log_file.close()
            self._log_file = None
            print(f"\n[日志] 已保存到: {self._log_path}")

    def solve(
        self,
        problem_text: str,
        generator_code: str,
        judge_code: str,
        max_attempts: int = 50,
        on_attempt: Callable[[int, str], None] | None = None,
    ) -> tuple[str | None, str | None, bool]:
        """Solve an interactive problem.

        Args:
            problem_text: The problem statement
            generator_code: Data generator code
            judge_code: Judge/interactor code
            max_attempts: Maximum attempts
            on_attempt: Callback for each attempt

        Returns:
            (python_code, cpp_code, success) tuple
        """
        self._generator_code = generator_code
        self._judge_code = judge_code

        self._init_log(problem_text)
        self._log("\n--- 数据生成器代码 ---")
        self._log(generator_code)
        self._log("\n--- 评测机代码 ---")
        self._log(judge_code)

        try:
            return self._solve_impl(problem_text, max_attempts, on_attempt)
        finally:
            self._close_log()

    def _translate_to_cpp(self, python_code: str | None) -> str | None:
        """Translate Python code to C++."""
        if not python_code:
            return None

        cpp_code = self._cpp_translator.translate(python_code)
        if cpp_code:
            self._cpp_code = cpp_code
            self._log("\n--- C++ 翻译结果 ---")
            self._log(cpp_code)
        else:
            self._log("[翻译] C++ 翻译失败")

        return cpp_code

    def _solve_impl(
        self,
        problem_text: str,
        max_attempts: int,
        on_attempt: Callable[[int, str], None] | None,
    ) -> tuple[str | None, str | None, bool]:
        """Actual solving logic."""
        from AICodeforcer.standard.tools import run_python_code

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=TOOL_DECLARATIONS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=1.0,
            thinking_config=types.ThinkingConfig(thinking_level="high"),
        )

        contents: list[types.Content] = []

        initial_prompt = f"""请解决以下交互题：

{problem_text}

请仔细分析交互协议，设计查询策略，编写交互代码，并使用工具测试验证。
记住：必须调用 interactive_stress_test 进行对拍验证。
所有 print 语句必须使用 flush=True。"""

        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=initial_prompt)],
        ))

        last_code: str | None = None
        attempt_count = 0
        stress_test_passed = False
        verified_code: str | None = None

        tool_functions = {
            "run_python_code": run_python_code,
            "interactive_stress_test": self._run_stress_test,
        }

        for turn in range(max_attempts):
            response = None
            for retry in range(30):
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    break
                except Exception as e:
                    print(f"[Turn {turn + 1}] 请求失败 (重试 {retry + 1}/30): {e}")
                    self._log(f"[Turn {turn + 1}] 请求失败 (重试 {retry + 1}/30): {e}")
                    if retry == 29:
                        raise
                    import time
                    time.sleep(5)

            if not response:
                break

            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content:
                print(f"[Turn {turn + 1}] 无响应内容")
                self._log(f"[Turn {turn + 1}] 无响应内容")
                break

            response_content = candidate.content
            contents.append(response_content)

            response_text = ""
            function_calls = []

            for part in response_content.parts:
                if part.text:
                    response_text += part.text
                if part.function_call:
                    function_calls.append(part.function_call)

            print(f"\n{'='*60}")
            print(f"Turn {turn + 1}")
            print("=" * 60)
            if response_text:
                preview = response_text[:1500] if len(response_text) > 1500 else response_text
                print(preview)
                if len(response_text) > 1500:
                    print(f"... (truncated, total {len(response_text)} chars)")

            self._log_response(turn + 1, response_text)

            code = self._extract_code(response_text)
            if code:
                last_code = code
                self._last_code = code
                attempt_count += 1
                if on_attempt:
                    on_attempt(attempt_count, code)

            if "ALL_TESTS_PASSED" in response_text and not function_calls:
                if stress_test_passed and verified_code:
                    print("\n[程序化校验] 对拍已通过，返回验证过的代码")
                    self._log("[程序化校验] 对拍已通过，返回验证过的代码")
                    self._contents = contents
                    self._config = config
                    self._last_verified_code = verified_code
                    self._last_code = verified_code
                    cpp_code = self._translate_to_cpp(verified_code)
                    return verified_code, cpp_code, True
                else:
                    print("\n[程序化校验] 模型声称通过但未检测到对拍通过，要求重新验证")
                    self._log("[程序化校验] 模型声称通过但未检测到对拍通过，要求重新验证")
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text="你声称 ALL_TESTS_PASSED，但系统未检测到对拍通过。请调用 interactive_stress_test 工具进行对拍验证。"
                        )],
                    ))
                    continue

            if function_calls:
                print(f"\n[工具调用] 共 {len(function_calls)} 个")
                function_responses = []

                for fc in function_calls:
                    func_name = fc.name
                    func_args = dict(fc.args) if fc.args else {}

                    if func_name == "interactive_stress_test":
                        solution_code = func_args.get("solution_code", "")
                        func_args = {"solution_code": solution_code}
                    elif func_name == "run_python_code":
                        allowed_keys = {"code", "test_input"}
                        func_args = {k: v for k, v in func_args.items() if k in allowed_keys}

                    print(f"  - {func_name}({', '.join(f'{k}=...' for k in func_args.keys())})")

                    if func_name in tool_functions:
                        try:
                            result = tool_functions[func_name](**func_args)
                        except Exception as e:
                            result = f"Error: {e}"
                    else:
                        result = f"Unknown function: {func_name}"

                    self._log_tool_call(func_name, func_args, result)

                    if func_name == "interactive_stress_test" and "INTERACTIVE STRESS TEST PASSED" in result:
                        stress_test_passed = True
                        verified_code = func_args.get("solution_code")
                        print("    [程序化校验] 对拍通过！已记录验证代码")
                    elif func_name == "interactive_stress_test" and "INTERACTIVE TEST FAILED" in result:
                        stress_test_passed = False
                        verified_code = None
                        print("    [程序化校验] 对拍失败，重置验证状态")

                    result_preview = result[:500] if len(result) > 500 else result
                    print(f"    结果: {result_preview}")
                    if len(result) > 500:
                        print(f"    ... (truncated, total {len(result)} chars)")

                    function_responses.append(types.Part.from_function_response(
                        name=func_name,
                        response={"result": result},
                    ))

                contents.append(types.Content(
                    role="user",
                    parts=function_responses,
                ))

                if stress_test_passed and verified_code:
                    print("\n[程序化校验] 对拍已通过 100 次测试，直接返回验证过的代码")
                    self._log("[程序化校验] 对拍已通过 100 次测试，直接返回验证过的代码")
                    self._contents = contents
                    self._config = config
                    self._last_verified_code = verified_code
                    self._last_code = verified_code
                    cpp_code = self._translate_to_cpp(verified_code)
                    return verified_code, cpp_code, True
            else:
                if turn < max_attempts - 1:
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text="请继续。记住必须调用工具验证代码。如果所有测试都通过了，请输出 'ALL_TESTS_PASSED' 并给出最终代码。"
                        )],
                    ))

        self._contents = contents
        self._config = config
        self._last_code = last_code
        cpp_code = self._translate_to_cpp(last_code)
        return last_code, cpp_code, False

    def _run_stress_test(self, solution_code: str) -> str:
        """Run interactive stress test with injected generator and judge."""
        if not self._generator_code or not self._judge_code:
            return "Error: 评测机或数据生成器未生成"

        return interactive_stress_test(
            solution_code=solution_code,
            generator_code=self._generator_code,
            judge_code=self._judge_code,
            num_tests=100,
        )

    def continue_solving(
        self,
        feedback: str,
        max_attempts: int = 30,
        on_attempt: Callable[[int, str], None] | None = None,
    ) -> tuple[str | None, str | None, bool]:
        """Continue solving based on user feedback.

        Returns:
            (python_code, cpp_code, success) tuple
        """
        if not self._contents or not self._config:
            raise RuntimeError("没有可继续的对话，请先调用 solve()")

        from AICodeforcer.standard.tools import run_python_code

        # Reopen log file in append mode
        if self._log_path and not self._log_file:
            self._log_file = open(self._log_path, "a", encoding="utf-8")

        self._log(f"\n{'='*80}")
        self._log("继续优化 - 用户反馈")
        self._log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._log("=" * 80)
        self._log(f"反馈内容: {feedback}")
        self._log("=" * 80 + "\n")

        try:
            return self._continue_solving_impl(feedback, max_attempts, on_attempt, run_python_code)
        finally:
            self._close_log()

    def _continue_solving_impl(
        self,
        feedback: str,
        max_attempts: int,
        on_attempt: Callable[[int, str], None] | None,
        run_python_code,
    ) -> tuple[str | None, str | None, bool]:
        """Continue solving implementation."""
        contents = self._contents
        config = self._config

        feedback_prompt = f"""用户提交代码后收到以下反馈：

{feedback}

请根据这个反馈分析问题原因，优化你的交互代码，然后：
1. 使用 interactive_stress_test 进行对拍验证
2. 确保对拍通过后输出 "ALL_TESTS_PASSED" 和最终代码

注意：
- TLE: 可能是查询次数过多或策略效率低
- WA: 交互逻辑有误，检查查询和答案格式
- RE: 可能是没有正确处理评测机的回复"""

        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=feedback_prompt)],
        ))

        last_code: str | None = self._last_code or self._last_verified_code
        attempt_count = 0
        stress_test_passed = False
        verified_code: str | None = None

        tool_functions = {
            "run_python_code": run_python_code,
            "interactive_stress_test": self._run_stress_test,
        }

        for turn in range(max_attempts):
            response = None
            for retry in range(30):
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    break
                except Exception as e:
                    print(f"[Turn {turn + 1}] 请求失败 (重试 {retry + 1}/30): {e}")
                    self._log(f"[Turn {turn + 1}] 请求失败 (重试 {retry + 1}/30): {e}")
                    if retry == 29:
                        raise
                    import time
                    time.sleep(5)

            if not response:
                break

            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content:
                break

            response_content = candidate.content
            contents.append(response_content)

            response_text = ""
            function_calls = []

            for part in response_content.parts:
                if part.text:
                    response_text += part.text
                if part.function_call:
                    function_calls.append(part.function_call)

            print(f"\n{'='*60}")
            print(f"Turn {turn + 1}")
            print("=" * 60)
            if response_text:
                preview = response_text[:1500] if len(response_text) > 1500 else response_text
                print(preview)
                if len(response_text) > 1500:
                    print(f"... (truncated, total {len(response_text)} chars)")

            self._log_response(turn + 1, response_text)

            code = self._extract_code(response_text)
            if code:
                last_code = code
                self._last_code = code
                attempt_count += 1
                if on_attempt:
                    on_attempt(attempt_count, code)

            if "ALL_TESTS_PASSED" in response_text and not function_calls:
                if stress_test_passed and verified_code:
                    self._contents = contents
                    self._last_verified_code = verified_code
                    self._last_code = verified_code
                    cpp_code = self._translate_to_cpp(verified_code)
                    return verified_code, cpp_code, True
                else:
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text="你声称 ALL_TESTS_PASSED，但系统未检测到对拍通过。请调用 interactive_stress_test 工具进行对拍验证。"
                        )],
                    ))
                    continue

            if function_calls:
                print(f"\n[工具调用] 共 {len(function_calls)} 个")
                function_responses = []

                for fc in function_calls:
                    func_name = fc.name
                    func_args = dict(fc.args) if fc.args else {}

                    if func_name == "interactive_stress_test":
                        solution_code = func_args.get("solution_code", "")
                        func_args = {"solution_code": solution_code}
                    elif func_name == "run_python_code":
                        allowed_keys = {"code", "test_input"}
                        func_args = {k: v for k, v in func_args.items() if k in allowed_keys}

                    print(f"  - {func_name}({', '.join(f'{k}=...' for k in func_args.keys())})")

                    if func_name in tool_functions:
                        try:
                            result = tool_functions[func_name](**func_args)
                        except Exception as e:
                            result = f"Error: {e}"
                    else:
                        result = f"Unknown function: {func_name}"

                    self._log_tool_call(func_name, func_args, result)

                    if func_name == "interactive_stress_test" and "INTERACTIVE STRESS TEST PASSED" in result:
                        stress_test_passed = True
                        verified_code = func_args.get("solution_code")
                        print("    [程序化校验] 对拍通过！")
                    elif func_name == "interactive_stress_test" and "INTERACTIVE TEST FAILED" in result:
                        stress_test_passed = False
                        verified_code = None

                    result_preview = result[:500] if len(result) > 500 else result
                    print(f"    结果: {result_preview}")
                    if len(result) > 500:
                        print(f"    ... (truncated, total {len(result)} chars)")

                    function_responses.append(types.Part.from_function_response(
                        name=func_name,
                        response={"result": result},
                    ))

                contents.append(types.Content(
                    role="user",
                    parts=function_responses,
                ))

                if stress_test_passed and verified_code:
                    self._contents = contents
                    self._last_verified_code = verified_code
                    self._last_code = verified_code
                    cpp_code = self._translate_to_cpp(verified_code)
                    return verified_code, cpp_code, True
            else:
                if turn < max_attempts - 1:
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text="请继续。记住必须调用工具验证代码。"
                        )],
                    ))

        self._contents = contents
        self._last_code = last_code
        cpp_code = self._translate_to_cpp(last_code)
        return last_code, cpp_code, False

    def _extract_code(self, text: str) -> str | None:
        """Extract Python code from response text."""
        patterns = [
            r"```python\n(.*?)```",
            r"```py\n(.*?)```",
            r"```\n(.*?)```",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                return matches[-1].strip()

        return None
