const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

function fakeElement(id = "") {
  const listeners = {};
  return {
    id, value: "", textContent: "", className: "", disabled: false, checked: false,
    hidden: false, open: false, children: [],
    addEventListener(type, handler) { listeners[type] = handler; },
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    replaceChildren(...nodes) { this.children = [...nodes]; },
    setAttribute(name) { if (name === "open") this.open = true; },
    removeAttribute(name) { if (name === "open") this.open = false; },
    showModal() { this.open = true; },
    close() { this.open = false; },
    listeners,
  };
}

async function main() {
  const htmlPath = path.join(__dirname, "..", "req2code", "resources", "development_review.html");
  const html = fs.readFileSync(htmlPath, "utf8");
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  assert(match, "review script is missing");

  const ids = [
    "content", "status", "approve", "changes", "publishDialog", "publishCheck",
    "confirmPublish", "subtitle", "badges", "comment", "publishTarget",
    "branchWarning", "cancelPublish", "publishButton",
  ];
  const elements = Object.fromEntries(ids.map(id => [id, fakeElement(id)]));
  const document = {
    getElementById(id) { return elements[id] || (elements[id] = fakeElement(id)); },
    createElement() { return fakeElement(); },
  };
  const calls = [];
  const followUps = [];
  const review = {
    run_id: "run-123", status: "waiting_approval", push_locked: true,
    work_items: [{ id: "DEMO-BUG-001", type: "bug", title: "示例缺陷", description: "公开演示缺陷说明", details: { priority: "high" } }],
    item_results: [{
      item_id: "BUG-1", solution: "增加确认框", changes: "取消时提前返回",
      changed_files: ["src/delete.ts"], test_evidence: "2 passed",
      acceptance_result: "通过", residual_risks: "无已知风险",
    }],
    changed_files: ["src/delete.ts"], test_result: { passed: true, source: "current_coding_agent", details: "2 passed" },
    verification_count: 1, report_path: "C:/state/report.md", diff_hash: "abc",
    planned_publication_target: "origin/master", protected_branch_warning: true,
    publish_nonce: "secret-once", commit_sha: "", error: "", approval_comment: "",
  };
  const windowListeners = {};
  const window = {
    parent: { postMessage(message) { throw new Error(`unexpected parent message: ${message?.method}`); } },
    setTimeout() { return 1; }, clearTimeout() {},
    addEventListener(type, handler) { windowListeners[type] = handler; },
    openai: {
      toolOutput: { run_id: review.run_id, status: review.status },
      toolResponseMetadata: { mcp_tool_result: { _meta: { "req2code/development-review": review } } },
      async callTool(name, args) {
        calls.push({ name, args });
        assert.equal(name, "publish_reviewed_run_for_ui");
        return { structuredContent: { run_id: review.run_id, status: "completed", commit_sha: "deadbeef", published_target: "origin/master" } };
      },
      async sendFollowUpMessage(message) { followUps.push(message); },
    },
  };

  new Function("window", "document", match[1])(window, document);
  assert.match(elements.subtitle.textContent, /run-123/);
  assert.equal(elements.approve.disabled, false);
  assert.equal(calls.length, 0);

  elements.approve.listeners.click();
  assert.equal(elements.publishDialog.open, true, "first approval click should only open the second-stage dialog");
  assert.equal(elements.publishTarget.textContent, "origin/master");
  assert.equal(elements.branchWarning.hidden, false);
  assert.equal(calls.length, 0, "first approval click must not publish");

  elements.publishCheck.checked = true;
  elements.publishCheck.listeners.change();
  assert.equal(elements.confirmPublish.disabled, false);
  await elements.confirmPublish.listeners.click();

  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].args, {
    run_id: "run-123", publish_nonce: "secret-once", confirmation: "确认提交并推送", comment: "",
  });
  assert.equal(followUps.length, 1);
  assert.match(followUps[0].prompt, /deadbeef/);
  assert.match(elements.status.textContent, /已提交并推送/);
  console.log("development review two-stage harness passed");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
