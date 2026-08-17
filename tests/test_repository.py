from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from req2code.project_memory import project_identity
from req2code.repository import RepositoryError, RepositorySpec, RepositoryWorkspace, StaleRunError


def git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def create_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    remote.mkdir()
    seed.mkdir()
    git(remote, "init", "--bare")
    git(seed, "init")
    git(seed, "config", "user.name", "Test")
    git(seed, "config", "user.email", "test@example.com")
    (seed / "README.md").write_text("initial\n", encoding="utf-8")
    git(seed, "add", "README.md")
    git(seed, "commit", "-m", "initial")
    git(seed, "branch", "-M", "main")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    return remote


def test_prepare_remote_snapshot_commit_and_push(tmp_path):
    remote = create_remote(tmp_path)
    workspace = RepositoryWorkspace(tmp_path / "state")
    prepared = workspace.prepare(
        RepositorySpec(
            repo_url=str(remote),
            base_branch="main",
            work_branch="feature/tapd-1",
            push_branch="feature/tapd-1",
        ),
        run_id="run1",
    )
    assert prepared.baseline_sha
    assert prepared.remote_branch_sha is None
    assert git(prepared.path, "branch", "--show-current") == "feature/tapd-1"
    assert git(prepared.path, "remote", "get-url", "--push", "origin") == workspace.disabled_push_url("run1")
    workspace.assert_baseline(
        prepared.path,
        prepared.baseline_sha,
        prepared.work_branch,
        prepared.remote_name,
        prepared.repo_url,
        "run1",
    )
    blocked_push = subprocess.run(["git", "push", "origin"], cwd=prepared.path, capture_output=True, check=False)
    assert blocked_push.returncode != 0

    (prepared.path / "feature.txt").write_text("implemented\n", encoding="utf-8")
    fingerprint, changed = workspace.snapshot(prepared.path)
    assert "feature.txt" in changed
    workspace.assert_unchanged(prepared.path, fingerprint)
    workspace.assert_remote_unchanged(prepared.path, "origin", "feature/tapd-1", None)

    commit = workspace.commit(prepared.path, "Implement TAPD-1", "Bot", "bot@example.com")
    workspace.push(prepared.path, "origin", "feature/tapd-1", prepared.push_url)
    assert git(prepared.path, "rev-parse", "origin/feature/tapd-1") == commit


def test_remote_runs_reuse_one_locked_project_mirror(tmp_path):
    remote = create_remote(tmp_path)
    state = tmp_path / "state"
    workspace = RepositoryWorkspace(state, use_mirror_cache=True)
    first = workspace.prepare(
        RepositorySpec(repo_url=str(remote), base_branch="main", work_branch="feature/one", push_branch="feature/one"),
        run_id="mirror-run-1",
    )
    workspace.restore_push_url(first.path, first.remote_name, first.push_url)
    second = workspace.prepare(
        RepositorySpec(repo_url=str(remote), base_branch="main", work_branch="feature/two", push_branch="feature/two"),
        run_id="mirror-run-2",
    )

    project_id, _ = project_identity(str(remote))
    mirror = state / "projects" / project_id / "mirror.git"
    assert (mirror / "HEAD").is_file()
    assert not (mirror.parent / ".mirror.lock").exists()
    assert first.path != second.path
    assert first.baseline_sha == second.baseline_sha

def test_snapshot_change_invalidates_approval(tmp_path):
    remote = create_remote(tmp_path)
    workspace = RepositoryWorkspace(tmp_path / "state")
    prepared = workspace.prepare(
        RepositorySpec(
            repo_url=str(remote),
            base_branch="main",
            work_branch="feature/tapd-2",
            push_branch="feature/tapd-2",
        ),
        run_id="run2",
    )
    target = prepared.path / "change.txt"
    target.write_text("one\n", encoding="utf-8")
    fingerprint, _ = workspace.snapshot(prepared.path)
    target.write_text("two\n", encoding="utf-8")
    with pytest.raises(StaleRunError):
        workspace.assert_unchanged(prepared.path, fingerprint)


