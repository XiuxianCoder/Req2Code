const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

function fakeElement(id = "") {
  const listeners = {};
  return {
    id,
    value: "",
    textContent: "",
    className: "",
    hidden: false,
    type: "",
    disabled: false,
    checked: false,
    children: [],
    addEventListener(type, handler) { listeners[type] = handler; },
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    replaceChildren(...nodes) { this.children = [...nodes]; },
    listeners,
  };
}

async function main() {
  const htmlPath = path.join(__dirname, "..", "req2code", "resources", "work_item_selector.html");
  const html = fs.readFileSync(htmlPath, "utf8");
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  assert(match, "selector script is missing");

  const elements = Object.fromEntries(
    [
      "pageTitle", "pageHint", "summary", "platformScreen", "profileScreen", "configScreen", "selectorScreen",
      "profiles", "items", "search", "typeFilter", "status", "confirm", "all", "retryAnalysis",
      "chooseTapd", "chooseFeishu", "chooseMock", "newProfile", "refreshProfiles", "changeProvider", "changeProfile", "configForm", "profileId", "profileName",
      "provider", "authMode", "baseUrl", "workspaceId", "appId", "appSecret",
      "authGroup", "baseUrlGroup", "workspaceGroup", "appIdGroup", "secretGroup",
    "feishuDocumentUrlGroup", "feishuResourceTypeGroup", "feishuParseModeGroup", "feishuTableIdGroup", "feishuViewIdGroup", "feishuSheetIdGroup", "feishuFieldMappingGroup",
    "documentUrl", "resourceType", "parseMode", "tableId", "viewId", "sheetId", "configNotice",
      "inspectFeishuBitable", "feishuTableOptions", "feishuViewOptions", "feishuInspectStatus",
      "feishuIdField", "feishuTitleField", "feishuDescriptionField", "feishuTypeField", "feishuStatusField", "feishuPriorityField", "feishuSeverityField", "feishuOwnerField", "feishuReporterField", "feishuAcceptanceField", "feishuUpdatedField",
      "appIdLabel", "secretLabel", "saveProfile", "cancelConfig", "configStatus",
    ].map(id => [id, fakeElement(id)]),
  );
  const document = {
    getElementById(id) { return elements[id]; },
    createElement() { return fakeElement(); },
    createTextNode(text) { return { textContent: text }; },
  };
  const calls = [];
  const followUps = [];
  const selection = {
    selection_id: "selection-123",
    status: "open",
    items: [
      {
        key: "DEMO-001", id: "DEMO-BUG-001", type: "bug", title: "Card layout",
        status: "in_progress", priority: "high", severity: "serious", owner: "Developer",
        reporter: "Reporter", updated_at: "2026-08-15 12:00:00", description_excerpt: "Fix the card.",
      },
      { key: "DEMO-002", id: "DEMO-REQ-001", type: "story", title: "New flow" },
    ],
  };
  const windowListeners = {};
  const window = {
    parent: { postMessage(message) {
      if (message?.method !== "ui/message") throw new Error(`unexpected parent message: ${message?.method}`);
      followUps.push({ prompt: message.params.content[0].text, bridge: "ui/message" });
      Promise.resolve().then(() => windowListeners.message({ source: window.parent, data: { jsonrpc: "2.0", id: message.id, result: {} } }));
    } },
    setTimeout() { return 1; },
    clearTimeout() {},
    addEventListener(type, handler) { windowListeners[type] = handler; },
    openai: {
      toolOutput: { selection_id: selection.selection_id, item_count: 2 },
      toolResponseMetadata: {
        status: "success",
        call_tool_result: { structuredContent: { selection_id: selection.selection_id } },
        mcp_tool_result: { _meta: { "req2code/selection": selection } },
      },
      async callTool(name, args) {
        calls.push({ name, args });
        assert.equal(name, "confirm_work_item_selection");
        return {
          structuredContent: {
            selection_id: selection.selection_id,
            selected_keys: ["DEMO-001"],
            selected_items: [{
              key: "DEMO-001",
              spec: "bug:DEMO-BUG-001",
              id: "DEMO-BUG-001",
              type: "bug",
              title: "Card layout",
              description: "Move the checkbox and add single delete.",
              source: "tapd",
            }],
            handoff_prompt: [
              "Req2Code 已确认开发任务。",
              `selection_id=${selection.selection_id}`,
              "selected_keys=DEMO-001",
              'selected_items=[{"key":"DEMO-001","description":"Move the checkbox and add single delete."}]',
              "调用 prepare_development_run，然后停在 waiting_approval。",
            ].join("\n"),
          },
        };
      },
      async sendFollowUpMessage(message) { followUps.push({ ...message, bridge: "compatibility" }); },
    },
  };

  new Function("window", "document", match[1])(window, document);

  assert.equal(elements.items.children.length, 2, "hidden metadata should hydrate both rows");
  assert.match(elements.summary.textContent, /需求 1 · 缺陷 1/);
  elements.typeFilter.value = "bug";
  elements.typeFilter.listeners.change();
  assert.equal(elements.items.children.length, 1, "type filter should retain only bugs");
  const checkbox = elements.items.children[0].children[0];
  checkbox.checked = true;
  checkbox.listeners.change();
  await elements.confirm.listeners.click();

  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].args.selected_keys, ["DEMO-001"]);
  assert.equal(followUps.length, 1);
  assert.equal(followUps[0].bridge, "ui/message");
  assert.match(followUps[0].prompt, /selection_id=selection-123/);
  assert.match(followUps[0].prompt, /Move the checkbox and add single delete/);
  assert.match(followUps[0].prompt, /prepare_development_run/);
  assert.match(followUps[0].prompt, /waiting_approval/);
  console.log("selector compatibility bridge harness passed");
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
