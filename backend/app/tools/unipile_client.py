"""Unipile LinkedIn client.

Provides:
- read-only health probes to validate the connected LinkedIn account
- outbound LinkedIn DM support for the deployment agent

The health probe uses GET-only calls so it can verify connectivity without
sending any messages or connection requests.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence, TypeAlias
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 20.0
_LINKEDIN_IDENTIFIER_RE = re.compile(r"linkedin\.com/(?:in|company)/([^/?#]+)", re.IGNORECASE)
MultipartFormPart: TypeAlias = (
    tuple[str, tuple[None, str]] | tuple[str, tuple[str, bytes, str]]
)


class LinkedInConnectionRequiredError(Exception):
    """Raised when a LinkedIn message send fails because the recipient is not connected.

    Carries the provider_id and public_identifier so the caller can send a
    connection request without a second profile lookup.
    """

    def __init__(self, provider_id: str, public_identifier: str) -> None:
        self.provider_id = provider_id
        self.public_identifier = public_identifier
        super().__init__(
            f"Not connected to LinkedIn user '{public_identifier}' (provider_id={provider_id})"
        )


def get_unipile_config_errors(require_account: bool = True) -> list[str]:
    """Return configuration issues that would block Unipile usage."""
    errors: list[str] = []
    if not settings.UNIPILE_DSN:
        errors.append("UNIPILE_DSN is not set — cannot reach the Unipile API.")
    if not settings.UNIPILE_API_KEY:
        errors.append("UNIPILE_API_KEY is not set — cannot authenticate to Unipile.")
    if require_account and not settings.UNIPILE_LINKEDIN_ACCOUNT_ID:
        errors.append(
            "UNIPILE_LINKEDIN_ACCOUNT_ID is not set — cannot target the connected LinkedIn account."
        )
    return errors


def get_unipile_base_url() -> str:
    """Return the Unipile DSN as a usable base URL."""
    dsn = (settings.UNIPILE_DSN or "").strip()
    if not dsn:
        raise ValueError("UNIPILE_DSN is not set.")
    if dsn.startswith(("http://", "https://")):
        return dsn.rstrip("/")
    return f"https://{dsn.rstrip('/')}"


def extract_linkedin_identifier(profile_reference: str) -> str:
    """Extract a public identifier or provider id from a LinkedIn URL/reference."""
    reference = (profile_reference or "").strip()
    if not reference:
        raise ValueError("LinkedIn profile reference is empty.")

    match = _LINKEDIN_IDENTIFIER_RE.search(reference)
    if match:
        return match.group(1)

    cleaned = reference.rstrip("/").split("?", 1)[0].split("#", 1)[0]
    return cleaned.rsplit("/", 1)[-1]


def _build_headers() -> dict[str, str]:
    if not settings.UNIPILE_API_KEY:
        raise ValueError("UNIPILE_API_KEY is not set.")
    return {
        "X-API-KEY": settings.UNIPILE_API_KEY,
        "accept": "application/json",
    }


async def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    files: Sequence[MultipartFormPart] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform a Unipile API request and return the parsed JSON body."""
    async with httpx.AsyncClient(
        base_url=get_unipile_base_url(),
        headers=_build_headers(),
        timeout=_TIMEOUT_SECONDS,
    ) as client:
        response = await client.request(
            method, path, params=params, files=files, json=json_body
        )
        if response.is_error:
            logger.error(
                "Unipile API %s %s → HTTP %s: %s",
                method,
                path,
                response.status_code,
                response.text[:300],
            )
        response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


async def list_accounts() -> dict[str, Any]:
    return await _request("GET", "/api/v1/accounts")


async def get_account(account_id: str) -> dict[str, Any]:
    return await _request("GET", f"/api/v1/accounts/{quote(account_id, safe='')}")


async def get_current_user(account_id: str) -> dict[str, Any]:
    return await _request("GET", "/api/v1/users/me", params={"account_id": account_id})


async def get_post(post_id: str, account_id: str) -> dict[str, Any]:
    return await _request(
        "GET",
        f"/api/v1/posts/{quote(post_id, safe='')}",
        params={"account_id": account_id},
    )


async def get_user_profile(identifier: str, account_id: str) -> dict[str, Any]:
    return await _request(
        "GET",
        f"/api/v1/users/{quote(identifier, safe='')}",
        params={"account_id": account_id},
    )


