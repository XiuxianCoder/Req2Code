from __future__ import annotations

from importlib.resources import files
from pathlib import Path


SKILL_NAME = "req2code-workflow"
HOST_SKILL_ROOTS = {
    "codex": Path(".agents") / "skills",
    "claude": Path(".claude") / "skills",
    "cursor": Path(".cursor") / "skills",
}


def install_skill(
    host: str,
    destination: str | Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Install the packaged Req2Code Skill for Codex, Claude Code, or Cursor."""
    normalized = host.strip().lower().replace("_", "-")
    if normalized == "claude-code":
        normalized = "claude"
    if normalized not in HOST_SKILL_ROOTS:
        raise ValueError("host must be codex, claude, or cursor")

    root = Path(destination).expanduser() if destination else Path.home() / HOST_SKILL_ROOTS[normalized]
    target = root.resolve() / SKILL_NAME
    skill_file = target / "SKILL.md"
    metadata_file = target / "agents" / "openai.yaml"
    source = files("req2code").joinpath("resources", "skills", SKILL_NAME)
    source_skill = source.joinpath("SKILL.md").read_bytes()
    source_metadata = source.joinpath("agents", "openai.yaml").read_bytes()
    if skill_file.exists() and not overwrite:
        installed_metadata = metadata_file.read_bytes() if metadata_file.exists() else b""
        if skill_file.read_bytes() == source_skill and installed_metadata == source_metadata:
            return target
        raise FileExistsError(f"Skill is already installed with different content: {target}; pass --force to update it")

    target.mkdir(parents=True, exist_ok=True)
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_bytes(source_skill)
    metadata_file.write_bytes(source_metadata)
    return target
