#!/usr/bin/env python3
"""Small OAuth + Streamable HTTP client for Oda's hosted MCP server.

The browser never receives OAuth credentials or a generic MCP proxy.  This
module exposes only the Oda operations selected by the Portal API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


MCP_URL = "https://oda.com/mcp"
REGISTRATION_URL = "https://oda.com/o/register/"
AUTHORIZATION_URL = "https://oda.com/o/authorize/"
TOKEN_URL = "https://oda.com/o/token/"
REVOCATION_URL = "https://oda.com/o/revoke_token/"
MCP_PROTOCOL_VERSION = "2025-06-18"


class OdaValidationError(ValueError):
    """The local request is invalid."""


class OdaAuthRequired(RuntimeError):
    """The Oda account needs to be connected again."""


class OdaUnavailable(RuntimeError):
    """Oda or its MCP service is temporarily unavailable."""


class _HttpError(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


def _url_token(size: int = 48) -> str:
    return secrets.token_urlsafe(size)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _json_body(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class OdaMcpClient:
    """Persistent Oda OAuth client with a narrow, serialized MCP session."""

    def __init__(
        self,
        callback_url: str,
        credentials_path: Path | None = None,
        *,
        timeout: int = 25,
    ):
        if not callback_url.startswith("http://") and not callback_url.startswith("https://"):
            raise ValueError("Oda callback URL must be HTTP(S).")
        self.callback_url = callback_url
        self.credentials_path = credentials_path or Path(
            os.environ.get(
                "FAMILYBOT_ODA_CREDENTIALS",
                str(Path.home() / ".openclaw/credentials/oda-mcp.json"),
            )
        ).expanduser()
        self.timeout = timeout
        self._pending: dict[str, dict[str, Any]] = {}
        self._session_id: str | None = None
        self._request_id = 0
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.credentials_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, value: dict[str, Any]) -> None:
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.credentials_path.parent, 0o700)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".oda-mcp-", dir=str(self.credentials_path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.credentials_path)
            os.chmod(self.credentials_path, 0o600)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        json_value: Any | None = None,
        form: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, str], bytes]:
        request_headers = {"User-Agent": "FamilyBot-Portal/1.0"}
        request_headers.update(headers or {})
        body = None
        if json_value is not None:
            body = _json_body(json_value)
            request_headers["Content-Type"] = "application/json"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return {key.lower(): value for key, value in response.headers.items()}, response.read()
        except urllib.error.HTTPError as exc:
            # Provider bodies can contain account or protocol details. Never put
            # them in the exception shown by the Portal or its logs.
            exc.read()
            raise _HttpError(exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OdaUnavailable("Oda svarer ikke akkurat nå. Prøv igjen om litt.") from exc

    @staticmethod
    def _decode_json(body: bytes) -> dict[str, Any]:
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OdaUnavailable("Oda svarte i et ukjent format.") from exc
        if not isinstance(value, dict):
            raise OdaUnavailable("Oda svarte i et ukjent format.")
        return value

    def status(self) -> dict[str, Any]:
        credentials = self._load()
        return {
            "connected": bool(credentials.get("access_token") or credentials.get("refresh_token")),
            "client_registered": bool(credentials.get("client_id")),
            "server_url": MCP_URL,
            "checkout_url": "https://oda.com/",
            "credentials_local": True,
        }

    def _register_client(self) -> dict[str, Any]:
        registration = {
            "client_name": "FamilyBot Portal",
            "redirect_uris": [self.callback_url],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": "mcp",
        }
        try:
            _, body = self._request(REGISTRATION_URL, method="POST", json_value=registration)
        except _HttpError as exc:
            raise OdaUnavailable("Oda kunne ikke opprette en sikker tilkobling.") from exc
        value = self._decode_json(body)
        if not isinstance(value.get("client_id"), str):
            raise OdaUnavailable("Oda returnerte ingen klientidentitet.")
        credentials = self._load()
        credentials.update({
            key: value[key]
            for key in ("client_id", "client_secret", "client_id_issued_at", "client_secret_expires_at")
            if key in value
        })
        credentials["redirect_uri"] = self.callback_url
        self._save(credentials)
        return credentials

    def begin_authorization(self, portal_origin: str) -> str:
        if not portal_origin.startswith("http://") and not portal_origin.startswith("https://"):
            raise OdaValidationError("Ugyldig portaladresse.")
        with self._lock:
            credentials = self._load()
            if not credentials.get("client_id") or credentials.get("redirect_uri") != self.callback_url:
                credentials = self._register_client()
            verifier = _url_token(64)
            state = _url_token(40)
            self._pending = {
                state: {
                    "verifier": verifier,
                    "created_at": time.time(),
                    "portal_origin": portal_origin.rstrip("/"),
                }
            }
            query = urllib.parse.urlencode({
                "response_type": "code",
                "client_id": credentials["client_id"],
                "redirect_uri": self.callback_url,
                "scope": "mcp",
                "state": state,
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
                "resource": MCP_URL,
            })
            return f"{AUTHORIZATION_URL}?{query}"

    def finish_authorization(self, query: dict[str, list[str]]) -> str:
        state = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]
        provider_error = (query.get("error") or [""])[0]
        with self._lock:
            pending = self._pending.pop(state, None)
            if not pending or time.time() - float(pending["created_at"]) > 600:
                raise OdaAuthRequired("Tilkoblingen er utløpt. Start på nytt fra Oda-fanen.")
            if provider_error:
                raise OdaAuthRequired("Oda-tilkoblingen ble ikke godkjent.")
            if not code:
                raise OdaAuthRequired("Oda returnerte ingen godkjenningskode.")
            credentials = self._load()
            token_form = {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": credentials.get("client_id", ""),
                "redirect_uri": self.callback_url,
                "code_verifier": pending["verifier"],
                "resource": MCP_URL,
            }
            try:
                _, body = self._request(TOKEN_URL, method="POST", form=token_form)
            except _HttpError as exc:
                raise OdaAuthRequired("Oda-tilkoblingen kunne ikke fullføres.") from exc
            tokens = self._decode_json(body)
            self._store_tokens(credentials, tokens)
            self._session_id = None
            return str(pending["portal_origin"])

    def _store_tokens(self, credentials: dict[str, Any], tokens: dict[str, Any]) -> None:
        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OdaAuthRequired("Oda returnerte ingen tilgang.")
        credentials["access_token"] = access_token
        if isinstance(tokens.get("refresh_token"), str):
            credentials["refresh_token"] = tokens["refresh_token"]
        credentials["token_type"] = tokens.get("token_type", "Bearer")
        credentials["scope"] = tokens.get("scope", "mcp")
        credentials["expires_at"] = time.time() + max(60, int(tokens.get("expires_in", 3600)))
        self._save(credentials)

    def _refresh(self, credentials: dict[str, Any]) -> dict[str, Any]:
        refresh_token = credentials.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise OdaAuthRequired("Koble Oda-kontoen til på nytt.")
        form = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": credentials.get("client_id", ""),
            "scope": "mcp",
            "resource": MCP_URL,
        }
        try:
            _, body = self._request(TOKEN_URL, method="POST", form=form)
        except _HttpError as exc:
            if exc.status in {400, 401, 403}:
                raise OdaAuthRequired("Oda-tilkoblingen er utløpt. Koble til på nytt.") from exc
            raise OdaUnavailable("Oda kunne ikke fornye tilkoblingen.") from exc
        tokens = self._decode_json(body)
        self._store_tokens(credentials, tokens)
        return self._load()

    def _access_token(self, *, force_refresh: bool = False) -> str:
        credentials = self._load()
        if force_refresh or float(credentials.get("expires_at") or 0) <= time.time() + 60:
            credentials = self._refresh(credentials)
        token = credentials.get("access_token")
        if not isinstance(token, str) or not token:
            raise OdaAuthRequired("Koble Oda-kontoen til først.")
        return token

    @staticmethod
    def _decode_mcp(body: bytes, content_type: str) -> dict[str, Any]:
        if not body:
            return {}
        if "text/event-stream" in content_type:
            events = []
            for line in body.decode("utf-8", errors="replace").splitlines():
                if line.startswith("data:"):
                    try:
                        events.append(json.loads(line[5:].strip()))
                    except json.JSONDecodeError:
                        continue
            value = next((event for event in reversed(events) if isinstance(event, dict)), None)
        else:
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OdaUnavailable("Oda svarte i et ukjent MCP-format.") from exc
        if not isinstance(value, dict):
            raise OdaUnavailable("Oda svarte i et ukjent MCP-format.")
        return value

    def _mcp_request(self, payload: dict[str, Any], *, retry_auth: bool = True) -> tuple[dict[str, Any], dict[str, str]]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._access_token()}",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            response_headers, body = self._request(
                MCP_URL, method="POST", json_value=payload, headers=headers
            )
        except _HttpError as exc:
            if exc.status == 401 and retry_auth:
                self._access_token(force_refresh=True)
                self._session_id = None
                return self._mcp_request(payload, retry_auth=False)
            if exc.status in {401, 403}:
                raise OdaAuthRequired("Oda-tilkoblingen må godkjennes på nytt.") from exc
            raise OdaUnavailable("Oda MCP svarer ikke akkurat nå.") from exc
        value = self._decode_mcp(body, response_headers.get("content-type", ""))
        if isinstance(value.get("error"), dict):
            raise OdaUnavailable("Oda kunne ikke utføre handlingen.")
        return value, response_headers

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _initialize(self) -> None:
        if self._session_id:
            return
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "familybot-portal", "version": "1.0.0"},
            },
        }
        value, headers = self._mcp_request(payload)
        if not isinstance(value.get("result"), dict):
            raise OdaUnavailable("Oda MCP kunne ikke startes.")
        self._session_id = headers.get("mcp-session-id")
        self._mcp_request({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._initialize()
            payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
            value, _ = self._mcp_request(payload)
            result = value.get("result")
            if not isinstance(result, dict):
                raise OdaUnavailable("Oda returnerte ikke noe resultat.")
            if result.get("isError"):
                raise OdaUnavailable("Oda kunne ikke utføre handlingen.")
            structured = result.get("structuredContent")
            if isinstance(structured, dict):
                return structured
            for block in result.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    try:
                        parsed = json.loads(str(block.get("text", "")))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
            raise OdaUnavailable("Oda returnerte et ukjent resultatformat.")

    def search_products(self, query: str, page: Any = 1) -> dict[str, Any]:
        query = str(query or "").strip()
        if not 2 <= len(query) <= 120:
            raise OdaValidationError("Søket må være mellom 2 og 120 tegn.")
        try:
            page = int(page)
        except (TypeError, ValueError) as exc:
            raise OdaValidationError("Ugyldig resultatside.") from exc
        if not 1 <= page <= 50:
            raise OdaValidationError("Ugyldig resultatside.")
        return self.call_tool("product_search", {
            "queries": [query], "page": page, "size": 12,
            "intent": "wants to find groceries for the household",
        })

    def suggestions(self, kind: str = "likely") -> dict[str, Any]:
        tools = {"likely": "likely_to_buy", "unique": "unique_for_you"}
        if kind not in tools:
            raise OdaValidationError("Ugyldig forslagstype.")
        return self.call_tool(tools[kind], {
            "intent": "wants grocery suggestions for the household",
        })

    def cart(self) -> dict[str, Any]:
        return self.call_tool("get_cart", {"intent": "wants to review the household cart"})

    def change_product(self, product_id: Any, quantity: Any) -> dict[str, Any]:
        try:
            product_id = int(product_id)
            quantity = int(quantity)
        except (TypeError, ValueError) as exc:
            raise OdaValidationError("Ugyldig vare eller antall.") from exc
        if product_id <= 0 or quantity == 0 or not -20 <= quantity <= 20:
            raise OdaValidationError("Ugyldig vare eller antall.")
        return self.call_tool("manipulate_cart", {
            "operations": [{"productId": product_id, "quantity": quantity}],
            "intent": "wants to update the household grocery cart",
        })

    def clear_cart(self) -> dict[str, Any]:
        return self.call_tool("clear_cart", {"intent": "wants to empty the household grocery cart"})

    def disconnect(self) -> None:
        with self._lock:
            credentials = self._load()
            token = credentials.get("refresh_token") or credentials.get("access_token")
            if token:
                try:
                    self._request(REVOCATION_URL, method="POST", form={
                        "token": token,
                        "client_id": credentials.get("client_id", ""),
                    })
                except _HttpError as exc:
                    raise OdaUnavailable("Oda-tilgangen kunne ikke trekkes tilbake.") from exc
            for key in ("access_token", "refresh_token", "token_type", "scope", "expires_at"):
                credentials.pop(key, None)
            self._save(credentials)
            self._session_id = None
