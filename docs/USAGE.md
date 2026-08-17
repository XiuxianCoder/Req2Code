# Req2Code Usage Guide

[English](USAGE.md) | [简体中文](USAGE.zh-CN.md) | [Back to README](../README.md)

Req2Code is the workflow orchestrator between TAPD or Feishu and the coding agent already open in the target project. It fetches work items, lets the human select work, assembles an executable target task, protects the Git state, stores the implementation/test result, and creates the review package. Codex, Claude Code, or Cursor understands the project, changes code, runs tests, and fixes failures.

The default workflow does not launch a second coding-agent process and never commits or pushes before explicit human approval.

## Recommended integration

| Host | Recommended integration | Model selection |
| --- | --- | --- |
| Codex desktop | Req2Code Skill + MCP; inline UI verified | Codex model settings |
| Codex CLI | Req2Code Skill + MCP; terminal/text fallback | Codex model settings |
| Claude Code | Req2Code Skill + MCP; text/external UI fallback | Claude Code model settings |
| Cursor | Req2Code Skill + MCP; MCP Apps require Cursor 2.6+ | Cursor model settings |
| Terminal or no MCP | Req2Code CLI fallback | Current coding agent develops |

Normal Req2Code setup does not select a coding engine or model. Engine configuration is only required by the legacy nested-CLI compatibility mode.

## 1. Install

GitHub end-user installation:

```powershell
uv tool install "git+https://github.com/XiuxianCoder/Req2Code.git"
req2code --version
```

Contributor installation:

```powershell
git clone https://github.com/XiuxianCoder/Req2Code.git
cd Req2Code
uv sync --extra test

uv run req2code --version
uv run python -m pytest -q
```

If `.venv` is already activated, `req2code` can be called directly. A uv-managed environment may not contain pip; update it with `uv sync` or `uv pip`.

## 2. Configure the work-item source

The normal path needs no terminal setup. After host integration, start `req2code-workflow`; its private launcher first asks for TAPD, Feishu, or Mock and then lets you add or reuse a named profile for that platform. TAPD supports:

- Open application OAuth2: `app_id`, `app_secret`, and workspace;
- API account Basic: `api_user`, `api_password`, and workspace.

Feishu uses a self-built application with an App ID and App Secret. `/docx/` documents, `/wiki/` nodes, `/base/` Bitable links, and `/sheets/` spreadsheets are supported. A document can be parsed by native table rows, heading sections, or as one whole task; Bitable records and spreadsheet rows become work items. Link `table`, `view`, and `sheet` parameters are detected automatically and can be overridden in the profile. For Bitable links, **Load tables** selects the intended table/view. Req2Code retains the view for configuration and traceability but deliberately reads records without its filters, then **AI analyze and select work items** lets the current agent map arbitrary columns, including every configured single/multi-select choice, before active rows are filtered locally.

Grant the application the appropriate read-only document scope and make the target document accessible to the application identity. Req2Code validates actual read access before saving the profile.

Enter these values only in the Req2Code private form. They are passed to an app-private local MCP tool, not inserted into the coding-agent conversation. An application created in TAPD Open Platform must use OAuth2; selecting Basic treats its credentials as an API account and can produce a 403.

Configuration lookup order:

1. the file selected by `REQ2CODE_CONFIG`;
2. `.req2code/config.yaml` in the current directory;
3. `~/.req2code/config.yaml`.

For hosts without MCP Apps, the private terminal fallback remains:

```powershell
uv run req2code setup
uv run req2code doctor
```

## 3. Install the host integration

```powershell
req2code integrate codex
# or: req2code integrate claude
# or: req2code integrate cursor
```

This installs the host-native user Skill and registers the stdio MCP server with absolute executable and Req2Code configuration paths. It preserves unrelated MCP servers and creates a `*.req2code.bak` backup before directly editing Codex/Cursor configuration. Use `--force` to update an existing Skill and `--config <path>` for a non-default local configuration file. That file may be created later by the private UI.

Restart Codex/Cursor or open a new Agent task/chat. Open a new Claude Code session. Confirm that `render_req2code_launcher`, `prepare_development_run`, `finalize_development_run`, and `get_run` are available. Configuration, candidate loading, confirmation, approval, and publication are private UI actions. `submit_feishu_table_analysis` is the narrow model-visible callback used only for an explicitly authorized Bitable schema analysis.

Skill-only installation remains available for custom integration work:

```powershell
req2code install-skill codex
# Or use: req2code install-skill claude
# Or use: req2code install-skill cursor
```

## 4. Start from the target project

Open the repository to develop in Codex, Claude Code, or Cursor and enter:

```text
Use req2code-workflow to open Req2Code and let me choose the work-item platform and what to solve.
```

The coding agent then:

