"""URI read/write helpers shared by the Meadow game server and grader.

Kept separate from `game.server` so supporting roles can import them without
triggering the server's module-level config loading.
"""

from __future__ import annotations

import gzip
import json
import os
import zlib
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

# urllib's default User-Agent ("Python-urllib/3.x") is blocked by some CDN
# WAFs (Cloudflare's "Bad bot" rule, error 1010), so we set an explicit one
# whenever we drive an HTTP request. Any non-default UA suffices.
HTTP_USER_AGENT = "coworld-meadow/0.1"
JSON_CONTENT_TYPE = "application/json"


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, headers={"User-Agent": HTTP_USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def artifact_method(env_var: str) -> Literal["POST", "PUT"]:
    method = os.environ.get(env_var, "PUT").upper()
    if method not in {"POST", "PUT"}:
        raise ValueError(f"{env_var} must be PUT or POST")
    return cast(Literal["POST", "PUT"], method)


def write_data(
    uri: str,
    data: bytes | str,
    *,
    content_type: str,
    http_method: Literal["POST", "PUT"] = "PUT",
) -> None:
    if isinstance(data, str):
        data = data.encode()

    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method=http_method)
        request.add_header("Content-Type", content_type)
        request.add_header("User-Agent", HTTP_USER_AGENT)
        with urlopen(request, timeout=60):
            return
    if parsed.scheme in ("file", ""):
        path = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    raise ValueError(f"Unsupported URI for write_data: {uri}")


def load_replay_data(replay_uri: str) -> dict[str, Any]:
    replay_data = read_data(replay_uri)
    if replay_uri.endswith(".z"):
        replay_data = zlib.decompress(replay_data)
    elif replay_uri.endswith(".gz"):
        replay_data = gzip.decompress(replay_data)
    return json.loads(replay_data)
