"""HTTP API that lets the org bot manage reserves in Vivillon."""

import hmac
import json
import logging
import unicodedata
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

logger = logging.getLogger(__name__)


class OrgError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {path}") from error


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_path.replace(path)


def fold(name: str) -> str:
    return unicodedata.normalize("NFC", name).replace("’", "'").casefold().strip()


class OrgReserves:
    """Org reserve list, kept separate from Vivillon's saved reservations."""

    def __init__(
        self,
        path: Path,
        restrictions_path: Path,
        known_names: list[str],
    ) -> None:
        self.path = path
        self.entries: list[dict[str, Any]] = load_json(path, [])
        restriction_data = load_json(restrictions_path, {})
        slots = restriction_data.get("slots", {})
        if isinstance(slots, list):
            shared_rule = restriction_data.get("shared", {})
            self.restrictions: dict[str, dict[str, list[str]]] = {
                slot: shared_rule for slot in slots
            }
        else:
            self.restrictions = slots
        self.names: dict[str, str] = {}
        for name in known_names:
            current = self.names.get(fold(name))
            if current is None or current == current.lower():
                self.names[fold(name)] = name

    def canonical_name(self, pokemon: str) -> tuple[str, bool]:
        """Return (display name, all_forms). Raises OrgError if unknown."""
        text = unicodedata.normalize("NFC", pokemon).strip()
        all_forms = False
        if text.casefold().startswith("all "):
            all_forms = True
            text = text[4:].strip()
        canonical = self.names.get(fold(text))
        if canonical is None:
            raise OrgError(404, f"Pokémon not found: {pokemon}")
        return canonical, all_forms

    def check_restriction(self, name: str, slot: str | None) -> None:
        if slot is None:
            return
        rule = self.restrictions.get(slot)
        if rule is None:
            return
        allowed = rule.get("allowed")
        blocked = rule.get("blocked", [])
        if allowed is not None and fold(name) not in {fold(n) for n in allowed}:
            raise OrgError(403, f"{name} is not allowed in slot {slot}")
        if fold(name) in {fold(n) for n in blocked}:
            raise OrgError(403, f"{name} is blocked in slot {slot}")

    def validate(self, pokemon: str, slot: str | None) -> tuple[str, bool]:
        name, all_forms = self.canonical_name(pokemon)
        self.check_restriction(name, slot)
        return name, all_forms

    def add(self, name: str, user_id: int, slot: str | None) -> bool:
        for entry in self.entries:
            if entry["pokemon"] == name and entry["userId"] == str(user_id):
                return False
        self.entries.append({"pokemon": name, "userId": str(user_id), "slot": slot})
        save_json(self.path, self.entries)
        return True

    def remove(self, name: str, user_id: int) -> bool:
        kept = [
            entry
            for entry in self.entries
            if not (entry["pokemon"] == name and entry["userId"] == str(user_id))
        ]
        removed = len(kept) != len(self.entries)
        if removed:
            self.entries = kept
            save_json(self.path, self.entries)
        return removed

    def reset(self) -> int:
        count = len(self.entries)
        self.entries = []
        save_json(self.path, self.entries)
        return count


def create_app(
    api_key: str,
    org: OrgReserves,
    guild_id: int,
    add_to_vivillon: Callable[[str, int], None],
    remove_from_vivillon: Callable[[str, int], bool],
) -> web.Application:
    @web.middleware
    async def guard(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.path == "/api/org/health":
            return await handler(request)
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {api_key}".encode()):
            return web.json_response(
                {"success": False, "error": "Unauthorized"}, status=401
            )
        try:
            return await handler(request)
        except OrgError as error:
            return web.json_response(
                {"success": False, "error": error.message}, status=error.status
            )
        except ValueError as error:
            logger.exception("Org API storage error")
            return web.json_response(
                {"success": False, "error": str(error)}, status=500
            )

    async def body(request: web.Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None
        if not isinstance(data, dict):
            raise OrgError(400, "Invalid request")
        return data

    def parse_user(data: dict[str, Any]) -> int:
        user_id = data.get("userId")
        if not isinstance(user_id, str) or not user_id.isdigit():
            raise OrgError(400, "Invalid request: userId must be a Discord ID string")
        return int(user_id)

    def parse_pokemon(data: dict[str, Any]) -> str:
        pokemon = data.get("pokemon")
        if not isinstance(pokemon, str) or not pokemon.strip():
            raise OrgError(400, "Invalid request: pokemon must be a string")
        return pokemon

    def parse_slot(data: dict[str, Any]) -> str | None:
        slot = data.get("slot")
        if slot is None:
            return None
        if not isinstance(slot, str):
            raise OrgError(400, "Invalid request: slot must be a string")
        return slot

    async def reserves(request: web.Request) -> web.Response:
        data = await body(request)
        action = data.get("action")
        if action not in {"add", "remove"}:
            raise OrgError(400, "Invalid request: action must be add or remove")
        user_id = parse_user(data)
        slot = parse_slot(data)
        pokemon = parse_pokemon(data)
        if action == "add":
            name, all_forms = org.validate(pokemon, slot)
        else:
            name, all_forms = org.canonical_name(pokemon)
        stored = f"All {name}" if all_forms else name
        if action == "add":
            created = org.add(stored, user_id, slot)
            add_to_vivillon(stored, user_id)
            changed = created
        else:
            changed = org.remove(stored, user_id)
            changed = remove_from_vivillon(stored, user_id) or changed
            if not changed:
                raise OrgError(404, f"{stored} is not reserved for that user")
        return web.json_response(
            {
                "success": True,
                "action": action,
                "pokemon": stored,
                "userId": str(user_id),
                "slot": slot,
                "changed": changed,
            }
        )

    async def validate(request: web.Request) -> web.Response:
        data = await body(request)
        name, all_forms = org.validate(parse_pokemon(data), parse_slot(data))
        return web.json_response(
            {
                "success": True,
                "valid": True,
                "pokemon": f"All {name}" if all_forms else name,
            }
        )

    async def list_reserves(request: web.Request) -> web.Response:
        del request
        return web.json_response(
            {"success": True, "count": len(org.entries), "reserves": org.entries}
        )

    async def reset(request: web.Request) -> web.Response:
        del request
        return web.json_response({"success": True, "cleared": org.reset()})

    async def health(request: web.Request) -> web.Response:
        del request
        return web.json_response({"success": True, "status": "ok"})

    app = web.Application(middlewares=[guard])
    app.router.add_get("/api/org/health", health)
    app.router.add_post("/api/org/reserves", reserves)
    app.router.add_post("/api/org/validate", validate)
    app.router.add_get("/api/org/reserves", list_reserves)
    app.router.add_post("/api/org/reset", reset)
    app["guild_id"] = guild_id
    return app
