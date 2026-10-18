"""Discord transport for the org bot: an alternative to the HTTP org API.

The org bot posts one JSON request into a single private channel and reads one
JSON reply from the same channel. Nothing here re-implements the org rules: name
resolution and slot restrictions come from OrgReserves in org_api.py, and
reserve writes go through the bot's own org_add_reserve / org_remove_reserve
callbacks, which use the same add_reservations_bulk / remove_reservation that
`v!r add` and `v!r remove` use. A user is never simulated typing a command.

Request, posted by the org bot (ORG_BOT_USER_ID) in the configured scope:

    {"type": "validate", "request_id": "abc", "pokemon": "pikachu", "slot": null}
    {"type": "add",      "request_id": "abc", "pokemon": "pikachu",
     "userId": "1234", "slot": null}
    {"type": "remove",   "request_id": "abc", "pokemon": "pikachu",
     "userId": "1234"}
    {"type": "list",     "request_id": "abc"}

Reply, sent by the bot in the channel the request arrived in:

    {"request_id": "abc", "success": true,  "result": {...}}
    {"request_id": "abc", "success": false, "error": "...", "status": 404}

Scope is configurable, so the transport can serve one channel or a whole server:

    ORG_DISCORD_RPC_GUILD_ID    the whole server: any channel in that guild
    ORG_DISCORD_RPC_CHANNEL_ID  a single channel (also usable inside a guild)
    both                        that channel, inside that guild
    neither                     the transport is disabled

In a guild, a message from the org bot that is not a JSON request is ignored
silently: a busy server must not get an error reply for every stray message.
In a single channel the old strict behaviour stays, where any content gets an
answer, because the channel is private and that helps while integrating.

Unset ORG_DISCORD_RPC_CHANNEL_ID, ORG_DISCORD_RPC_GUILD_ID or
ORG_BOT_USER_ID disables the transport completely: no listener, no replies, and
on_message behaves exactly as before.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

import discord

from org_api import OrgError, OrgReserves

logger = logging.getLogger("vivillon_naming.org_rpc")

CHANNEL_ENV = "ORG_DISCORD_RPC_CHANNEL_ID"
GUILD_ENV = "ORG_DISCORD_RPC_GUILD_ID"
USER_ENV = "ORG_BOT_USER_ID"
DEDUPE_FILE_ENV = "ORG_RPC_DEDUPE_FILE"
DEFAULT_DEDUPE_FILE = "org_rpc_dedupe.json"

REQUEST_TYPES = frozenset({"add", "remove", "list", "validate"})
DEFAULT_HANDLE_TIMEOUT = 20.0
DEFAULT_SEND_TIMEOUT = 10.0
MAX_REMEMBERED_IDS = 2000


def _parse_user_id(value: Any) -> int:
    if not isinstance(value, str) or not value.isdigit():
        raise OrgError(400, "Invalid request: userId must be a Discord ID string")
    return int(value)


def _parse_pokemon(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OrgError(400, "Invalid request: pokemon must be a string")
    return value


def _parse_slot(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OrgError(400, "Invalid request: slot must be a string")
    return value


def _parse_request_id(value: Any) -> str:
    if isinstance(value, bool):
        raise OrgError(400, "Invalid request: request_id must be a string")
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str) or not value.strip():
        raise OrgError(400, "Invalid request: request_id must be a string")
    return value.strip()


class OrgRpc:
    """A JSON request/reply transport over Discord, in one channel or a guild."""

    def __init__(
        self,
        channel_id: int | None,
        guild_id: int | None,
        org_bot_user_id: int,
        org: OrgReserves,
        add_to_vivillon: Callable[[str, int], None],
        remove_from_vivillon: Callable[[str, int], bool],
        dedupe_path: Path,
        handle_timeout: float = DEFAULT_HANDLE_TIMEOUT,
        send_timeout: float = DEFAULT_SEND_TIMEOUT,
    ) -> None:
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.org_bot_user_id = org_bot_user_id
        self.org = org
        self.add_to_vivillon = add_to_vivillon
        self.remove_from_vivillon = remove_from_vivillon
        self.dedupe_path = dedupe_path
        self.handle_timeout = handle_timeout
        self.send_timeout = send_timeout
        self.seen_message_ids: list[int] = []
        self.seen_request_ids: list[str] = []
        self._load_dedupe()
        logger.info(
            "Discord org transport enabled: %s, org bot %s",
            self.scope_description(),
            org_bot_user_id,
        )

    def scope_description(self) -> str:
        if self.channel_id is not None and self.guild_id is not None:
            return f"channel {self.channel_id} in guild {self.guild_id}"
        if self.guild_id is not None:
            return f"every channel in guild {self.guild_id}"
        return f"channel {self.channel_id}"

    @property
    def guild_wide(self) -> bool:
        """True when the transport listens in a whole server, not one channel."""
        return self.guild_id is not None

    # -- dedupe ---------------------------------------------------------------

    def _load_dedupe(self) -> None:
        try:
            raw = json.loads(self.dedupe_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # No file yet, or an unreadable one: start clean rather than crash.
            return
        if not isinstance(raw, dict):
            return
        messages = raw.get("message_ids")
        if isinstance(messages, list):
            self.seen_message_ids = [int(value) for value in messages if str(value).isdigit()]
        requests = raw.get("request_ids")
        if isinstance(requests, list):
            self.seen_request_ids = [str(value) for value in requests]

    def _save_dedupe(self) -> None:
        del self.seen_message_ids[:-MAX_REMEMBERED_IDS]
        del self.seen_request_ids[:-MAX_REMEMBERED_IDS]
        payload = {
            "message_ids": self.seen_message_ids,
            "request_ids": self.seen_request_ids,
        }
        try:
            self.dedupe_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.dedupe_path.with_name(f"{self.dedupe_path.name}.tmp")
            temporary.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
            temporary.replace(self.dedupe_path)
        except OSError:
            logger.exception("Could not persist org RPC dedupe state")

    def _remember(self, message_id: int, request_id: str | None) -> bool:
        """Record the ids. False means this request was already processed."""
        duplicate = message_id in self.seen_message_ids or (
            request_id is not None and request_id in self.seen_request_ids
        )
        if duplicate:
            return False
        self.seen_message_ids.append(message_id)
        if request_id is not None:
            self.seen_request_ids.append(request_id)
        self._save_dedupe()
        return True

    # -- message entry point -------------------------------------------------

    def matches(self, message: Any) -> bool:
        """True when this message arrived inside the configured scope.

        A channel narrows to that channel, a guild widens to every channel in it,
        and with both set the message has to be in that channel of that guild.
        """
        channel = getattr(message, "channel", None)
        if self.channel_id is not None:
            if getattr(channel, "id", None) != self.channel_id:
                return False
        if self.guild_id is not None:
            guild = getattr(message, "guild", None) or getattr(channel, "guild", None)
            if getattr(guild, "id", None) != self.guild_id:
                return False
        return True

    async def handle_message(self, message: Any) -> bool:
        """Handle one Discord message. True means: it belongs to this transport.

        on_message early-returns on True, so a JSON request is never mistaken for
        a spawn and never reaches the v! commands either.
        """
        if not self.matches(message):
            return False
        author = getattr(message, "author", None)
        author_id = getattr(author, "id", None)
        if author_id != self.org_bot_user_id:
            # Not the org bot. In a guild this is just ordinary traffic, so it is
            # left completely alone (False = not ours). In a single private
            # channel the old behaviour stays: warn, no reply, and swallow it so
            # it can never be read as a spawn.
            if self.guild_id is None:
                logger.warning(
                    "Ignoring org channel message %s from %s: not the org bot (%s)",
                    getattr(message, "id", "?"),
                    author_id,
                    self.org_bot_user_id,
                )
                return True
            return False
        if self.guild_wide and not self._looks_like_request(message):
            # A whole server carries plenty of other messages from this bot; an
            # error reply to each of them would be noise. Not ours, hands off.
            return False
        try:
            await asyncio.wait_for(self._handle_request(message), self.handle_timeout)
        except asyncio.TimeoutError:
            logger.error(
                "Org request %s timed out after %ss",
                getattr(message, "id", "?"),
                self.handle_timeout,
            )
            await self._reply(
                message,
                self._failure(None, f"Timed out after {self.handle_timeout}s", 504),
            )
        return True

    def report_scope(self, guilds: Any) -> None:
        """Log whether this client can actually see the configured scope.

        Called once from on_ready, when the guild list is known. Without it a
        wrong ORG_DISCORD_RPC_GUILD_ID would look identical to a quiet server:
        the transport would simply never fire.
        """
        guild_list = list(guilds)
        guild_ids = [getattr(guild, "id", None) for guild in guild_list]
        if self.guild_id is not None and self.guild_id not in guild_ids:
            logger.error(
                "Discord org transport is set to server %s but this bot is not in it "
                "(it is in %s). Invite it to that server, or every org request will "
                "be missed.",
                self.guild_id,
                guild_ids or "no servers",
            )
            return
        if self.channel_id is not None:
            seen = {
                getattr(channel, "id", None)
                for guild in guild_list
                for channel in getattr(guild, "channels", [])
            }
            if self.channel_id not in seen:
                logger.error(
                    "Discord org transport is set to channel %s but this bot cannot "
                    "see it. Check the ID, or give the bot access to that channel.",
                    self.channel_id,
                )
                return
        logger.info(
            "Discord org transport ready in %s, listening for requests from user %s",
            self.scope_description(),
            self.org_bot_user_id,
        )

    @staticmethod
    def _looks_like_request(message: Any) -> bool:
        """Cheap test: a JSON object carrying type or request_id.

        Used only in guild mode, to tell a request from the org bot's ordinary
        chatter without replying an error to every stray message.
        """
        raw = (getattr(message, "content", "") or "").strip()
        if not raw.startswith("{"):
            return False
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        return "type" in payload or "request_id" in payload

    async def _handle_request(self, message: Any) -> None:
        message_id = getattr(message, "id", None)
        if not isinstance(message_id, int):
            logger.error("Org channel message without a usable id; ignored")
            return
        raw = getattr(message, "content", "") or ""
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._reply(message, self._failure(None, "Invalid JSON payload", 400))
            return
        if not isinstance(payload, dict):
            await self._reply(message, self._failure(None, "Invalid JSON payload", 400))
            return

        request_id = payload.get("request_id")
        if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
            await self._reply(
                message,
                self._failure(None, "Invalid request: request_id must be a string", 400),
            )
            return
        request_id = str(request_id).strip()
        if not request_id:
            await self._reply(
                message,
                self._failure(None, "Invalid request: request_id must be a string", 400),
            )
            return

        if not self._remember(message_id, request_id):
            logger.info("Duplicate org request %s (message %s)", request_id, message_id)
            await self._reply(
                message,
                self._failure(
                    request_id,
                    "Duplicate request: this message id or request_id was already handled",
                    409,
                ),
            )
            return

        request_type = payload.get("type")
        if request_type not in REQUEST_TYPES:
            await self._reply(
                message,
                self._failure(
                    request_id,
                    "Invalid request: type must be one of add, remove, list, validate",
                    400,
                ),
            )
            return

        try:
            result = self._dispatch(request_type, payload)
        except OrgError as error:
            await self._reply(
                message, self._failure(request_id, error.message, error.status)
            )
            return
        except ValueError as error:
            logger.exception("Org storage error while handling %s", request_id)
            await self._reply(message, self._failure(request_id, str(error), 500))
            return
        except Exception:
            logger.exception("Unexpected failure while handling org request %s", request_id)
            await self._reply(
                message, self._failure(request_id, "Internal error", 500)
            )
            return

        await self._reply(
            message, {"request_id": request_id, "success": True, "result": result}
        )
        logger.info("Org %s %s handled", request_type, request_id)

    # -- request handlers ----------------------------------------------------

    def _dispatch(self, request_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one request, reusing OrgReserves and the bot's org callbacks.

        The order of operations mirrors the HTTP handler in org_api.py exactly:
        validate first, then the org list, then Vivillon's own reserves, so both
        transports produce the same state and the same answers.
        """
        if request_type == "list":
            return {"count": len(self.org.entries), "reserves": self.org.entries}

        if request_type == "validate":
            name, all_forms = self.org.validate(
                _parse_pokemon(payload.get("pokemon")),
                _parse_slot(payload.get("slot")),
            )
            return {
                "valid": True,
                "pokemon": f"All {name}" if all_forms else name,
            }

        user_id = _parse_user_id(payload.get("userId"))
        slot = _parse_slot(payload.get("slot"))
        pokemon = _parse_pokemon(payload.get("pokemon"))
        if request_type == "add":
            name, all_forms = self.org.validate(pokemon, slot)
        else:
            name, all_forms = self.org.canonical_name(pokemon)
        stored = f"All {name}" if all_forms else name

        if request_type == "add":
            created = self.org.add(stored, user_id, slot)
            self.add_to_vivillon(stored, user_id)
            changed = created
        else:
            changed = self.org.remove(stored, user_id)
            changed = self.remove_from_vivillon(stored, user_id) or changed
            if not changed:
                raise OrgError(404, f"{stored} is not reserved for that user")

        return {
            "action": request_type,
            "pokemon": stored,
            "userId": str(user_id),
            "slot": slot,
            "changed": changed,
        }

    # -- replies -------------------------------------------------------------

    @staticmethod
    def _failure(request_id: str | None, message: str, status: int) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "success": False,
            "error": message,
            "status": status,
        }

    async def _reply(self, message: Any, payload: dict[str, Any]) -> None:
        """Send the JSON reply back into the org channel.

        A send that fails or hangs cannot answer the caller, so the failure is
        logged with the request id instead of being swallowed.
        """
        channel = getattr(message, "channel", None)
        send = getattr(channel, "send", None)
        if send is None:
            logger.error(
                "Could not reply to org request %s: channel is not sendable",
                payload.get("request_id"),
            )
            return
        try:
            await asyncio.wait_for(
                send(json.dumps(payload, ensure_ascii=False)), self.send_timeout
            )
        except asyncio.TimeoutError:
            logger.error(
                "Reply to org request %s timed out after %ss",
                payload.get("request_id"),
                self.send_timeout,
            )
        except (discord.HTTPException, OSError) as error:
            logger.error(
                "Reply to org request %s failed: %s", payload.get("request_id"), error
            )
        except Exception:
            # A reply failure must never escape into the message handler: log it
            # against the request id and let the event loop carry on.
            logger.exception(
                "Reply to org request %s failed unexpectedly", payload.get("request_id")
            )


