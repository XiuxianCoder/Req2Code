from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Mapping, Sequence

from req2code.artifacts import ArtifactManager
from req2code.logging_setup import get_logger
from req2code.runners.base import RunnerResult

logger = get_logger()


class CliRunnerMixin:
    def _render_command(self, template: str, variables: Mapping[str, str]) -> str:
        command = template
        for key, value in variables.items():
            command = command.replace("{" + key + "}", shlex.quote(value or ""))
        return command

    def _split_command(self, command: str | Sequence[str]) -> list[str]:
        if not isinstance(command, str):
            return list(command)
        return shlex.split(command, posix=True)

    def _display_command(self, args: Sequence[str]) -> str:
        if os.name == "nt":
            return subprocess.list2cmdline(list(args))
        return shlex.join(list(args))

    def _run_once_streaming(
        self,
        command: str | Sequence[str],
        timeout_seconds: int,
        cwd: str | Path | None = None,
        input_text: str = "",
        env: Mapping[str, str] | None = None,
    ) -> RunnerResult:
        args = self._split_command(command)
        child_env = os.environ.copy()
        if env:
            child_env.update({key: value for key, value in env.items() if value})
        display_command = self._display_command(args)
        proc = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd else None,
            env=child_env,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        stdout_buf: list[str] = []
        stderr_buf: list[str] = []

        def _read(pipe, buf: list[str], label: str) -> None:
            if pipe is None:
                return
            for line in iter(pipe.readline, ""):
                buf.append(line)
                sys.stdout.write(f"{label}{line}")
                sys.stdout.flush()

        t_out = threading.Thread(target=_read, args=(proc.stdout, stdout_buf, ""), daemon=True)
        t_err = threading.Thread(target=_read, args=(proc.stderr, stderr_buf, "  "), daemon=True)
        t_out.start()
        t_err.start()

        if proc.stdin is not None:
            try:
                if input_text:
                    proc.stdin.write(input_text)
                    if not input_text.endswith("\n"):
                        proc.stdin.write("\n")
                proc.stdin.close()
            except BrokenPipeError:
                pass

        try:
            proc.wait(timeout=timeout_seconds)
            t_out.join(timeout=5)
            t_err.join(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            stderr_buf.append(f"\n[Timeout] command exceeded {timeout_seconds}s")
            logger.warning("Command timed out after %ds: %s", timeout_seconds, display_command[:120])
            return RunnerResult(False, "".join(stdout_buf), "".join(stderr_buf), display_command)

        ok = proc.returncode == 0
        if not ok:
            logger.warning("Command exited with code %d", proc.returncode)
        return RunnerResult(ok, "".join(stdout_buf), "".join(stderr_buf), display_command)

    def _run_with_retry(
        self,
        command: str | Sequence[str],
        timeout_seconds: int,
        retries: int,
        runner_name: str,
        phase: str,
        work_item_id: str,
        cwd: str | Path | None = None,
        input_text: str = "",
        env: Mapping[str, str] | None = None,
        artifact_base_dir: str | Path = ".req2code/artifacts",
    ) -> RunnerResult:
        args = self._split_command(command)
        display_command = self._display_command(args)
        last = RunnerResult(ok=False, stdout="", stderr="", command=display_command)
        attempts = max(1, retries)
        artifact = ArtifactManager(str(artifact_base_dir))

        for index in range(attempts):
            run_dir = artifact.create_run_dir(runner_name, f"{phase}_attempt_{index + 1}", work_item_id)
            logger.info("[%s] %s attempt %d/%d", runner_name, phase, index + 1, attempts)
            result = self._run_once_streaming(
                args,
                timeout_seconds=timeout_seconds,
                cwd=cwd,
                input_text=input_text,
                env=env,
            )
            artifact.write_text(run_dir, "command.txt", display_command)
            artifact.write_text(run_dir, "stdout.log", result.stdout)
            artifact.write_text(run_dir, "stderr.log", result.stderr)
            artifact.write_text(run_dir, "status.txt", "ok" if result.ok else "failed")

            if result.ok:
                logger.info("[%s] %s OK", runner_name, phase)
                result.stdout = f"{result.stdout}\n[Artifact] {run_dir}"
                return result

            last = result
            logger.warning("[%s] %s failed (attempt %d/%d)", runner_name, phase, index + 1, attempts)
            if index < attempts - 1:
                time.sleep(1)

        last.stdout = f"{last.stdout}\n[Artifact] failed attempts archived"
        return last
