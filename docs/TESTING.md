# Testing Req2Code

[English](TESTING.md) | [简体中文](TESTING.zh-CN.md)

Test in three levels. Level 1 needs no external service or coding agent. Level 2 exercises the current-agent workflow against a disposable local Git remote. Level 3 uses staging TAPD and Git systems.

## Level 1: automated suite

### uv (recommended)

```powershell
uv sync --extra test
uv run python -m compileall -q req2code tests scripts
uv run python -m pytest -q
node tests/selector_ui_harness.js
node tests/launcher_ui_harness.js
node tests/feishu_analysis_ui_harness.js
uv run req2code --version
uv run req2code start --help
uv run req2code finalize --help
uv run req2code verify --help
uv run req2code install-skill --help
```

A uv-managed `.venv` may not contain `pip`; that is normal. Use `uv sync`, `uv run`, or `uv pip`.

### Already activated environment

```powershell
.\.venv\Scripts\Activate.ps1
python -m compileall -q req2code tests scripts
python -m pytest -q
req2code --version
```

The suite uses fake TAPD data and local bare Git repositories. It verifies current-branch preservation, current-agent task briefs, agent-evidence finalization without duplicate tests, opt-in strict reruns, blocked agent commits and pushes, stale-run detection, rejection, and human-approved publication.

The Node harnesses verify direct-selector compatibility, the UI-first configuration flow, and the opt-in Feishu schema-analysis round trip, including that credentials are absent from agent messages.

## Level 2: Mock current-agent workflow

This level has no TAPD dependency and pushes only to a disposable bare repository under `.demo/`.

### 1. Create isolated configuration

```powershell
$env:REQ2CODE_CONFIG = Join-Path $PWD ".demo-config.yaml"
req2code setup
```

Choose **Mock**. Keep the demo test commands:

- Unit: `python -m pytest -q`
- Coverage: `python -m coverage run -m pytest -q && python -m coverage report`
- Minimum coverage: `80`

The normal setup must not ask for a coding engine or model.

```powershell
req2code fetch --item-type all --limit 10
req2code doctor
```

Expected items: `DEMO-STORY-1` and `DEMO-BUG-1`.

### 2. Create a disposable repository

```powershell
python scripts/create_demo_repository.py --output .demo
```

The script refuses to overwrite an existing directory.

### 3. Open the target in a coding agent

Open `.demo/work` in Codex, Claude Code, or Cursor with the Req2Code MCP enabled. Invoke the Skill and select `DEMO-STORY-1`, or prepare through CLI:

```powershell
req2code start --item story:DEMO-STORY-1 --local .demo/work
```

Do not pass `--branch`. Expected preparation behavior:

- `main` remains checked out.
- no second coding-agent CLI starts;
- the run becomes `developing`;
- the task brief instructs the current agent to add `multiply(a, b)`, run tests, prepare the result, and call `finalize_development_run`;
- the remote push URL is temporarily disabled.

Let the current agent implement and test the work, fix failures, and produce the implementation/test summary. It should call `finalize_development_run` through MCP. CLI fallback:

```powershell
req2code finalize <run_id> `
  --plan "Add multiplication and regression coverage" `
  --summary "Implemented multiply and added tests" `
  --test-evidence "python -m pytest -q: all tests passed" `
  --tests-passed
```

Expected finalization result:

- status is `waiting_approval`;
- the report records the current agent's exact test evidence and states that Req2Code did not rerun configured tests;
- a Markdown report contains the work item, plan, summary, changed files, and test log;
- `git -C .demo/work log -1 --oneline` still shows `Initial demo`;
- no push occurred.

### 4. Review, reject, or approve

```powershell
req2code runs
req2code status <run_id>
git -C .demo/work diff
```

Safe rejection test:

```powershell
req2code reject <run_id> --comment "Demo rejection"
```

For approval testing, prepare and finalize a fresh run, then review and run:

```powershell
req2code approve <run_id>
req2code status <run_id>
git --git-dir=.demo/remote.git log --oneline --all --decorate
```

Expected: the run is `completed` and the reviewed commit exists in the local bare remote. No force push is used.

## Level 3: staging TAPD and Git

1. Point `REQ2CODE_CONFIG` to a staging-only configuration.
2. Open `req2code-workflow`, add a named TAPD project in the private UI, and choose Open application OAuth2 or API account Basic to match the credentials. On a host without MCP Apps, use `req2code setup` in a private terminal instead.
3. Confirm that the UI validates both stories and bugs, then optionally run `req2code doctor`, `req2code fetch`, and `req2code show` before allowing writes.
4. Open a non-production target repository in the coding agent.
5. Select one low-risk work item through the Skill/MCP.
6. First verify the no-branch case on a safe feature branch already checked out.
7. Verify an explicitly named new branch.
8. Verify a two-item batch on one branch.
9. Verify remote-clone mode with an explicit base/work branch.
10. Inspect every report and diff before approval; confirm the pushed SHA afterward.

Never use a production branch for the first integration test.

## Skill and MCP checks

```powershell
python C:\path\to\skill-creator\scripts\quick_validate.py integrations\codex\skills\req2code-workflow
req2code-mcp
```

The MCP process waits on stdio; stop it with `Ctrl+C`. In each host, confirm these model-callable workflow tools are available:

- `render_req2code_launcher`
- `submit_feishu_table_analysis` (only for an explicitly authorized Bitable analysis)
- `prepare_development_run`
- `finalize_development_run`
- `verify_development_run`
- `get_run`

Confirm the configuration, candidate-loading, selection-confirmation, approval, and publication tools are marked app-private and cannot be chosen by the coding model.

## Packaging check

```powershell
uv build
uv run python -c "import req2code.mcp_server; print('MCP import OK')"
```

Install the built wheel in a disposable environment and confirm both `req2code` and `req2code-mcp` are present.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `.venv` has no pip | Use `uv sync --extra test`; do not treat this as a broken uv environment. |
| Setup asks for an engine | Normal setup should not. Remove `--legacy-engines` and verify Req2Code is version 0.5+. |
| Repository is dirty before start | Reconcile existing changes; Req2Code refuses to hide them with stash/reset. |
| Preparation appears slow | Query `list_runs`; the `preparing` record exposes its stage and a bounded Git timeout will produce an error. Do not retry the same request repeatedly. |
| Local code is not current | Explicitly approve sync or use `req2code start --pull`; Req2Code never silently pulls. |
| Branch changed unexpectedly | Omit `--branch` only when you intend to keep the current local branch. |
| Coverage says `not reported` | Pass the current agent's coverage with `coverage` / `--coverage` when it is available. |
| Finalization returns `changes_requested` | Fix the reported implementation/test problem and call `finalize_development_run` again. |
| Run becomes `stale` | Branch, HEAD, remote, remote SHA, or reviewed diff changed; prepare a new run. |
| Approval page is unreachable | Start `req2code serve-approval` and verify `review.approval_base_url`. |
