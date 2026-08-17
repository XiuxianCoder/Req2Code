# Changelog

All notable changes to Req2Code will be documented in this file. The project follows semantic versioning after its first stable release.

## [Unreleased]

- Added opt-in AI schema analysis for Feishu Bitable, including field types, complete configured single/multi-select choices, bounded sample values, structured JSON mapping, local active/terminal filtering, and key-field rendering without exposing credentials.
- Moved Feishu schema payloads behind an explicitly authorized read-only analysis tool, avoiding both visible large follow-up messages and composer context attachments; the analysis callback now opens a fresh selector at the current conversation position, and obvious instruction/cover tables are rejected before agent analysis.
- Bitable record reads now ignore saved Feishu view filters and apply the agent-mapped active/terminal status filter locally, preventing unresolved rows from being hidden by presentation views.
- Fixed Feishu analysis handoff to prefer the standard MCP Apps `ui/message` bridge, added the compatibility-method title, and exposed a direct retry button when analysis delivery or completion fails.

## [0.10.0] - 2026-08-17

- Added Feishu as a named work-item source using self-built application credentials and tenant-token authentication.
- Added `/docx/`, `/wiki/`, `/base/`, and `/sheets/` support, including native document-table rows, heading sections, whole-document tasks, Wiki node resolution, Bitable records, and spreadsheet rows.
- Added a platform-first MCP Apps launcher with separate TAPD, Feishu, and Mock profile lists plus private add, edit, connection validation, and delete actions.
- Generalized confirmed source metadata and generated task briefs while retaining `tapd_fields` compatibility for existing integrations.
- Added conservative local field mapping and requirement/defect classification so unconfirmed Feishu content remains outside the coding-model context.
- Added private Bitable table/view discovery, explicit table selection, saved-profile refresh, and URL rewriting when switching between tables in one Bitable application.

## [0.7.0] - 2026-08-15

- Added a structured Chinese development-review MCP App that opens automatically after finalization and shows every selected requirement or bug with its solution/root cause, concrete changes, associated files, test evidence, acceptance result, and residual risks.
- Added per-work-item `item_results` to persisted runs and review snapshots, including compatibility synthesis for older clients.
- Added a two-stage human publication gate: the first review action performs no Git operation, while the second dialog reveals the planned branch, warns for `main`/`master`, and requires an acknowledgment before commit/push.
- Restricted publication and change-request actions to app-only MCP tools and enforced a private one-time review nonce plus an exact second-stage confirmation on the server.
- Removed planned publication targets from normal model-facing run output and primary review text; the target is shown only during the second publication confirmation or after successful publication.
- Kept the Markdown report as an audit snapshot and retained CLI/external approval paths as fallbacks for hosts without MCP Apps.

## [0.6.6] - 2026-08-15

- Replaced `git branch --show-current` with direct local `.git/HEAD` inspection so a local branch check cannot hang finalization.
- Made transient current-agent finalization errors retryable and added recovery for legacy `failed` runs that already completed development.
- Kept repository push URLs disabled through interrupted, failed, stale, and changes-requested states; only explicit human approval may restore the real push URL for publication.
- Changed current-agent task briefs, review reports, reviewer notifications, approval-page labels, and status output to Chinese.
- Renamed the model-facing destination field to `post_approval_push_target` and explicitly labels it as the planned branch used only after approval.

## [0.6.5] - 2026-08-15

- Fixed Codex MCP Apps confirmation handoff so the complete selected TAPD data and execution instructions are automatically sent instead of being left unsent in the composer.
- Added a server-generated, self-contained development handoff with `selection_id`, selected item details, repository defaults, testing/report requirements, and the human approval gate.
- Published selector resource v6 and updated the Req2Code workflow Skill and bilingual documentation.

## [0.6.4] - 2026-08-15

- Excluded resolved, verified, closed, rejected, completed, cancelled, and other terminal work items from selectable TAPD candidates while fetching a broad window before filtering.
- Added the portable MCP Apps `ui/update-model-context` handoff so the confirmed selection ID and complete selected descriptions reach the coding agent without rendering the internal orchestration prompt in chat.
- Reduced the post-confirmation component message to a single natural-language development trigger, with a compatibility fallback for hosts that do not support model-context updates.
- Defaulted post-selection execution to the current coding project, current checked-out branch, and no pull; repository, branch, or sync questions are asked only for explicit overrides or genuine ambiguity.
- Expanded the generated task brief with normalized TAPD fields, complete description and acceptance scope, definition of done, exact testing evidence requirements, and review-report requirements.
- Updated all packaged and plugin Skill copies to launch development directly after confirmation and avoid echoing internal handoff instructions.
- Published selector resource v5 and bumped the package to 0.6.4.

## [0.6.3] - 2026-08-15

- Fixed TAPD Bug records being classified as requirements by using the `/stories` or `/bugs` endpoint as the authoritative work-item kind instead of TAPD's optional business-subtype field.
- Added a defensive Bug-wrapper check when generating short selection keys and confirmed item specs, including compatibility repair for older open sessions.
- Added requirement/defect counts and a type filter to the checkbox selector.
- Expanded selector cards with status, priority, severity, owner, reporter, module, iteration, update time, and a compact description excerpt.
- Reduced selector transfer size by keeping full descriptions and raw TAPD metadata server-side until human confirmation.
- Published a new versioned selector resource URI to avoid stale iframe caches.

## [0.6.2] - 2026-08-15

