from req2code.config import RunnerCommandConfig
from req2code.runners.claude_code_runner import ClaudeCodeRunner
from req2code.runners.codex_runner import CodexRunner
from req2code.runners.cursor_runner import CursorRunner


def test_codex_extracts_thread_and_builds_resume_command():
    runner = CodexRunner(RunnerCommandConfig(command="codex exec --json --sandbox workspace-write -"))
    output = '{"type":"thread.started","thread_id":"thread-123"}\n'
    runner.session_id = runner._extract_session_id(output)
    assert runner.session_id == "thread-123"
    assert runner._resume_command(runner.cfg.command) == [
        "codex", "exec", "--json", "--sandbox", "workspace-write", "resume", "thread-123", "-"
    ]


def test_claude_extracts_session_and_builds_resume_command():
    runner = ClaudeCodeRunner(RunnerCommandConfig(command="claude -p --output-format stream-json"))
    output = '{"type":"system","subtype":"init","session_id":"session-123"}\n'
    runner.session_id = runner._extract_session_id(output)
    assert runner.session_id == "session-123"
    assert runner._resume_command(runner.cfg.command) == [
        "claude", "-p", "--output-format", "stream-json", "--resume", "session-123"
    ]


def test_streaming_json_project_memory_is_reduced_to_markdown():
    runner = CodexRunner(RunnerCommandConfig(command="codex exec --json -"))
    markdown = "## OVERVIEW\\nSummary\\n## ARCHITECTURE\\nArchitecture"
    output = '{"type":"item.completed","item":{"type":"agent_message","text":"' + markdown + '"}}'
    extracted = runner._extract_memory_markdown(output)
    assert extracted.startswith("## OVERVIEW")
    assert "Summary" in extracted

def test_model_is_injected_for_supported_engine_commands():
    cases = [
        (CodexRunner, "codex exec --json -", ["codex", "exec", "--model", "test-model", "--json", "-"]),
        (ClaudeCodeRunner, "claude -p", ["claude", "--model", "test-model", "-p"]),
        (CursorRunner, "cursor-agent -p", ["cursor-agent", "--model", "test-model", "-p"]),
    ]
    for runner_type, command, expected in cases:
        cfg = RunnerCommandConfig(command=command, model="test-model")
        runner = runner_type(cfg)
        rendered = runner._render_command(cfg.command, {"model": runner.model})
        assert runner._command_with_model(rendered, cfg.command) == expected


def test_model_placeholder_supports_custom_wrapper():
    cfg = RunnerCommandConfig(command="company-wrapper --model {model}", model="team/model-v1")
    runner = CodexRunner(cfg)
    rendered = runner._render_command(cfg.command, {"model": runner.model})
    assert runner._command_with_model(rendered, cfg.command) == [
        "company-wrapper", "--model", "team/model-v1"
    ]


def test_custom_wrapper_requires_explicit_model_placeholder():
    import pytest

    cfg = RunnerCommandConfig(command="company-wrapper --run", model="team-model")
    runner = CodexRunner(cfg)
    with pytest.raises(ValueError, match=r"add \{model\}"):
        runner._command_with_model(cfg.command, cfg.command)