async def search_linkedin_people(
    keyword: str,
    account_id: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search LinkedIn for people by name/keyword using the connected Unipile account.

    Returns a list of profile dicts with keys: name, public_identifier, linkedin_url,
    occupation, headline, location, provider_id.
    Falls back to an empty list on any error so the caller can try other strategies.
    """
    try:
        data = await _request(
            "GET",
            "/api/v1/users/search",
            params={"account_id": account_id, "keyword": keyword, "limit": limit},
        )
    except Exception as exc:
        logger.warning("search_linkedin_people: /users/search failed (%s), trying /users", exc)
        try:
            data = await _request(
                "GET",
                "/api/v1/users",
                params={"account_id": account_id, "keyword": keyword, "limit": limit},
            )
        except Exception as exc2:
            logger.warning("search_linkedin_people: both search endpoints failed: %s", exc2)
            return []

    items = data.get("items") or data.get("results") or []
    if not isinstance(items, list):
        return []

    profiles = []
    for item in items:
        public_id = item.get("public_identifier") or item.get("publicIdentifier") or ""
        profiles.append({
            "name": " ".join(
                p for p in [item.get("first_name"), item.get("last_name")] if p
            ).strip() or item.get("name") or item.get("full_name") or "",
            "public_identifier": public_id,
            "linkedin_url": f"https://www.linkedin.com/in/{public_id}" if public_id else "",
            "occupation": item.get("occupation") or item.get("headline") or "",
            "location": item.get("location") or "",
            "provider_id": item.get("provider_id") or item.get("providerId") or "",
        })
    return profiles


async def list_chats(account_id: str, limit: int = 1) -> dict[str, Any]:
    return await _request("GET", "/api/v1/chats", params={"account_id": account_id, "limit": limit})


async def list_messages(account_id: str, limit: int = 1) -> dict[str, Any]:
    return await _request(
        "GET",
        "/api/v1/messages",
        params={"account_id": account_id, "limit": limit},
    )


def _extract_message_id(payload: dict[str, Any]) -> str | None:
    """Extract the provider message id from a Unipile send response."""
    if not payload:
        return None

    object_type = payload.get("object")
    if object_type == "Message":
        return payload.get("message_id") or payload.get("provider_id") or payload.get("id")

    last_message = payload.get("last_message") or {}
    return last_message.get("message_id") or last_message.get("provider_id")


def _extract_post_social_id(payload: dict[str, Any]) -> str | None:
    """Extract Unipile's stable LinkedIn social_id from a post payload."""
    if not payload:
        return None
    return (
        payload.get("social_id")
        or payload.get("socialId")
        or payload.get("provider_id")
        or payload.get("providerId")
    )


async def _resolve_post_social_id(post_id: str, account_id: str) -> str:
    """Resolve a LinkedIn post id to its social_id when needed."""
    candidate = (post_id or "").strip()
    if not candidate:
        return candidate
    if candidate.startswith("urn:li:"):
        return candidate

    try:
        post = await get_post(candidate, account_id)
    except Exception as exc:
        logger.warning("_resolve_post_social_id: failed for post=%s: %s", candidate, exc)
        return candidate

    return _extract_post_social_id(post) or candidate


async def send_linkedin_message(
    recipient_profile_reference: str,
    message: str,
    *,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Send a LinkedIn DM through Unipile.

    This is only called from a confirmed deployment path. The health probe uses
    GET-only endpoints and never calls this function.
    """
    config_errors = get_unipile_config_errors(require_account=True)
    if config_errors:
        raise ValueError(" | ".join(config_errors))

    resolved_account_id = account_id or settings.UNIPILE_LINKEDIN_ACCOUNT_ID
    identifier = extract_linkedin_identifier(recipient_profile_reference)
    profile = await get_user_profile(identifier, resolved_account_id)
    provider_id = profile.get("provider_id")
    if not provider_id:
        raise ValueError(
            f"Unipile did not return a provider_id for LinkedIn identifier '{identifier}'."
        )

    files = [
        ("account_id", (None, resolved_account_id)),
        ("text", (None, message)),
        ("attendees_ids", (None, provider_id)),
    ]
    try:
        chat = await _request("POST", "/api/v1/chats", files=files)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise LinkedInConnectionRequiredError(
                provider_id=provider_id,
                public_identifier=profile.get("public_identifier") or identifier,
            ) from exc
        raise

    provider_message_id = _extract_message_id(chat)
    if not provider_message_id and chat.get("id"):
        messages = await _request(
            "GET",
            f"/api/v1/chats/{quote(chat['id'], safe='')}/messages",
            params={"limit": 1},
        )
        items = messages.get("items") or []
        if items:
            provider_message_id = items[0].get("message_id") or items[0].get("provider_id")

    if not provider_message_id:
        # Message was sent (no HTTP error) but Unipile didn't return a message ID.
        # Fall back to the chat ID so the deployment record is still marked sent.
        provider_message_id = chat.get("id") or f"linkedin-{provider_id[:12]}"
        logger.warning(
            "send_linkedin_message: no message_id in response — using fallback id=%s",
            provider_message_id,
        )

    return {
        "provider_message_id": provider_message_id,
        "chat_id": chat.get("id"),
        "recipient_provider_id": provider_id,
        "recipient_public_identifier": profile.get("public_identifier") or identifier,
    }


async def send_connection_request(
    provider_id: str,
    *,
    account_id: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Send a LinkedIn connection request to a user identified by their provider_id."""
    resolved_account_id = account_id or settings.UNIPILE_LINKEDIN_ACCOUNT_ID
    if not resolved_account_id:
        raise ValueError("UNIPILE_LINKEDIN_ACCOUNT_ID is not set.")

    body: dict[str, Any] = {
        "account_id": resolved_account_id,
        "provider_id": provider_id,
    }
    if message:
        body["message"] = message

    return await _request("POST", "/api/v1/users/invite", json_body=body)


async def send_linkedin_message_direct(
    provider_id: str,
    message: str,
    *,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Send a LinkedIn DM directly using a known provider_id (no profile lookup).

    Used by the webhook handler to deliver messages that were deferred
    pending a connection request acceptance.
    """
    resolved_account_id = account_id or settings.UNIPILE_LINKEDIN_ACCOUNT_ID
    if not resolved_account_id:
        raise ValueError("UNIPILE_LINKEDIN_ACCOUNT_ID is not set.")

    files = [
        ("account_id", (None, resolved_account_id)),
        ("text", (None, message)),
        ("attendees_ids", (None, provider_id)),
    ]
    chat = await _request("POST", "/api/v1/chats", files=files)

    provider_message_id = _extract_message_id(chat)
    if not provider_message_id and chat.get("id"):
        messages = await _request(
            "GET",
            f"/api/v1/chats/{quote(chat['id'], safe='')}/messages",
            params={"limit": 1},
        )
        items = messages.get("items") or []
        if items:
            provider_message_id = items[0].get("message_id") or items[0].get("provider_id")

    if not provider_message_id:
        provider_message_id = chat.get("id") or f"linkedin-{provider_id[:12]}"
        logger.warning(
            "send_linkedin_message_direct: no message_id in response — using fallback id=%s",
            provider_message_id,
        )

    return {"provider_message_id": provider_message_id, "chat_id": chat.get("id")}


async def create_linkedin_post(
    text: str,
    *,
    account_id: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> dict[str, Any]:
    """Publish a text post to the connected LinkedIn account via Unipile.

    Returns the Unipile response dict which includes 'id' or 'provider_id' for the post.
    """
    config_errors = get_unipile_config_errors(require_account=True)
    if config_errors:
        raise ValueError(" | ".join(config_errors))

    resolved_account_id = account_id or settings.UNIPILE_LINKEDIN_ACCOUNT_ID
    files: list[MultipartFormPart] = [
        ("account_id", (None, resolved_account_id)),
        ("text", (None, text)),
    ]
    for filename, content, content_type in attachments or []:
        files.append(("attachments", (filename, content, content_type)))
    response = await _request(
        "POST",
        "/api/v1/posts",
        files=files,
    )
    created_post_id = (
        response.get("post_id") or response.get("id") or response.get("provider_id") or ""
    )
    if created_post_id:
        response["social_id"] = await _resolve_post_social_id(created_post_id, resolved_account_id)
    return response


async def list_post_comments(
    post_provider_id: str,
    *,
    account_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch comments on a published LinkedIn post.

    Returns a list of comment dicts (id, author, text/content). Returns an empty
    list on any error so callers don't need to handle exceptions.
    """
    resolved_account_id = account_id or settings.UNIPILE_LINKEDIN_ACCOUNT_ID
    resolved_post_id = await _resolve_post_social_id(post_provider_id, resolved_account_id)
    try:
        data = await _request(
            "GET",
            f"/api/v1/posts/{quote(resolved_post_id, safe='')}/comments",
            params={"account_id": resolved_account_id, "limit": limit},
        )
    except Exception as exc:
        logger.warning(
            "list_post_comments: failed for post=%s resolved_post=%s: %s",
            post_provider_id,
            resolved_post_id,
            exc,
        )
        return []

    items = data.get("items") or data.get("data") or []
    return items if isinstance(items, list) else []


async def reply_to_post_comment(
    post_provider_id: str,
    comment_provider_id: str,
    text: str,
    *,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Post a reply to a comment on a LinkedIn post."""
    resolved_account_id = account_id or settings.UNIPILE_LINKEDIN_ACCOUNT_ID
    resolved_post_id = await _resolve_post_social_id(post_provider_id, resolved_account_id)
    return await _request(
        "POST",
        f"/api/v1/posts/{quote(resolved_post_id, safe='')}/comments",
        json_body={
            "account_id": resolved_account_id,
            "text": text,
            "parent_comment_id": comment_provider_id,
        },
    )


async def get_unipile_connection_health(account_id: str | None = None) -> dict[str, Any]:
    """Run a read-only Unipile probe for the configured LinkedIn account."""
    config_errors = get_unipile_config_errors(require_account=False)
    if config_errors:
        return {
            "status": "misconfigured",
            "configured": False,
            "connected": False,
            "errors": config_errors,
        }

    try:
        accounts_payload = await list_accounts()
        accounts = accounts_payload.get("items") or []
        linkedin_accounts = [account for account in accounts if account.get("type") == "LINKEDIN"]

        desired_account_id = account_id or settings.UNIPILE_LINKEDIN_ACCOUNT_ID or None
        selected_account = None
        if desired_account_id:
            selected_account = next(
                (account for account in linkedin_accounts if account.get("id") == desired_account_id),
                None,
            )
            if selected_account is None:
                return {
                    "status": "error",
                    "configured": True,
                    "connected": False,
                    "errors": [
                        f"Configured LinkedIn account '{desired_account_id}' was not returned by Unipile."
                    ],
                    "linkedin_account_count": len(linkedin_accounts),
                }
        elif linkedin_accounts:
            selected_account = linkedin_accounts[0]
        else:
            return {
                "status": "error",
                "configured": True,
                "connected": False,
                "errors": ["No LinkedIn accounts are connected in Unipile."],
                "linkedin_account_count": 0,
            }

        resolved_account_id = selected_account["id"]
        account = await get_account(resolved_account_id)
        owner = await get_current_user(resolved_account_id)
        chats = await list_chats(resolved_account_id, limit=1)
        messages = await list_messages(resolved_account_id, limit=1)

        source_statuses = [
            source.get("status")
            for source in (account.get("sources") or [])
            if source.get("status")
        ]
        connected = bool(source_statuses) and all(status == "OK" for status in source_statuses)
        status = "connected" if connected else "degraded"

        return {
            "status": status,
            "configured": True,
            "connected": connected,
            "base_url": get_unipile_base_url(),
            "account_id": resolved_account_id,
            "account_name": account.get("name") or selected_account.get("name"),
            "account_type": account.get("type") or selected_account.get("type"),
            "source_statuses": source_statuses,
            "owner": {
                "public_identifier": owner.get("public_identifier"),
                "name": " ".join(
                    part for part in [owner.get("first_name"), owner.get("last_name")] if part
                ).strip(),
                "occupation": owner.get("occupation"),
                "location": owner.get("location"),
            },
            "read_checks": {
                "accounts": "ok",
                "account": "ok",
                "users_me": "ok",
                "chats": {
                    "status": "ok",
                    "count": len(chats.get("items") or []),
                },
                "messages": {
                    "status": "ok",
                    "count": len(messages.get("items") or []),
                },
            },
            "linkedin_account_count": len(linkedin_accounts),
        }
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Unipile health probe failed with HTTP %s",
            exc.response.status_code,
        )
        return {
            "status": "error",
            "configured": True,
            "connected": False,
            "errors": [f"Unipile API returned HTTP {exc.response.status_code}."],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unipile health probe failed: %s", exc)
        return {
            "status": "error",
            "configured": True,
            "connected": False,
            "errors": [str(exc)],
        }
