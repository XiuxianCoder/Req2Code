const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

function fakeElement(id = "") {
  const listeners = {};
  return {
    id, value: "", textContent: "", className: "", hidden: false, type: "", style: {},
    disabled: false, checked: false, children: [],
    addEventListener(type, handler) { listeners[type] = handler; },
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    replaceChildren(...nodes) { this.children = [...nodes]; },
    listeners,
  };
}

async function main() {
  const html = fs.readFileSync(path.join(__dirname, "..", "req2code", "resources", "work_item_selector.html"), "utf8");
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  assert(match, "selector script is missing");
  const ids = [
    "pageTitle", "pageHint", "summary", "platformScreen", "profileScreen", "configScreen", "selectorScreen",
    "profiles", "items", "search", "typeFilter", "status", "confirm", "all", "retryAnalysis",
    "chooseTapd", "chooseFeishu", "chooseMock", "newProfile", "refreshProfiles", "changeProvider", "changeProfile",
    "configForm", "profileId", "profileName", "provider", "authMode", "baseUrl", "workspaceId", "appId", "appSecret",
    "authGroup", "baseUrlGroup", "workspaceGroup", "appIdGroup", "secretGroup",
    "feishuDocumentUrlGroup", "feishuResourceTypeGroup", "feishuParseModeGroup", "feishuTableIdGroup", "feishuViewIdGroup",
    "feishuSheetIdGroup", "feishuFieldMappingGroup", "documentUrl", "resourceType", "parseMode", "tableId", "viewId",
    "sheetId", "configNotice", "inspectFeishuBitable", "feishuTableOptions", "feishuViewOptions", "feishuInspectStatus",
    "feishuIdField", "feishuTitleField", "feishuDescriptionField", "feishuTypeField", "feishuStatusField",
    "feishuPriorityField", "feishuSeverityField", "feishuOwnerField", "feishuReporterField", "feishuAcceptanceField",
    "feishuUpdatedField", "appIdLabel", "secretLabel", "saveProfile", "cancelConfig", "configStatus",
  ];
  const elements = Object.fromEntries(ids.map(id => [id, fakeElement(id)]));
  const document = {
    getElementById(id) { return elements[id]; },
    createElement() { return fakeElement(); },
    createTextNode(text) { return { textContent: text }; },
  };
  const profile = {
    id: "feishu-1", name: "飞书问题库", source: "feishu", source_label: "飞书",
    resource_type: "bitable", document_url: "https://example.feishu.cn/base/app?table=tblIssues",
  };
  const launcher = { ui_state: "choose_source_profile", profiles: [profile], profile_count: 1, item_type: "all", limit: 200 };
  const selection = {
    selection_id: "selection-feishu", status: "open", source_profile_id: profile.id, source_profile_name: profile.name,
    source: "feishu", source_analysis_id: "analysis-1",
    items: [{
      key: "B0001", id: "rec1", type: "bug", title: "保存失败", status: "未解决",
      description_excerpt: "点击保存没有响应", display_fields: { 问题分类: "问题", 角色: "PM" },
    }],
  };
  const calls = [];
  const followUps = [];
  let failAnalysis = false;
  const windowListeners = {};
  const window = {
    parent: { postMessage(message) {
      if (message?.method === "ui/message") {
        followUps.push({ prompt: message.params.content[0].text, bridge: "ui/message" });
      } else if (message?.method !== "ui/initialize") {
        throw new Error(`unexpected parent message: ${message?.method}`);
      }
      Promise.resolve().then(() => windowListeners.message({ source: window.parent, data: { jsonrpc: "2.0", id: message.id, result: {} } }));
    } },
    setTimeout(callback, delay) { if (delay === 1500) Promise.resolve().then(callback); return 1; },
    clearTimeout() {}, addEventListener(type, handler) { windowListeners[type] = handler; },
    openai: {
      toolOutput: { ui_state: "choose_source_profile", profile_count: 1 },
      toolResponseMetadata: { mcp_tool_result: { _meta: { "req2code/launcher": launcher } } },
      async callTool(name, args) {
        calls.push({ name, args });
        if (name === "get_req2code_launcher_for_ui") return { _meta: { "req2code/launcher": launcher } };
        if (name === "create_feishu_table_analysis_for_ui") {
          if (failAnalysis) throw new Error("temporary analysis failure");
          return { analysis_id: "analysis-1" };
        }
        if (name === "create_work_item_selection_for_ui") {
          return { structuredContent: { selection_id: selection.selection_id }, _meta: { "req2code/selection": selection } };
        }
        throw new Error(`unexpected tool: ${name}`);
      },
      async sendFollowUpMessage(message) { followUps.push({ ...message, bridge: "compatibility" }); },
    },
  };

  new Function("window", "document", match[1])(window, document);
  await elements.chooseFeishu.listeners.click();
  const card = elements.profiles.children[0];
  const useButton = card.children[1].children[0];
  assert.equal(useButton.textContent, "AI 解析并选择工作项");
  assert.match(card.children[2].textContent, /全部选择项/);
  await useButton.listeners.click();

  assert.deepEqual(calls.map(call => call.name), [
    "get_req2code_launcher_for_ui",
    "create_feishu_table_analysis_for_ui",
  ]);
  assert.equal(followUps.length, 1);
  assert.equal(followUps[0].bridge, "ui/message");
  assert.match(followUps[0].prompt, /analysis_id=analysis-1/);
  assert.match(followUps[0].prompt, /get_feishu_table_analysis_task/);
  assert.doesNotMatch(followUps[0].prompt, /analysis_payload/);
  assert.match(elements.items.children[0].textContent, /当前对话底部/);

  windowListeners["openai:set_globals"]({ detail: { globals: {
    toolOutput: { analysis_id: "analysis-1", status: "completed", profile_id: profile.id },
    toolResponseMetadata: { mcp_tool_result: { _meta: { "req2code/feishu-analysis": {
      analysis_id: "analysis-1", status: "completed", profile_id: profile.id, profile_name: profile.name,
    } } } },
  } } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls[2].name, "create_work_item_selection_for_ui");
  assert.equal(calls[2].args.analysis_id, "analysis-1");
  assert.equal(elements.items.children.length, 1);
  assert.match(elements.items.children[0].children[1].children.at(-1).children[0].textContent, /问题分类：问题/);
  failAnalysis = true;
  await useButton.listeners.click();
  assert.equal(elements.retryAnalysis.hidden, false, "analysis failures should expose a direct retry action");
  assert.match(elements.items.children[0].textContent, /temporary analysis failure/);
  console.log("Feishu AI schema analysis UI harness passed");
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
