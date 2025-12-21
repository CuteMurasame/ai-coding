"""Interactive stress test tool for validating interactive solutions."""

from AICodeforcer.interactive.tools.interaction_runner import run_interaction
from AICodeforcer.standard.tools.executor import execute_code


def interactive_stress_test(
    solution_code: str,
    generator_code: str,
    judge_code: str,
    num_tests: int = 100,
) -> str:
    """Run interactive stress test.

    Args:
        solution_code: Python code for the solver
        generator_code: Python code for generating test data
        judge_code: Python code for the judge/interactor
        num_tests: Number of tests to run

    Returns:
        Result string: "INTERACTIVE STRESS TEST PASSED" or failure details with full log
    """
    for i in range(num_tests):
        # Generate test data
        gen_result = execute_code(
            code=generator_code,
            stdin="",
            timeout_seconds=5.0,
            memory_mb=256,
        )

        if gen_result.status != "passed":
            return f"""=== GENERATOR ERROR ===
Test #{i + 1}
Error:
{gen_result.error_message or 'Unknown error'}
Stdout:
{(gen_result.actual_output or '').strip()}
Status: {gen_result.status}"""

        test_input = gen_result.actual_output or ""

        # Run interaction
        result = run_interaction(
            judge_code=judge_code,
            solver_code=solution_code,
            test_input=test_input,
            timeout_total=30.0,
            timeout_per_turn=2.0,
        )

        if result.verdict != "AC":
            return f"""=== INTERACTIVE TEST FAILED ===
Test #{i + 1}
Verdict: {result.verdict}
Time: {result.time_ms:.1f}ms
{f"Exit Code: {result.exit_code}" if result.exit_code is not None else ""}
{f"Error: {result.error_message}" if result.error_message else ""}

Test Input:
{test_input}

Interaction Log:
{result.log}

请分析交互日志并修正你的代码。"""

    return f"""=== INTERACTIVE STRESS TEST PASSED ===
All {num_tests} tests passed!
Your interactive solution works correctly on all random inputs."""
