from __future__ import annotations

import socket
from dataclasses import dataclass

from req2code.config import AgentConfig
from req2code.engine_preflight import inspect_engine


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def _is_placeholder(value: str) -> bool:
    return (not value) or ("REPLACE_ME" in value)


def _can_connect(host: str, port: int, timeout: float = 1.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def run_doctor(
    cfg: AgentConfig,
    approval_host: str,
    approval_port: int,
    check_legacy_engine: bool = False,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    if cfg.source == "feishu":
        auth_mode = (cfg.feishu.auth_mode or "").lower()
        auth_mode_ok = auth_mode == "tenant"
        checks.append(
            DoctorCheck(
                "feishu.auth_mode",
                auth_mode_ok,
                "self-built application" if auth_mode == "tenant" else f"unsupported: {auth_mode or '(empty)'}",
            )
        )
        credentials_ok = all(not _is_placeholder(value) for value in (cfg.feishu.app_id, cfg.feishu.app_secret))
        checks.append(
            DoctorCheck(
                "feishu.application_credentials",
                credentials_ok,
                "configured" if credentials_ok else "missing app_id/app_secret",
            )
        )
        document_ok = bool((cfg.feishu.document_url or "").strip())
        checks.append(
            DoctorCheck(
                "feishu.document_url",
                document_ok,
                cfg.feishu.document_url if document_ok else "missing document URL",
            )
        )
    else:
        tapd_ok = all(
            not _is_placeholder(value)
            for value in (cfg.tapd.app_id, cfg.tapd.app_secret, cfg.tapd.workspace_id)
        )
        auth_mode = (cfg.tapd.auth_mode or "").lower()
        auth_mode_ok = auth_mode in {"basic", "oauth2"}
        checks.append(
            DoctorCheck(
                "tapd.auth_mode",
                auth_mode_ok,
                (
                    "open application OAuth2"
                    if auth_mode == "oauth2"
                    else ("API account Basic" if auth_mode == "basic" else f"unsupported: {auth_mode or '(empty)'}")
                ),
            )
        )
        checks.append(
            DoctorCheck(
                "tapd.oauth2_credentials" if auth_mode == "oauth2" else "tapd.api_account_credentials",
                tapd_ok,
                (
                    "configured"
                    if tapd_ok
                    else (
                        "missing app_id/app_secret/workspace_id"
                        if auth_mode == "oauth2"
                        else "missing API account/API password/workspace_id"
                    )
                ),
            )
        )

    if check_legacy_engine:
        active = (cfg.engines.active or "claude_code").lower().replace("-", "_")
        try:
            engine_check = inspect_engine(cfg, active)
        except ValueError:
            checks.append(DoctorCheck("engine.active", False, f"unsupported engine: {active}"))
        else:
            checks.append(
                DoctorCheck(
                    "engine.executable",
                    engine_check.installed,
                    f"{active}: {engine_check.executable or engine_check.detail}",
                )
            )
            checks.append(
                DoctorCheck(
                    "engine.authentication",
                    engine_check.ok,
                    engine_check.detail,
                )
            )

    checks.append(
        DoctorCheck(
            "review.callback_secret",
            not _is_placeholder(cfg.review.callback_secret),
            "configured" if not _is_placeholder(cfg.review.callback_secret) else "missing or placeholder",
        )
    )
    checks.append(
        DoctorCheck(
            "review.ip_allowlist",
            bool(cfg.review.ip_allowlist),
            ",".join(cfg.review.ip_allowlist) if cfg.review.ip_allowlist else "empty",
        )
    )
    listening = _can_connect(approval_host, approval_port)
    checks.append(
        DoctorCheck(
            "approval.endpoint",
            not listening,
            f"{approval_host}:{approval_port} seems free" if not listening else f"{approval_host}:{approval_port} already in use",
        )
    )
    return checks
