const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

function fakeElement(id = "") {
  const listeners = {};
  return {
    id, value: "", textContent: "", className: "", hidden: false, type: "",
    disabled: false, checked: false, children: [],
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
  assert(match, "launcher script is missing");

  const ids = [
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
  ];
  const elements = Object.fromEntries(ids.map(id => [id, fakeElement(id)]));
  const document = {
    getElementById(id) { return elements[id]; },
    createElement() { return fakeElement(); },
    createTextNode(text) { return { textContent: text }; },
  };
  const calls = [];
  const followUps = [];
  const launcher = {
    ui_state: "configuration_required", profiles: [], profile_count: 0,
    providers: [{ id: "tapd", label: "TAPD" }], item_type: "all", limit: 200,
  };
  const profile = {
    id: "tapd-1", name: "产品研发", source: "tapd", source_label: "TAPD",
    workspace_id: "12345678", auth_mode: "oauth2", base_url: "https://api.tapd.cn", configured: true,
  };
  const selection = {
    selection_id: "selection-ui", status: "open", source_profile_id: profile.id,
    source_profile_name: profile.name, source: "tapd",
    items: [{ key: "DEMO-001", id: "DEMO-BUG-001", type: "bug", title: "示例缺陷", status: "new" }],
  };
  const windowListeners = {};
  const window = {
    parent: { postMessage(message) {
      if (message?.method !== "ui/message") throw new Error(`unexpected parent message: ${message?.method}`);
      followUps.push({ prompt: message.params.content[0].text, bridge: "ui/message" });
      Promise.resolve().then(() => windowListeners.message({ source: window.parent, data: { jsonrpc: "2.0", id: message.id, result: {} } }));
    } },
    setTimeout() { return 1; }, clearTimeout() {},
    addEventListener(type, handler) { windowListeners[type] = handler; },
    openai: {
      toolOutput: { ui_state: "configuration_required", profile_count: 0 },
      toolResponseMetadata: { mcp_tool_result: { _meta: { "req2code/launcher": launcher } } },
      async callTool(name, args) {
        calls.push({ name, args });
        if (name === "save_source_profile_for_ui") {
          return { ui_state: "source_profile_saved", message: "连接验证成功", profile, profile_count: 1 };
        }
        if (name === "get_req2code_launcher_for_ui") {
          return { _meta: { "req2code/launcher": { ...launcher, profiles: [profile], profile_count: 1 } } };
        }
        if (name === "create_work_item_selection_for_ui") {
          return { structuredContent: { selection_id: selection.selection_id }, _meta: { "req2code/selection": selection } };
        }
        if (name === "confirm_work_item_selection") {
          return {
            selection_id: selection.selection_id, selected_keys: ["DEMO-001"],
            selected_items: [{ key: "DEMO-001", id: selection.items[0].id, type: "bug", title: "示例缺陷", description: "公开演示缺陷说明" }],
            handoff_prompt: `selection_id=${selection.selection_id}\nselected_items=公开演示缺陷说明\nprepare_development_run\nwaiting_approval`,
          };
        }
        throw new Error(`unexpected tool: ${name}`);
      },
      async sendFollowUpMessage(message) { followUps.push({ ...message, bridge: "compatibility" }); },
    },
  };

  new Function("window", "document", match[1])(window, document);

  assert.equal(elements.platformScreen.hidden, false, "first use should ask for a source platform");
  await elements.chooseFeishu.listeners.click();
  elements.newProfile.listeners.click();
  assert.equal(elements.authMode.value, "tenant", "Feishu should use a self-built application");
  assert.equal(elements.baseUrlGroup.hidden, true, "Feishu should hide the TAPD API URL");
  assert.equal(elements.workspaceGroup.hidden, true, "Feishu should hide the TAPD project field");
  assert.equal(elements.feishuDocumentUrlGroup.hidden, false, "Feishu should show the document URL");
  assert.equal(elements.appIdGroup.hidden, false, "Feishu should request an App ID");
  assert.match(elements.configNotice.textContent, /App ID\/App Secret/);
  await elements.cancelConfig.listeners.click();
  elements.changeProvider.listeners.click();
  await elements.chooseTapd.listeners.click();
  elements.newProfile.listeners.click();
  assert.equal(elements.configScreen.hidden, false, "adding a platform profile should open the private configuration form");
  elements.profileName.value = "产品研发";
  elements.provider.value = "tapd";
  elements.authMode.value = "oauth2";
  elements.baseUrl.value = "https://api.tapd.cn";
  elements.workspaceId.value = "12345678";
  elements.appId.value = "private-client";
  elements.appSecret.value = "private-secret";
  await elements.configForm.listeners.submit({ preventDefault() {} });

  assert.equal(elements.items.children.length, 1, "saved profile should proceed directly to work items");
  const checkbox = elements.items.children[0].children[0];
  checkbox.checked = true;
  checkbox.listeners.change();
  await elements.confirm.listeners.click();

  assert.deepEqual(calls.map(call => call.name), [
    "get_req2code_launcher_for_ui", "get_req2code_launcher_for_ui", "get_req2code_launcher_for_ui",
    "save_source_profile_for_ui", "get_req2code_launcher_for_ui",
    "create_work_item_selection_for_ui", "confirm_work_item_selection",
  ]);
  assert.equal(calls.find(call => call.name === "save_source_profile_for_ui").args.app_secret, "private-secret");
  assert.equal(calls.find(call => call.name === "create_work_item_selection_for_ui").args.profile_id, "tapd-1");
  assert.equal(followUps.length, 1);
  assert.equal(followUps[0].bridge, "ui/message");
  assert.match(followUps[0].prompt, /公开演示缺陷说明/);
  assert.doesNotMatch(followUps[0].prompt, /private-client|private-secret/);
  console.log("launcher configuration and selection harness passed");
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
