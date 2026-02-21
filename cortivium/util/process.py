"""Async subprocess wrapper."""

from __future__ import annotations

import asyncio
import shlex
import signal
from typing import Callable


async def exec_cmd(
    command: str,
    cwd: str | None = None,
    env: dict | None = None,
    timeout: float | None = None,
) -> dict:
    """Execute a shell command asynchronously. Returns {stdout, stderr, exit_code, timed_out}."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        timed_out = True
        try:
            proc.send_signal(signal.SIGTERM)
            await asyncio.sleep(1)
            if proc.returncode is None:
                proc.kill()
        except ProcessLookupError:
            pass
        stdout_bytes = b""
        stderr_bytes = b""

    return {
        "stdout": stdout_bytes.decode(errors="replace") if stdout_bytes else "",
        "stderr": stderr_bytes.decode(errors="replace") if stderr_bytes else "",
        "exit_code": proc.returncode if proc.returncode is not None else -1,
        "timed_out": timed_out,
    }


async def exec_or_fail(
    command: str,
    cwd: str | None = None,
    env: dict | None = None,
    timeout: float | None = None,
) -> str:
    """Execute and return stdout, raise on non-zero exit."""
    result = await exec_cmd(command, cwd, env, timeout)
    if result["exit_code"] != 0:
        raise RuntimeError(
            f"Command failed: {command}\n"
            f"Exit code: {result['exit_code']}\n"
            f"Stderr: {result['stderr']}"
        )
    return result["stdout"]


async def stream_cmd(
    command: str,
    on_stdout: Callable[[str], None] | None = None,
    on_stderr: Callable[[str], None] | None = None,
    cwd: str | None = None,
    env: dict | None = None,
) -> int:
    """Run command with streaming output callbacks. Returns exit code."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )

    async def read_stream(stream, callback):
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            if callback:
                callback(chunk.decode(errors="replace"))

    await asyncio.gather(
        read_stream(proc.stdout, on_stdout),
        read_stream(proc.stderr, on_stderr),
    )
    await proc.wait()
    return proc.returncode or 0


def quote(value: str) -> str:
    """Shell-safe quoting."""
    return shlex.quote(value)
