from __future__ import annotations

import hashlib
import os
import time
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from req2code.project_memory import project_identity


class RepositoryError(RuntimeError):
    pass


class StaleRunError(RepositoryError):
    pass


@dataclass
class RepositorySpec:
    local_path: str = ""
    repo_url: str = ""
    remote_name: str = "origin"
    base_branch: str = ""
    work_branch: str = ""
    push_branch: str = ""
    allow_dirty: bool = False
    sync_before_start: bool = False


@dataclass
class PreparedRepository:
    path: Path
    repo_url: str
    push_url: str
    remote_name: str
    base_branch: str
    work_branch: str
    push_branch: str
    baseline_sha: str
    remote_branch_sha: str | None
    branch_mode: str = "selected"


class RepositoryWorkspace:
    def __init__(
        self,
        state_dir: str | Path = ".req2code",
        use_mirror_cache: bool = True,
        command_timeout_seconds: int = 120,
    ) -> None:
        self.state_dir = Path(state_dir).resolve()
        self.use_mirror_cache = use_mirror_cache
        self.command_timeout_seconds = max(5, int(command_timeout_seconds))

    def _git(self, repo_path: Path, *args: str, check: bool = True) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=repo_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=self.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            command = "git " + " ".join(args)
            raise RepositoryError(
                f"{command} timed out after {self.command_timeout_seconds}s; check network access and Git credentials"
            ) from exc
        if check and result.returncode != 0:
            raise RepositoryError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
        return result.stdout.rstrip("\r\n")

    def current_branch(self, repo_path: str | Path) -> str:
        """Read the checked-out branch from local Git metadata without spawning Git."""
        path = Path(repo_path).resolve()
        marker = path / ".git"
        git_dir = marker
        if marker.is_file():
            pointer = marker.read_text(encoding="utf-8", errors="replace").strip()
            prefix = "gitdir:"
            if not pointer.lower().startswith(prefix):
                raise RepositoryError(f"Invalid Git metadata pointer: {marker}")
            git_dir = Path(pointer[len(prefix):].strip())
            if not git_dir.is_absolute():
                git_dir = (path / git_dir).resolve()
        head_path = git_dir / "HEAD"
        if not head_path.is_file():
            raise RepositoryError(f"Git HEAD metadata is missing: {head_path}")
        head = head_path.read_text(encoding="utf-8", errors="replace").strip()
        prefix = "ref: refs/heads/"
        return head[len(prefix):] if head.startswith(prefix) else ""

    def _ref_exists(self, repo_path: Path, ref: str) -> bool:
        return subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", ref],
            cwd=repo_path,
            capture_output=True,
            check=False,
        ).returncode == 0

    def _validate_branch(self, repo_path: Path, branch: str) -> None:
        if not branch:
            raise RepositoryError("Branch name is required")
        result = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            cwd=repo_path,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RepositoryError(f"Invalid branch name: {branch}")

    def _remote_default_branch(self, repo_path: Path, remote: str) -> str:
        ref = self._git(
            repo_path,
            "symbolic-ref",
            "--quiet",
            "--short",
            f"refs/remotes/{remote}/HEAD",
            check=False,
        )
        prefix = f"{remote}/"
        if ref.startswith(prefix):
            return ref[len(prefix):]
        return ""

    def _run_git_process(self, args: list[str], cwd: Path) -> None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=self.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            command = "git " + " ".join(args)
            raise RepositoryError(
                f"{command} timed out after {self.command_timeout_seconds}s; check network access and Git credentials"
            ) from exc
        if result.returncode != 0:
            raise RepositoryError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")

    @contextmanager
    def _mirror_lock(self, project_root: Path):
        lock = project_root / ".mirror.lock"
        deadline = time.monotonic() + 120
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 3600:
                        lock.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise RepositoryError(f"Timed out waiting for project mirror lock: {lock}")
                time.sleep(0.2)
        try:
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                lock.unlink()
            except FileNotFoundError:
                pass

    def _mirror(self, repo_url: str) -> Path:
        project_id, _ = project_identity(repo_url)
        project_root = self.state_dir / "projects" / project_id
        project_root.mkdir(parents=True, exist_ok=True)
        mirror = project_root / "mirror.git"
        with self._mirror_lock(project_root):
            if mirror.exists():
                if not (mirror / "HEAD").is_file():
                    raise RepositoryError(f"Project mirror is invalid: {mirror}")
                self._run_git_process(["remote", "set-url", "origin", repo_url], mirror)
                self._run_git_process(["remote", "update", "--prune"], mirror)
            else:
                self._run_git_process(["clone", "--mirror", repo_url, str(mirror)], project_root)
        return mirror

    def _clone(self, repo_url: str, run_id: str) -> Path:
        if not repo_url:
            raise RepositoryError("Repository URL is required")
        root = self.state_dir / "workspaces" / run_id
        root.mkdir(parents=True, exist_ok=True)
        target = root / "repository"
        if target.exists():
            raise RepositoryError(f"Managed workspace already exists: {target}")
        if self.use_mirror_cache:
            mirror = self._mirror(repo_url)
            with self._mirror_lock(mirror.parent):
                self._run_git_process(["clone", "--no-checkout", str(mirror), str(target)], root)
            self._git(target, "remote", "set-url", "origin", repo_url)
        else:
            self._run_git_process(["clone", "--no-checkout", repo_url, str(target)], root)
        return target

    def disabled_push_url(self, run_id: str) -> str:
        return f"req2code-disabled://{run_id}"

    def prepare(self, spec: RepositorySpec, run_id: str) -> PreparedRepository:
        if bool(spec.local_path) == bool(spec.repo_url):
            raise RepositoryError("Choose exactly one repository source: local path or repository URL")
        repo_path = self._clone(spec.repo_url, run_id) if spec.repo_url else Path(spec.local_path).expanduser().resolve()
        if not repo_path.is_dir():
            raise RepositoryError(f"Repository directory does not exist: {repo_path}")
        self._git(repo_path, "rev-parse", "--is-inside-work-tree")
        dirty = self._git(repo_path, "status", "--porcelain")
        if dirty and not spec.allow_dirty:
            raise RepositoryError("Repository has uncommitted changes; use a clean directory or an isolated clone/worktree")

        remote = spec.remote_name or "origin"
        if remote not in self._git(repo_path, "remote").splitlines():
            raise RepositoryError(f"Git remote not found: {remote}")
        base = spec.base_branch.strip()
        requested_work = spec.work_branch.strip()
        branch_mode = "selected"
        should_pull_work = False

        if spec.sync_before_start and not spec.repo_url:
            # Network access is opt-in for a user-owned checkout. Refresh remote refs
            # before deciding whether the requested branch already exists.
            self._git(repo_path, "fetch", "--prune", remote)

        if requested_work:
            work = requested_work
            if not base:
                current = self.current_branch(repo_path)
                base = current or self._remote_default_branch(repo_path, remote)
            self._validate_branch(repo_path, base)
            self._validate_branch(repo_path, work)

            local_work = f"refs/heads/{work}"
            remote_work = f"refs/remotes/{remote}/{work}"
            remote_base = f"refs/remotes/{remote}/{base}"
            local_base = f"refs/heads/{base}"
            if self._ref_exists(repo_path, local_work):
                self._git(repo_path, "switch", work)
                should_pull_work = self._ref_exists(repo_path, remote_work)
            elif self._ref_exists(repo_path, remote_work):
                self._git(repo_path, "switch", "--track", "-c", work, f"{remote}/{work}")
                should_pull_work = True
            else:
                if self._ref_exists(repo_path, remote_base):
                    start_ref = f"{remote}/{base}"
                elif self._ref_exists(repo_path, local_base):
                    start_ref = base
                else:
                    raise RepositoryError(f"Base branch not found locally or on {remote}: {base}")
                self._git(repo_path, "switch", "-c", work, start_ref)
        else:
            current = self.current_branch(repo_path)
            has_head = bool(self._git(repo_path, "rev-parse", "--verify", "HEAD", check=False))
            if current and has_head:
                # Local-project default: preserve the branch already opened by the user.
                work = current
                base = base or current
                branch_mode = "current"
                should_pull_work = self._ref_exists(repo_path, f"refs/remotes/{remote}/{work}")
            else:
                # A managed remote clone has no checked-out branch yet. Use the requested
                # base, or the remote's default branch, without creating an extra branch.
                base = base or self._remote_default_branch(repo_path, remote)
                if not base:
                    raise RepositoryError("Cannot determine the remote default branch; pass --base or --branch")
                self._validate_branch(repo_path, base)
                local_base = f"refs/heads/{base}"
                remote_base = f"refs/remotes/{remote}/{base}"
                if self._ref_exists(repo_path, local_base):
                    self._git(repo_path, "switch", base)
                elif self._ref_exists(repo_path, remote_base):
                    self._git(repo_path, "switch", "--track", "-c", base, f"{remote}/{base}")
                else:
                    raise RepositoryError(f"Base branch not found locally or on {remote}: {base}")
                work = base
                branch_mode = "default"

        if spec.sync_before_start and not spec.repo_url and should_pull_work:
            # Updating a user-owned local repository is explicit and fast-forward only.
            # No merge commit or rebase is ever created by task preparation.
            self._git(repo_path, "pull", "--ff-only", remote, work)

        push = spec.push_branch.strip() or work
        self._validate_branch(repo_path, work)
        self._validate_branch(repo_path, push)

        baseline_sha = self._git(repo_path, "rev-parse", "HEAD")
        remote_push_ref = f"refs/remotes/{remote}/{push}"
        remote_sha = self._git(repo_path, "rev-parse", remote_push_ref) if self._ref_exists(repo_path, remote_push_ref) else None
        if remote_sha and baseline_sha != remote_sha:
            raise RepositoryError(
                "Local branch HEAD does not match the existing remote push branch; sync it before starting a reviewed run"
            )
        repo_url = self._git(repo_path, "remote", "get-url", remote)
        push_url = self._git(repo_path, "remote", "get-url", "--push", remote)
        self.protect_push_url(repo_path, remote, run_id)
        return PreparedRepository(
            path=repo_path,
            repo_url=repo_url,
            push_url=push_url,
            remote_name=remote,
            base_branch=base,
            work_branch=work,
            push_branch=push,
            baseline_sha=baseline_sha,
            remote_branch_sha=remote_sha,
            branch_mode=branch_mode,
        )

    def is_ancestor(self, repo_path: str | Path, ancestor_sha: str, descendant_sha: str) -> bool:
        if not ancestor_sha or not descendant_sha:
            return False
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
            cwd=Path(repo_path).resolve(),
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def changed_between(self, repo_path: str | Path, old_sha: str, new_sha: str) -> list[str]:
        path = Path(repo_path).resolve()
        if not self.is_ancestor(path, old_sha, new_sha):
            return []
        output = self._git(path, "-c", "core.quotepath=false", "diff", "--name-only", old_sha, new_sha)
        return sorted({line.strip() for line in output.splitlines() if line.strip()})

    def working_diff(self, repo_path: str | Path, max_chars: int = 24000) -> str:
        path = Path(repo_path).resolve()
        diff = self._git(path, "-c", "core.quotepath=false", "diff", "--no-ext-diff", "--unified=3", "HEAD")
        untracked = self._git(path, "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard")
        suffix = ""
        if untracked:
            suffix = "\n\nUntracked files (inspect them in the repository):\n" + untracked
        return (diff + suffix)[:max_chars]
    def snapshot(self, repo_path: str | Path) -> tuple[str, list[str]]:
        path = Path(repo_path).resolve()
        status = self._git(path, "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "--untracked-files=all")
        diff = self._git(path, "diff", "--binary", "HEAD")
        changed: list[str] = []
        entries = [entry for entry in status.split("\0") if entry]
        index = 0
        while index < len(entries):
            entry = entries[index]
            code = entry[:2]
            if len(entry) >= 4:
                changed.append(entry[3:])
            if "R" in code or "C" in code:
                index += 1
                if index < len(entries):
                    changed.append(entries[index])
            index += 1

        untracked = [
            name for name in self._git(path, "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard", "-z").split("\0") if name
        ]
        untracked_hashes: list[str] = []
        for name in untracked:
            file_path = path / name
            if file_path.is_file():
                untracked_hashes.append(f"{name}:{hashlib.sha256(file_path.read_bytes()).hexdigest()}")
        payload = "\n".join([status, diff, *sorted(untracked_hashes)]).encode("utf-8", errors="replace")
        return hashlib.sha256(payload).hexdigest(), sorted(set(changed + untracked))

    def assert_unchanged(self, repo_path: str | Path, expected_hash: str) -> None:
        current_hash, _ = self.snapshot(repo_path)
        if current_hash != expected_hash:
            raise StaleRunError("Workspace changed after the review report was generated")

    def assert_baseline(
        self,
        repo_path: str | Path,
        baseline_sha: str,
        work_branch: str,
        remote: str,
        repo_url: str,
        run_id: str,
    ) -> None:
        path = Path(repo_path).resolve()
        if self.current_branch(path) != work_branch:
            raise StaleRunError("Current branch changed during the run")
        if self._git(path, "rev-parse", "HEAD") != baseline_sha:
            raise StaleRunError("Git HEAD changed before human approval; agents must not commit")
        if self._git(path, "remote", "get-url", remote) != repo_url:
            raise StaleRunError("Repository remote URL changed during the run")
        if self._git(path, "remote", "get-url", "--push", remote) != self.disabled_push_url(run_id):
            raise StaleRunError("The protected push URL was modified during the run")

    def assert_remote_unchanged(
        self,
        repo_path: str | Path,
        remote: str,
        push_branch: str,
        expected_sha: str | None,
    ) -> None:
        path = Path(repo_path).resolve()
        self._git(path, "fetch", "--prune", remote)
        ref = f"refs/remotes/{remote}/{push_branch}"
        actual = self._git(path, "rev-parse", ref) if self._ref_exists(path, ref) else None
        if actual != expected_sha:
            raise StaleRunError(
                f"Remote branch changed after development started: expected={expected_sha or '(new)'}, actual={actual or '(missing)'}"
            )

    def restore_push_url(self, repo_path: str | Path, remote: str, push_url: str) -> None:
        self._git(Path(repo_path).resolve(), "remote", "set-url", "--push", remote, push_url)

    def protect_push_url(self, repo_path: str | Path, remote: str, run_id: str) -> None:
        self._git(
            Path(repo_path).resolve(),
            "remote",
            "set-url",
            "--push",
            remote,
            self.disabled_push_url(run_id),
        )

    def commit(self, repo_path: str | Path, message: str, author: str, email: str) -> str:
        path = Path(repo_path).resolve()
        self._git(path, "add", "-A")
        if not self._git(path, "diff", "--cached", "--name-only"):
            raise RepositoryError("No code changes to commit")
        self._git(path, "-c", f"user.name={author}", "-c", f"user.email={email}", "commit", "-m", message)
        return self._git(path, "rev-parse", "HEAD")

    def push(self, repo_path: str | Path, remote: str, push_branch: str, push_url: str) -> None:
        path = Path(repo_path).resolve()
        self.restore_push_url(path, remote, push_url)
        self._git(path, "push", remote, f"HEAD:refs/heads/{push_branch}")
