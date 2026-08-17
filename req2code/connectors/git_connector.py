from __future__ import annotations

import subprocess
from pathlib import Path

from req2code.logging_setup import get_logger

logger = get_logger()


class GitConnector:
    def __init__(self, repo_path: Path | None = None) -> None:
        self.repo_path = repo_path or Path.cwd()

    def is_git_repo(self) -> bool:
        return (self.repo_path / ".git").exists()

    def _run(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result.stdout.strip()

    def ensure_repo(self) -> None:
        if not self.is_git_repo():
            logger.info("Initializing git repo at %s", self.repo_path)
            self._run("init")

    def create_branch(self, branch_name: str) -> None:
        self.ensure_repo()
        logger.debug("Creating/checking out branch: %s", branch_name)
        exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            cwd=self.repo_path,
            check=False,
        ).returncode == 0
        self._run("switch", branch_name) if exists else self._run("switch", "-c", branch_name)

    def add_all_and_commit(self, message: str) -> str:
        self.ensure_repo()
        self._run("add", ".")
        try:
            self._run("commit", "-m", message)
            logger.info("Committed: %s", message[:80])
        except RuntimeError as err:
            if "nothing to commit" in str(err).lower():
                logger.info("Nothing to commit (working tree clean)")
            else:
                raise
        return self._run("rev-parse", "HEAD")

    def merge_to(self, source_branch: str, target_branch: str) -> None:
        self.ensure_repo()
        logger.info("Merging %s → %s", source_branch, target_branch)
        self._run("checkout", target_branch)
        self._run("merge", "--no-ff", source_branch, "-m",
                   f"Merge {source_branch} into {target_branch}")
