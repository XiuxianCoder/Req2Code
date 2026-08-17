from __future__ import annotations

import time
from typing import Any, Iterable

import requests

from req2code.config import TapdFieldMappingConfig
from req2code.connectors.base import SourceConnector
from req2code.logging_setup import get_logger
from req2code.models import TaskType, WorkItem
from req2code.tapd_stats import TapdErrorStats

logger = get_logger()


class TapdConnector(SourceConnector):
    """TAPD connector supporting API-account Basic and open-application OAuth2."""

    def __init__(
        self,
        base_url: str = "",
        workspace_id: str = "",
        latest_endpoint: str = "/stories",
        detail_endpoint: str = "/stories/{id}",
        field_mapping: TapdFieldMappingConfig | None = None,
        bug_latest_endpoint: str = "/bugs",
        bug_detail_endpoint: str = "/bugs/{id}",
        bug_field_mapping: TapdFieldMappingConfig | None = None,
        default_item_type: str = "story",
        auth_mode: str = "oauth2",
        app_id: str = "",
        app_secret: str = "",
        token_endpoint: str = "/tokens/request_token",
        auth_scheme: str = "Bearer",
        auth_header_name: str = "Authorization",
        timeout_seconds: int = 20,
        retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        rate_limit_qps: float = 5.0,
        error_stats_path: str = ".req2code/tapd_error_stats.yaml",
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.workspace_id = workspace_id
        self.latest_endpoint = latest_endpoint
        self.detail_endpoint = detail_endpoint
        self.field_mapping = field_mapping or TapdFieldMappingConfig()

        self.bug_latest_endpoint = bug_latest_endpoint
        self.bug_detail_endpoint = bug_detail_endpoint
        self.bug_field_mapping = bug_field_mapping or TapdFieldMappingConfig(
            id_field="Bug.id",
            title_field="Bug.title",
            description_field="Bug.description",
            type_field="Bug.type",
        )
        self.default_item_type = (default_item_type or "story").lower()

        self.auth_mode = (auth_mode or "oauth2").lower()
        self.app_id = app_id
        self.app_secret = app_secret
        self.token_endpoint = token_endpoint
        self.auth_scheme = auth_scheme
        self.auth_header_name = auth_header_name
        self.timeout_seconds = timeout_seconds
        self.retries = max(1, retries)
        self.retry_backoff_seconds = retry_backoff_seconds
        self.rate_limit_qps = rate_limit_qps
        self._last_request_ts = 0.0
        self.stats = TapdErrorStats(error_stats_path)

        self._access_token: str = ""
        self.last_error: str = ""

    # -- HTTP helpers --------------------------------------------------------

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers[self.auth_header_name] = f"{self.auth_scheme} {token}".strip()
        return headers

    def _basic_auth(self) -> tuple[str, str] | None:
        if self.app_id and self.app_secret:
            return self.app_id, self.app_secret
        return None

    def _throttle(self) -> None:
        if self.rate_limit_qps <= 0:
            return
        min_interval = 1.0 / self.rate_limit_qps
        now = time.time()
        wait = min_interval - (now - self._last_request_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.time()

    def _classify_error(self, exc: Exception | None, status_code: int | None) -> str:
        if status_code in {401, 403}:
            return "auth"
        if status_code == 429:
            return "rate_limit"
        if status_code and status_code >= 500:
            return "server"
        if status_code and status_code >= 400:
            return "client_error"
        if isinstance(exc, requests.Timeout):
            return "timeout"
        if isinstance(exc, requests.RequestException):
            return "network"
        return "unknown"

    def _response_info(self, response: requests.Response) -> str:
        """Return a bounded TAPD error message without request credentials or headers."""
        try:
            payload = response.json()
        except ValueError:
            return (response.text or "").strip()[:500]
        if isinstance(payload, dict):
            return str(payload.get("info") or payload.get("message") or "").strip()[:500]
        return ""

    # -- Token management ----------------------------------------------------

    def _extract_value(self, payload: Any, path: str) -> Any:
        """Extract a nested value from a dict using dot-notation path."""
        cur = payload
        for part in (path or "").split("."):
            if not part:
                continue
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    def _extract_access_token(self, payload: dict[str, Any]) -> str:
        candidates = [
            payload.get("access_token"),
            payload.get("token"),
            self._extract_value(payload, "data.access_token"),
            self._extract_value(payload, "data.token"),
        ]
        for c in candidates:
            if isinstance(c, str) and c.strip():
                return c.strip()
        return ""

    def _request_access_token(self) -> str:
        if self.auth_mode not in {"basic", "oauth2"}:
            self.last_error = f"unsupported auth_mode={self.auth_mode}"
            self.stats.inc("auth")
            return ""
        auth = self._basic_auth()
        if not auth:
            self.last_error = "open application app_id/app_secret is missing"
            self.stats.inc("auth")
            return ""

        url = f"{self.base_url}{self.token_endpoint}"
        data = {"grant_type": "client_credentials"}
        last_exc: Exception | None = None
        last_status: int | None = None

        for i in range(self.retries):
            self._throttle()
            try:
                resp = requests.post(url, auth=auth, data=data, timeout=self.timeout_seconds)
                last_status = resp.status_code
                if resp.status_code >= 400:
                    self.last_error = f"token HTTP {resp.status_code}: {self._response_info(resp)}".rstrip(": ")
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"retryable status={resp.status_code}")
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict):
                    self.stats.inc("mapping")
                    return ""
                token = self._extract_access_token(payload)
                if token:
                    self._access_token = token
                    self.last_error = ""
                    return token
                self.last_error = "token response did not contain access_token"
                self.stats.inc("mapping")
                return ""
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if not self.last_error:
                    self.last_error = f"token {type(exc).__name__}: {exc}"[:500]
                if i < self.retries - 1:
                    time.sleep(self.retry_backoff_seconds * (i + 1))

        self.stats.inc(self._classify_error(last_exc, last_status))
        return ""

    def _ensure_access_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token:
            return self._access_token
        return self._request_access_token()

    # -- API request ---------------------------------------------------------

    def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        self.last_error = ""
        basic_auth = self._basic_auth() if self.auth_mode == "basic" else None
        token = "" if basic_auth else self._ensure_access_token()
        if self.auth_mode == "basic" and not basic_auth:
            self.last_error = "API account/API password is missing"
            logger.warning("No Basic Auth credentials available for %s", url)
            return None
        if self.auth_mode != "basic" and not token:
            logger.warning("No OAuth access token available for %s", url)
            return None
        last_exc: Exception | None = None
        last_status: int | None = None
        for i in range(self.retries):
            self._throttle()
            try:
                resp = requests.get(
                    url,
                    auth=basic_auth,
                    headers=self._headers(token=token),
                    params=params,
                    timeout=self.timeout_seconds,
                )
                last_status = resp.status_code
                if resp.status_code >= 400:
                    self.last_error = f"HTTP {resp.status_code}: {self._response_info(resp)}".rstrip(": ")
                if resp.status_code in {401, 403} and self.auth_mode != "basic":
                    token = self._ensure_access_token(force_refresh=True)
                    if not token:
                        self.stats.inc("auth")
                        return None
                    if i < self.retries - 1:
                        time.sleep(self.retry_backoff_seconds * (i + 1))
                    continue
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"retryable status={resp.status_code}")
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict):
                    raise ValueError("TAPD response is not a JSON object")
                if "status" in payload and str(payload.get("status")) not in {"1", "True", "true"}:
                    self.last_error = f"TAPD API error: {payload.get('info') or payload.get('status')}"[:500]
                    raise ValueError(self.last_error)
                self.last_error = ""
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if not self.last_error:
                    self.last_error = f"{type(exc).__name__}: {exc}"[:500]
                if i < self.retries - 1:
                    time.sleep(self.retry_backoff_seconds * (i + 1))
        self.stats.inc(self._classify_error(last_exc, last_status))
        return None

    # -- Item building -------------------------------------------------------

    def _parse_type(self, raw_type: str | None) -> TaskType:
        text = (raw_type or "").lower()
        if text in {"bug", "defect"}:
            return TaskType.BUG
        return TaskType.REQUIREMENT

    def _build_item(
        self,
        record: dict[str, Any],
        mapping: TapdFieldMappingConfig,
        req_id_fallback: str = "UNKNOWN",
        forced_type: TaskType | None = None,
    ) -> WorkItem:
        raw_id = self._extract_value(record, mapping.id_field) or req_id_fallback
        raw_title = self._extract_value(record, mapping.title_field) or f"Work item {raw_id}"
        raw_desc = self._extract_value(record, mapping.description_field) or ""
        raw_type = self._extract_value(record, mapping.type_field)
        return WorkItem(
            id=str(raw_id),
            title=str(raw_title),
            description=str(raw_desc),
            # TAPD's Story.type / Bug.type fields describe a business subtype and
            # are not a reliable discriminator between the two API resources.
            # The caller knows which endpoint produced the record, so prefer it.
            type=forced_type or self._parse_type(None if raw_type is None else str(raw_type)),
            source="tapd",
            metadata=record,
        )

    def _select(self, item_type: str) -> tuple[str, str, TapdFieldMappingConfig]:
        t = (item_type or self.default_item_type or "story").lower()
        if t == "bug":
            return self.bug_latest_endpoint, self.bug_detail_endpoint, self.bug_field_mapping
        return self.latest_endpoint, self.detail_endpoint, self.field_mapping

    # -- Public API ----------------------------------------------------------

    def fetch_latest_by_type(self, limit: int = 10, item_type: str = "story") -> Iterable[WorkItem]:
        if not self.base_url:
            return self._fallback_latest(limit, item_type)

        latest_endpoint, _, mapping = self._select(item_type)
        url = f"{self.base_url}{latest_endpoint}"
        params: dict[str, Any] = {"limit": limit}
        if self.workspace_id:
            params["workspace_id"] = self.workspace_id

        payload = self._request_json(url, params)
        if payload is None:
            detail = f": {self.last_error}" if self.last_error else ""
            raise RuntimeError(
                f"TAPD request failed for {item_type} using auth_mode={self.auth_mode}{detail}; "
                "refusing to create placeholder work items"
            )

        records = self._extract_value(payload, mapping.list_path)
        if not isinstance(records, list):
            self.stats.inc("mapping")
            logger.warning("TAPD list_path=%s did not yield a list", mapping.list_path)
            return self._fallback_latest(limit, item_type)

        endpoint_type = TaskType.BUG if (item_type or "").lower() == "bug" else TaskType.REQUIREMENT
        items = [
            self._build_item(r, mapping=mapping, forced_type=endpoint_type)
            for r in records
            if isinstance(r, dict)
        ]
        logger.info("Fetched %d %s items from TAPD", len(items), item_type)
        return items

    def fetch_latest_all(self, limit: int = 10) -> Iterable[WorkItem]:
        half = max(1, limit // 2)
        stories = list(self.fetch_latest_by_type(limit=half, item_type="story"))
        bugs = list(self.fetch_latest_by_type(limit=max(1, limit - half), item_type="bug"))
        return (stories + bugs)[:limit]

    def fetch_latest(self, limit: int = 10) -> Iterable[WorkItem]:
        return self.fetch_latest_by_type(limit=limit, item_type=self.default_item_type)

    def get_by_id_with_type(self, req_id: str, item_type: str = "story") -> WorkItem:
        if not self.base_url:
            return self._fallback_item(req_id, item_type)

        _, detail_endpoint, mapping = self._select(item_type)
        params: dict[str, Any] = {}
        if detail_endpoint.endswith("/{id}") and "api.tapd.cn" in self.base_url:
            endpoint = detail_endpoint[:-5]
            params["id"] = req_id
        else:
            endpoint = detail_endpoint.replace("{id}", req_id)
            if "{id}" not in detail_endpoint:
                params["id"] = req_id
        url = f"{self.base_url}{endpoint}"
        if self.workspace_id:
            params["workspace_id"] = self.workspace_id

        payload = self._request_json(url, params)
        if payload is None:
            detail = f": {self.last_error}" if self.last_error else ""
            raise RuntimeError(
                f"TAPD request failed for {item_type} {req_id} using auth_mode={self.auth_mode}{detail}"
            )

        record = self._extract_value(payload, mapping.detail_path)
        if isinstance(record, list):
            record = record[0] if record else {}

        if not isinstance(record, dict):
            record = payload if isinstance(payload, dict) else {}
            self.stats.inc("mapping")

        endpoint_type = TaskType.BUG if (item_type or "").lower() == "bug" else TaskType.REQUIREMENT
        return self._build_item(
            record,
            mapping=mapping,
            req_id_fallback=req_id,
            forced_type=endpoint_type,
        )

    def get_by_id(self, req_id: str) -> WorkItem:
        return self.get_by_id_with_type(req_id=req_id, item_type=self.default_item_type)

    # -- Fallbacks -----------------------------------------------------------

    def _fallback_item(self, req_id: str, item_type: str = "story", reason: str = "placeholder") -> WorkItem:
        return WorkItem(
            id=req_id,
            title=f"Work item {req_id}",
            description=f"Fetched from TAPD ({reason}).",
            type=TaskType.BUG if (item_type or "").lower() == "bug" else TaskType.REQUIREMENT,
            source="tapd",
        )

    def _fallback_latest(self, limit: int, item_type: str = "story") -> list[WorkItem]:
        t = (item_type or "story").lower()
        return [
            WorkItem(
                id=f"TAPD-{1000 + i}",
                title=f"Sample {t} {i}",
                description=f"Auto generated sample {t} from TAPD connector.",
                type=TaskType.BUG if t == "bug" else TaskType.REQUIREMENT,
                source="tapd",
            )
            for i in range(min(limit, 5))
        ]
