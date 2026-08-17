from pathlib import Path

import pytest

from req2code.skill_installer import install_skill


def test_packaged_skill_matches_repository_integration():
    root = Path(__file__).resolve().parents[1]
    packaged = root / "req2code" / "resources" / "skills" / "req2code-workflow"
    integration = root / "integrations" / "codex" / "skills" / "req2code-workflow"
    assert (packaged / "SKILL.md").read_bytes() == (integration / "SKILL.md").read_bytes()
    assert (packaged / "agents" / "openai.yaml").read_bytes() == (
        integration / "agents" / "openai.yaml"
    ).read_bytes()


def test_install_skill_copies_packaged_files_and_requires_force(tmp_path):
    target = install_skill("codex", destination=tmp_path)
    assert target == tmp_path.resolve() / "req2code-workflow"
    assert (target / "SKILL.md").is_file()
    assert (target / "agents" / "openai.yaml").is_file()

    assert install_skill("codex", destination=tmp_path) == target

    (target / "SKILL.md").write_text("locally changed", encoding="utf-8")
    with pytest.raises(FileExistsError):
        install_skill("codex", destination=tmp_path)

    assert install_skill("claude-code", destination=tmp_path, overwrite=True) == target
    assert install_skill("cursor", destination=tmp_path, overwrite=True) == target