def test_agent_commit_invalidates_baseline(tmp_path):
    remote = create_remote(tmp_path)
    workspace = RepositoryWorkspace(tmp_path / "state")
    prepared = workspace.prepare(
        RepositorySpec(
            repo_url=str(remote),
            base_branch="main",
            work_branch="feature/tapd-3",
            push_branch="feature/tapd-3",
        ),
        run_id="run3",
    )
    (prepared.path / "committed.txt").write_text("unexpected\n", encoding="utf-8")
    workspace.commit(prepared.path, "agent commit", "Agent", "agent@example.com")

    with pytest.raises(StaleRunError, match="must not commit"):
        workspace.assert_baseline(
            prepared.path,
            prepared.baseline_sha,
            prepared.work_branch,
            prepared.remote_name,
            prepared.repo_url,
            "run3",
        )


def test_local_prepare_without_branch_keeps_current_branch(tmp_path):
    remote = create_remote(tmp_path)
    local = tmp_path / "local"
    result = subprocess.run(["git", "clone", str(remote), str(local)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    git(local, "switch", "main")

    workspace = RepositoryWorkspace(tmp_path / "state")
    prepared = workspace.prepare(
        RepositorySpec(local_path=str(local)),
        run_id="current-branch",
    )

    assert prepared.branch_mode == "current"
    assert prepared.base_branch == "main"
    assert prepared.work_branch == "main"
    assert prepared.push_branch == "main"
    assert git(local, "branch", "--show-current") == "main"


def test_local_prepare_only_pulls_when_explicitly_requested(tmp_path, monkeypatch):
    remote = create_remote(tmp_path)
    local = tmp_path / "local-sync"
    result = subprocess.run(["git", "clone", str(remote), str(local)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    git(local, "switch", "main")

    workspace = RepositoryWorkspace(tmp_path / "state")
    calls: list[tuple[str, ...]] = []
    original = workspace._git

    def tracked(repo_path, *args, **kwargs):
        calls.append(tuple(args))
        return original(repo_path, *args, **kwargs)

    monkeypatch.setattr(workspace, "_git", tracked)
    prepared = workspace.prepare(RepositorySpec(local_path=str(local)), run_id="no-sync")
    assert not any(args and args[0] in {"fetch", "pull"} for args in calls)
    workspace.restore_push_url(prepared.path, prepared.remote_name, prepared.push_url)

    calls.clear()
    workspace.prepare(RepositorySpec(local_path=str(local), sync_before_start=True), run_id="with-sync")
    assert any(args[:2] == ("fetch", "--prune") for args in calls)
    assert any(args[:2] == ("pull", "--ff-only") for args in calls)


def test_git_timeout_has_actionable_error(tmp_path, monkeypatch):
    workspace = RepositoryWorkspace(tmp_path / "state", command_timeout_seconds=7)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=7)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RepositoryError, match="timed out after 7s"):
        workspace._git(tmp_path, "fetch", "origin")


def test_current_branch_reads_local_head_without_spawning_git_branch(tmp_path, monkeypatch):
    remote = create_remote(tmp_path)
    local = tmp_path / "local-head"
    result = subprocess.run(["git", "clone", str(remote), str(local)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    git(local, "switch", "main")
    workspace = RepositoryWorkspace(tmp_path / "state")
    original_git = workspace._git

    def reject_branch_process(repo_path, *args, **kwargs):
        if args[:2] == ("branch", "--show-current"):
            raise AssertionError("current branch should come from .git/HEAD")
        return original_git(repo_path, *args, **kwargs)

    monkeypatch.setattr(workspace, "_git", reject_branch_process)
    assert workspace.current_branch(local) == "main"
    prepared = workspace.prepare(RepositorySpec(local_path=str(local)), run_id="local-head")
    assert prepared.work_branch == "main"
    workspace.restore_push_url(prepared.path, prepared.remote_name, prepared.push_url)