- Fixed Codex/ChatGPT component-bridge hydration by reading hidden result metadata from the nested `toolResponseMetadata.mcp_tool_result` / `call_tool_result` envelopes and subscribing to delayed `openai:set_globals` updates.
- Added an app-only private selector-data tool as a compatibility fallback; unconfirmed candidates remain unavailable to the model.
- Switched selector confirmation and follow-up messages to feature-detect the `window.openai` compatibility APIs before using the portable MCP Apps bridge.
- Published a new versioned selector resource URI to avoid stale iframe caches.

## [0.6.1] - 2026-08-15

- Fixed the MCP Apps selector initialization handshake so Codex can deliver tool results after rendering the UI.
- Moved unconfirmed TAPD candidates into UI-only tool-result metadata; the coding agent now sees only selection session state and the human-confirmed items.
- Changed the Skill to wait for UI confirmation instead of immediately dumping a Markdown fallback list.
- Kept the confirmed repository/branch/sync step, after which `prepare_development_run` returns the complete implementation, testing, reporting, and approval-gate prompt to the current coding agent.

## [0.6.0] - 2026-08-15

- Added server-owned work-item selection sessions with recognizable short keys and an optional MCP Apps checkbox selector; text-only clients keep a complete fallback workflow.
- Added explicit local-repository synchronization through `sync_before_start` / `req2code start --pull`, using fetch plus `git pull --ff-only` without merges or rebases. No network update occurs by default.
- Added bounded Git command timeouts and actionable timeout errors.
- Persisted `preparing` task sessions before Git preparation, including preparation stage and failures, so a slow or failed operation remains queryable.
- Made identical active current-agent preparation requests idempotent to prevent repeated calls from creating duplicate sessions.
- Clarified the Skill workflow: Req2Code prepares the task brief for the current agent and never launches another coding agent.

## [0.5.2] - 2026-08-15

- Added an explicit TAPD authentication choice to `req2code setup`: open-application OAuth2 (`app_id`/`app_secret`) or API-account Basic (`api_user`/`api_password`).
- Changed new configurations to default to open-application OAuth2 while preserving explicit Basic configurations.
- Added authentication-aware Doctor checks and actionable, bounded TAPD API/token error details.
- Corrected the active local TAPD configuration to OAuth2 after verifying both story and bug endpoints with the configured open application.

## [0.5.1] - 2026-08-15

- Added `finalize_development_run` and `req2code finalize` as the default current-agent handoff: Req2Code stores the agent's implementation/test evidence, validates Git state, fingerprints the diff, and creates the human-review package without rerunning tests.
- Kept `verify_development_run` and `req2code verify` as explicit strict-mode compatibility entry points that rerun configured checks.
- Updated the generated task brief and packaged Skill so Codex, Claude Code, or Cursor owns the complete implementation, testing, and result summary while Req2Code owns orchestration and the approval gate.
- Added dedicated English and Simplified Chinese usage guides covering installation, MCP/Skill integration, selection, repository/branch behavior, finalization, and approval.
- Documented direct `config.toml` MCP setup for Windows Codex desktop installations where the standalone `codex` CLI is not on `PATH`.

## [0.5.0] - 2026-08-15

- Changed the default architecture to current-agent execution: Req2Code no longer launches a nested Claude Code, Codex, or Cursor process.
- Added `prepare_development_run` and `verify_development_run` MCP tools for task briefs, deterministic tests, reports, and the human approval gate.
- Changed `req2code start` to prepare work for the current coding-agent conversation and added `req2code verify`.
- Made branch selection optional: a local run with no branch preserves the currently checked-out branch without creating or switching branches.
- Removed engine/model selection from normal setup; legacy nested execution remains opt-in through `--legacy-engines`.
- Reworked the Req2Code Skill around the active repository conversation and reduced repeated project-context injection.
- Packaged the Skill in the wheel and added `req2code install-skill codex|claude`.
- Added current-agent execution metadata, verification attempts, test evidence, bilingual docs, and approval-gate tests.

## [0.4.1] - 2026-08-10

- Added explicit reuse or replacement of an existing TAPD setup.
- Added TAPD workspace-page URL detection and automatic workspace ID extraction.
- Save completed TAPD credentials before engine preflight so an unavailable engine does not discard them.
- Clarified that the engine command prompt expects a CLI executable/wrapper, not a model, and allows returning to engine selection.

## [0.4.0] - 2026-08-07

- Added per-engine default model configuration and interactive model selection.
- Added per-run `--model` overrides for Claude Code, Codex, and Cursor.
- Added safe model injection for official CLI commands and explicit placeholders for custom wrappers.
- Added model provenance to persisted runs, MCP responses, CLI status, and approval reports.
- Added schema v5 migration for existing configurations.

## [0.3.0] - 2026-08-07

- Added Git-SHA-bound project memory with full and incremental refresh.
- Added relevant-context retrieval, approved-memory promotion, and native instruction export.
- Added same-run Codex and Claude Code session reuse with safe fallback.
- Added per-project bare mirrors with isolated run workspaces.
- Added read-only project-memory MCP tools and project management CLI commands.
- Added schema v4 configuration switches for memory, mirrors, and sessions.
- Added bilingual English and Simplified Chinese documentation.
- Added a disposable Mock end-to-end demo repository generator.
- Added GitHub Actions testing for Python 3.10, 3.11, and 3.12.
- Added CLI version output and packaging smoke coverage.

## [0.2.0] - 2026-08-07

- Added approval-gated multi-item development runs.
- Added local repository and managed remote-clone modes.
- Added Claude Code, Codex, and Cursor engine selection and preflight checks.
- Added persistent run reports, repository fingerprints, and stale-run protection.
- Added CLI, stdio MCP server, and Agent Skill integration.