1. calls `render_req2code_launcher` once;
2. the private UI lets the human add or choose a named platform/project profile. For Bitable, an explicit AI-analysis click sends a short message containing an analysis ID. The agent uses `get_feishu_table_analysis_task` to retrieve field names/types, all configured select options, and bounded samples without placing a large payload or app-context attachment in the composer. Its JSON mapping opens a fresh selector at the current conversation position; Req2Code then classifies type/status, filters terminal rows locally, and renders key fields. Obvious cover or instruction tables are rejected before analysis;
3. keeps credentials, profile details, and complete unconfirmed rows in component-only data, then automatically sends one self-contained development handoff containing only the confirmed items, their complete content, workflow defaults, execution requirements, and approval boundary;
4. defaults to the current project, current checked-out branch, and no pull unless the human supplied overrides before opening the selector;
5. honors a pre-supplied local path, remote URL, branch, or explicit pull request;
6. calls `prepare_development_run` once with the `selection_id`;
7. receives the complete Req2Code `task_brief` and immediately develops and tests the work.

The brief includes normalized source fields, complete descriptions and acceptance scope, repository, branch, baseline SHA, implementation/testing/Chinese-report requirements, definition of done, and the no-commit/no-push safety boundary. Push remains locked until the human approves the exact run. Codex is the verified UI reference host; Cursor 2.6+ officially supports MCP Apps but still needs a Req2Code release test; Claude Code uses the text/report or external approval fallback because its official client documentation does not promise the same custom HTML surface.

## 5. Repository and branch choices

| Input | Behavior |
| --- | --- |
| No repository | Use the project currently open in the coding agent |
| `local_path` | Develop directly in a clean local Git repository |
| `repo_url` | Clone into an isolated Req2Code-managed workspace |
| No branch for a local repository | Preserve the current branch without creating or switching |
| Explicit branch | Use that branch for all selected work items |
| Local repository + sync approved | Fetch, then run `git pull --ff-only` when that branch exists remotely |
| Local repository + no sync | Do not perform a network update or modify local HEAD |
| No push branch | Publish to the actual work branch after approval |

One work item per branch is the recommended default, but an intentional multi-item shared branch is supported.

Preparation is persisted before Git validation starts. If a Git credential or network operation times out, query `list_runs`/`get_run` for its stage and error instead of submitting the same request repeatedly. `git.command_timeout_seconds` defaults to 120 seconds.

CLI fallbacks:

```powershell
req2code start --item story:101 --item bug:202 --local .

req2code start --item bug:202 --local . --pull

req2code start --item story:101 --item bug:202 --local . `
  --base develop --branch feature/sprint-08 --push-branch feature/sprint-08

req2code start --item bug:202 `
  --repo-url https://git.example.com/team/service.git `
  --base develop --branch fix/tapd-202
```

## 6. Develop, test, and finalize

The current coding agent must inspect the target repository, plan the change, implement every selected item, add/update tests, run appropriate tests/build/lint checks, fix failures, and prepare an implementation/test summary.

It then calls:

```text
finalize_development_run(
  run_id,
  implementation_plan,
  implementation_summary,
  test_evidence,
  tests_passed,
  coverage
)
```

By default Req2Code does not repeat those tests. It stores the evidence, revalidates the protected branch and baseline, fingerprints the diff, writes the Markdown report, and changes a successful run to `waiting_approval`.

CLI fallback:

```powershell
req2code finalize <run_id> `
  --plan "Implementation approach" `
  --summary "Implemented the selected work" `
  --test-evidence "python -m pytest -q: 72 passed" `
  --tests-passed `
  --coverage 92.5
```

For an independent strict rerun, add `--rerun-tests`. `req2code verify` and MCP `verify_development_run` remain strict-mode compatibility aliases.

## 7. Human review and publication

When the run reaches `waiting_approval`, the current agent presents the work items, solution, changed files, tests, Chinese report path, post-approval planned push branch, and approval URL; it explicitly states that nothing has been committed or pushed, then stops.

Inspect the exact state:

```powershell
req2code runs
req2code status <run_id>
git diff
```

Reject without publishing:

```powershell
req2code reject <run_id> --comment "More boundary tests are required"
```

After explicit review and approval:

```powershell
req2code approve <run_id>
```

Req2Code revalidates the branch, baseline HEAD, remote URL, diff fingerprint, and remote target SHA before creating a commit and performing a non-force push. Any state change makes the run stale instead of bypassing the approval boundary.

## Complete conversation example

```text
Human: Use req2code-workflow, open Req2Code, and let me choose the source and work items.
Agent: Shows the work items and asks which items, repository, and branch to use.
Human: Select story:101 and bug:202; use the current project and branch.
Agent: Calls prepare_development_run, follows the task brief, implements, and tests.
Agent: Calls finalize_development_run, presents the report, and states that nothing was committed or pushed.
Human: Reviews the diff/report and explicitly approves the run.
Human/terminal: Runs req2code approve <run_id>.
Req2Code: Revalidates the state, commits, and pushes to the reported target branch.
```