def from_environment(
    org: OrgReserves,
    add_to_vivillon: Callable[[str, int], None],
    remove_from_vivillon: Callable[[str, int], bool],
) -> OrgRpc | None:
    """Build the transport, or None when it is switched off.

    Either ORG_DISCORD_RPC_GUILD_ID (a whole server) or ORG_DISCORD_RPC_CHANNEL_ID
    (one channel) selects the scope; both together mean that channel inside that
    guild. Neither set is the feature flag and the rollback path: the transport is
    not created at all, so on_message stays exactly as it was and nothing is
    listened for.
    """
    channel_id = _read_optional_id(CHANNEL_ENV, "channel")
    guild_id = _read_optional_id(GUILD_ENV, "server")
    if channel_id is None and guild_id is None:
        logger.info(
            "Neither %s nor %s is set: the Discord org transport is disabled",
            GUILD_ENV,
            CHANNEL_ENV,
        )
        return None
    raw_user = os.environ.get(USER_ENV, "").strip()
    if not raw_user.isdigit():
        logger.error(
            "%s is not set or not a user ID: the Discord org transport is disabled",
            USER_ENV,
        )
        return None
    dedupe_path = Path(os.environ.get(DEDUPE_FILE_ENV, DEFAULT_DEDUPE_FILE))
    return OrgRpc(
        channel_id=channel_id,
        guild_id=guild_id,
        org_bot_user_id=int(raw_user),
        org=org,
        add_to_vivillon=add_to_vivillon,
        remove_from_vivillon=remove_from_vivillon,
        dedupe_path=dedupe_path,
    )


def _read_optional_id(name: str, kind: str) -> int | None:
    """Read an ID from the environment. Unset is fine, malformed is not."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        logger.error(
            "%s is not a Discord %s ID: the Discord org transport is disabled",
            name,
            kind,
        )
        return None
    return int(raw)
