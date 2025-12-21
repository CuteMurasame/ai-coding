"""Interactive problem runner with IPC between judge and solver."""

import os
import selectors
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Verdict = Literal["AC", "WA", "PE", "TLE", "RE"]


@dataclass
class InteractionResult:
    """Result of running an interactive session."""

    verdict: Verdict
    log: str
    time_ms: float
    exit_code: int | None = None
    error_message: str | None = None


def run_interaction(
    judge_code: str,
    solver_code: str,
    test_input: str,
    timeout_total: float = 30.0,
    timeout_per_turn: float = 5.0,
) -> InteractionResult:
    """Run an interactive session between judge and solver.

    The judge receives test_input via command line argument (temp file path).
    Communication is line-based: judge writes to stdout, solver reads from stdin,
    solver writes to stdout, judge reads from stdin.

    Judge exit codes:
        0 = AC (Accepted)
        1 = WA (Wrong Answer)
        2 = PE (Protocol Error)

    Args:
        judge_code: Python code for the judge/interactor
        solver_code: Python code for the solver
        test_input: Test data to pass to the judge
        timeout_total: Total timeout in seconds
        timeout_per_turn: Timeout per turn in seconds (increased to 5s for computation)

    Returns:
        InteractionResult with verdict, log, and timing info
    """
    log_lines: list[str] = []
    start_time = time.perf_counter()

    # Write codes to temp files
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(judge_code)
        judge_file = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(solver_code)
        solver_file = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(test_input)
        input_file = f.name

    judge_proc = None
    solver_proc = None
    sel = None

    try:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONUNBUFFERED": "1",
            "HOME": tempfile.gettempdir(),
        }

        # Start judge process: reads test data from file, interacts via stdin/stdout
        judge_proc = subprocess.Popen(
            [sys.executable, judge_file, input_file],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )

        # Start solver process: interacts via stdin/stdout
        solver_proc = subprocess.Popen(
            [sys.executable, solver_file],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )

        sel = selectors.DefaultSelector()
        sel.register(judge_proc.stdout, selectors.EVENT_READ, ("judge", "stdout"))
        sel.register(judge_proc.stderr, selectors.EVENT_READ, ("judge", "stderr"))
        sel.register(solver_proc.stdout, selectors.EVENT_READ, ("solver", "stdout"))
        sel.register(solver_proc.stderr, selectors.EVENT_READ, ("solver", "stderr"))

        judge_buffer = b""
        solver_buffer = b""
        last_activity = time.perf_counter()
        solver_exited = False
        solver_exit_time = None

        while True:
            elapsed = time.perf_counter() - start_time
            if elapsed > timeout_total:
                return InteractionResult(
                    verdict="TLE",
                    log="\n".join(log_lines),
                    time_ms=elapsed * 1000,
                    error_message=f"Total timeout exceeded ({timeout_total}s)",
                )

            idle_time = time.perf_counter() - last_activity
            if idle_time > timeout_per_turn:
                return InteractionResult(
                    verdict="TLE",
                    log="\n".join(log_lines),
                    time_ms=elapsed * 1000,
                    error_message=f"Turn timeout exceeded ({timeout_per_turn}s)",
                )

            # Check process states
            judge_poll = judge_proc.poll()
            solver_poll = solver_proc.poll()

            # Judge has exited - this is the authoritative verdict
            if judge_poll is not None:
                elapsed = time.perf_counter() - start_time
                verdict = _exit_code_to_verdict(judge_poll)
                return InteractionResult(
                    verdict=verdict,
                    log="\n".join(log_lines),
                    time_ms=elapsed * 1000,
                    exit_code=judge_poll,
                )

            # Solver exited but judge hasn't - give judge time to process final output
            if solver_poll is not None and not solver_exited:
                solver_exited = True
                solver_exit_time = time.perf_counter()
                log_lines.append(f"[INFO] Solver exited with code {solver_poll}, waiting for judge...")

            # If solver has been dead for too long and judge still hasn't responded
            if solver_exited and solver_exit_time:
                wait_time = time.perf_counter() - solver_exit_time
                if wait_time > 2.0:  # Give judge 2 seconds to finish after solver exits
                    elapsed = time.perf_counter() - start_time
                    return InteractionResult(
                        verdict="RE",
                        log="\n".join(log_lines),
                        time_ms=elapsed * 1000,
                        exit_code=solver_poll,
                        error_message=f"Solver exited (code {solver_poll}) but judge didn't respond",
                    )

            # Wait for I/O events
            timeout_remaining = min(
                timeout_total - elapsed,
                timeout_per_turn - idle_time,
                0.1,
            )
            events = sel.select(timeout=max(0.001, timeout_remaining))

            for key, _ in events:
                source, stream = key.data
                try:
                    data = key.fileobj.read(4096)
                except Exception:
                    data = b""

                if not data:
                    continue

                last_activity = time.perf_counter()

                if source == "judge" and stream == "stdout":
                    judge_buffer += data
                    while b"\n" in judge_buffer:
                        line, judge_buffer = judge_buffer.split(b"\n", 1)
                        line_str = line.decode(errors="replace")
                        log_lines.append(f"[JUDGE -> SOLVER] {line_str}")
                        # Forward to solver (if still alive)
                        if solver_proc.poll() is None:
                            try:
                                solver_proc.stdin.write(line + b"\n")
                                solver_proc.stdin.flush()
                            except (BrokenPipeError, OSError):
                                pass

                elif source == "solver" and stream == "stdout":
                    solver_buffer += data
                    while b"\n" in solver_buffer:
                        line, solver_buffer = solver_buffer.split(b"\n", 1)
                        line_str = line.decode(errors="replace")
                        log_lines.append(f"[SOLVER -> JUDGE] {line_str}")
                        # Forward to judge
                        try:
                            judge_proc.stdin.write(line + b"\n")
                            judge_proc.stdin.flush()
                        except (BrokenPipeError, OSError):
                            pass

                elif stream == "stderr":
                    stderr_str = data.decode(errors="replace").strip()
                    if stderr_str:
                        log_lines.append(f"[{source.upper()} STDERR] {stderr_str}")

        # Should not reach here
        elapsed = time.perf_counter() - start_time
        return InteractionResult(
            verdict="RE",
            log="\n".join(log_lines),
            time_ms=elapsed * 1000,
            error_message="Unexpected exit from interaction loop",
        )

    except Exception as e:
        elapsed = time.perf_counter() - start_time
        return InteractionResult(
            verdict="RE",
            log="\n".join(log_lines),
            time_ms=elapsed * 1000,
            error_message=str(e),
        )

    finally:
        # Always cleanup processes
        if judge_proc is not None or solver_proc is not None:
            _cleanup_processes(judge_proc, solver_proc)

        # Close selector
        if sel is not None:
            try:
                sel.close()
            except Exception:
                pass

        # Cleanup temp files
        for f in [judge_file, solver_file, input_file]:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass


def _exit_code_to_verdict(exit_code: int) -> Verdict:
    """Convert judge exit code to verdict."""
    if exit_code == 0:
        return "AC"
    elif exit_code == 1:
        return "WA"
    elif exit_code == 2:
        return "PE"
    else:
        return "RE"


def _cleanup_processes(
    judge_proc: subprocess.Popen | None,
    solver_proc: subprocess.Popen | None,
) -> None:
    """Terminate and cleanup processes."""
    for proc in [judge_proc, solver_proc]:
        if proc is None:
            continue
        try:
            if proc.poll() is None:  # Still running
                proc.terminate()
                proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=1)
            except Exception:
                pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
