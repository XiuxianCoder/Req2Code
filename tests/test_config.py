from req2code.config import ConfigManager


def test_config_set_get_nested(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    mgr = ConfigManager(path=cfg_path)

    mgr.set("engines.active", "cursor")
    assert mgr.get("engines.active") == "cursor"


def test_sensitive_masking(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    mgr = ConfigManager(path=cfg_path)

    mgr.set("tapd.app_secret", "abcdef123456")
    masked = mgr.mask_value("tapd.app_secret", mgr.get("tapd.app_secret"))
    assert masked.startswith("abc")
    assert masked.endswith("456")
    assert "***" in masked


def test_source_profile_list_masking_never_prints_nested_credentials(tmp_path):
    mgr = ConfigManager(path=tmp_path / "config.yaml")
    profiles = [
        {
            "id": "tapd-one",
            "name": "研发",
            "tapd": {"app_id": "private-client", "app_secret": "private-secret"},
        }
    ]

    masked = mgr.mask_value("source_profiles", profiles)

    assert "private-client" not in masked
    assert "private-secret" not in masked
    assert "pri***ent" in masked
    assert "pri***ret" in masked

def test_v1_migrates_legacy_engine_commands_and_safe_git(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """schema_version: 1
engines:
  active: claude_code
  claude_code:
    command: 'claude-code --auth "{auth_token}" --prompt "{prompt}" --cwd "{target_dir}"'
  cursor:
    command: 'cursor-agent --auth "{auth_token}" --task "{prompt}" --workdir "{target_dir}"'
git:
  target_branch: develop
  auto_init_if_missing: true
tapd:
  detail_endpoint: /stories/{id}
  bug_detail_endpoint: /bugs/{id}
""",
        encoding="utf-8",
    )
    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.schema_version == 8
    assert cfg.git.command_timeout_seconds == 120
    assert cfg.review.approvals_file == "approvals.yaml"
    assert cfg.review.replay_store_file == "replay_nonces.yaml"
    assert cfg.git.base_branch == "develop"
    assert cfg.git.auto_init_if_missing is False
    assert cfg.engines.claude_code.command.startswith("claude -p")
    assert cfg.engines.codex.command.startswith("codex exec")
    assert cfg.tapd.detail_endpoint == "/stories"
    assert cfg.project_memory.enabled is True
    assert cfg.project_memory.max_context_chars == 14000
    assert cfg.project_memory.use_mirror_cache is True
    assert cfg.project_memory.resume_engine_sessions is True
    assert cfg.engines.claude_code.model == ""
    assert cfg.engines.codex.model == ""
    assert cfg.engines.cursor.model == ""


def test_v6_migrates_configured_tapd_to_named_source_profile(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """schema_version: 6
source: tapd
tapd:
  auth_mode: oauth2
  app_id: local-client
  app_secret: local-secret
  workspace_id: '12345678'
""",
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()

    assert cfg.schema_version == 8
    assert len(cfg.source_profiles) == 1
    assert cfg.source_profiles[0].name == "TAPD 12345678"
    assert cfg.source_profiles[0].tapd.app_secret == "local-secret"
    assert "source_profiles:" in cfg_path.read_text(encoding="utf-8")
