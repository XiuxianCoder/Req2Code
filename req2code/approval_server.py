from __future__ import annotations

import hmac
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from req2code.config import ConfigManager
from req2code.logging_setup import get_logger
from req2code.replay_guard import ReplayGuard
from req2code.security import sign_payload_with_meta
from req2code.workflow import WorkflowService

logger = get_logger()
app = FastAPI(title="Req2Code Approval Callback API")


def _state_file(cfg, configured_path: str) -> str:
    path = Path(configured_path).expanduser()
    if not path.is_absolute():
        path = Path(cfg.system.state_dir).expanduser() / path.name
    return str(path.resolve())


class ApprovalCallbackRequest(BaseModel):
    run_id: str | None = None
    req_id: str | None = None
    approved: bool
    comment: str = ""


@app.post("/approval/callback")
async def approval_callback(
    request: Request,
    x_req2code_signature: str | None = Header(default=None),
    x_req2code_timestamp: str | None = Header(default=None),
    x_req2code_nonce: str | None = Header(default=None),
):
    cfg = ConfigManager().load()

    # IP allowlist
    client_ip = request.client.host if request.client else ""
    if cfg.review.ip_allowlist and client_ip not in cfg.review.ip_allowlist:
        logger.warning("Blocked callback from IP: %s", client_ip)
        raise HTTPException(status_code=403, detail="IP not allowed")

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    sig_header = cfg.review.signature_header
    ts_header = cfg.review.timestamp_header
    nonce_header = cfg.review.nonce_header

    provided_sig = x_req2code_signature if sig_header.lower() == "x-req2code-signature" else request.headers.get(sig_header)
    provided_ts = x_req2code_timestamp if ts_header.lower() == "x-req2code-timestamp" else request.headers.get(ts_header)
    provided_nonce = x_req2code_nonce if nonce_header.lower() == "x-req2code-nonce" else request.headers.get(nonce_header)

    if not provided_sig or not provided_ts or not provided_nonce:
        raise HTTPException(status_code=401, detail="Missing signature headers")

    try:
        ts_int = int(provided_ts)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp")

    now = int(time.time())
    tol = cfg.review.timestamp_tolerance_seconds
    if abs(now - ts_int) > tol:
        raise HTTPException(status_code=401, detail="Timestamp out of tolerance")

    guard = ReplayGuard(_state_file(cfg, cfg.review.replay_store_file))
    if guard.seen_or_add(provided_nonce, now_ts=now, ttl_seconds=tol):
        raise HTTPException(status_code=401, detail="Replay detected")

    expected = sign_payload_with_meta(cfg.review.callback_secret, body, provided_ts, provided_nonce)
    if not hmac.compare_digest(provided_sig, expected):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = ApprovalCallbackRequest(**body)
    run_id = payload.run_id or payload.req_id
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    service = WorkflowService(cfg)
    try:
        result = (
            service.approve_and_publish(run_id, payload.comment)
            if payload.approved
            else service.reject(run_id, payload.comment)
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info("Callback processed: %s -> %s", run_id, result.status)
    return {
        "run_id": result.run_id,
        "status": result.status,
        "branch": result.work_branch,
        "commit": result.commit_sha,
        "push_target": f"{result.remote_name}/{result.push_branch}",
    }

class ApprovalDecisionRequest(BaseModel):
    approved: bool
    token: str
    comment: str = ""


def _verify_approval_access(request: Request, run_id: str, token: str):
    cfg = ConfigManager().load()
    client_ip = request.client.host if request.client else ""
    if cfg.review.ip_allowlist and client_ip not in cfg.review.ip_allowlist:
        raise HTTPException(status_code=403, detail="IP not allowed")
    service = WorkflowService(cfg)
    try:
        record = service.runs.require(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not token or not hmac.compare_digest(token, record.approval_token):
        raise HTTPException(status_code=401, detail="Invalid approval token")
    return service, record


@app.get("/approval/{run_id}")
async def approval_page(run_id: str, request: Request, token: str = ""):
    import html
    import json
    from pathlib import Path
    from fastapi.responses import HTMLResponse

    _, record = _verify_approval_access(request, run_id, token)
    report = "审核报告不可用"
    if record.report_path and Path(record.report_path).is_file():
        report = Path(record.report_path).read_text(encoding="utf-8")
    run_json = json.dumps(run_id)
    token_json = json.dumps(token)
    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Req2Code 人工审核</title>
<style>body{{font-family:system-ui;max-width:1100px;margin:32px auto;padding:0 20px}}pre{{white-space:pre-wrap;background:#f6f8fa;padding:20px;border-radius:8px}}button{{padding:10px 18px;margin-right:8px}}textarea{{width:100%;min-height:80px}}#publishConfirm{{display:none;margin:18px 0;padding:16px;border:1px solid #d97706;border-radius:8px}}</style></head>
<body><h1>Req2Code 人工审核：{html.escape(run_id)}</h1>
<p><b>当前状态：</b>尚未选择发布，没有提交或推送。准确发布分支将在第二次确认中显示。</p>
<pre>{html.escape(report)}</pre>
<label>审核意见</label><textarea id="comment"></textarea><p>
<button onclick="showPublish()">审核通过，进入发布确认</button>
<button onclick="decide(false)">驳回并结束运行</button></p>
<div id="publishConfirm"><h2>第二次确认：是否提交并推送？</h2>
<p><b>审核通过后计划发布到：</b> {html.escape(record.remote_name)}/{html.escape(record.push_branch)}</p>
<label><input id="publishCheck" type="checkbox" onchange="document.getElementById('publishButton').disabled=!this.checked"> 我已审核准确变更集，并确认提交、推送。</label><p>
<button id="publishButton" disabled onclick="decide(true)">确认提交并推送</button></p></div><pre id="result"></pre>
<script>
function showPublish() {{ document.getElementById('publishConfirm').style.display = 'block'; }}
async function decide(approved) {{
  const response = await fetch('/approval/' + {run_json} + '/decision', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{approved, token: {token_json}, comment: document.getElementById('comment').value}})
  }});
  document.getElementById('result').textContent = await response.text();
}}
</script></body></html>"""
    return HTMLResponse(body)


@app.post("/approval/{run_id}/decision")
async def approval_decision(run_id: str, request: Request, payload: ApprovalDecisionRequest):
    import asyncio

    service, _ = _verify_approval_access(request, run_id, payload.token)
    try:
        if payload.approved:
            record = await asyncio.to_thread(service.approve_and_publish, run_id, payload.comment)
        else:
            record = await asyncio.to_thread(service.reject, run_id, payload.comment)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": record.run_id,
        "status": record.status,
        "commit": record.commit_sha,
        "push_target": f"{record.remote_name}/{record.push_branch}",
    }
