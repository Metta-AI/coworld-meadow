"""Meadow websocket player entrypoint.

Connects to the game's `/player` route and drives one policy from
`coworld.examples.meadow.player.policies`. The policy is chosen by the first
argv entry, falling back to `COWORLD_MEADOW_POLICY`, defaulting to
`sustainable`; `COWORLD_MEADOW_SEED` seeds stochastic policies.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, cast

import websockets

from coworld.examples.meadow.player.policies import make_policy
from coworld.examples.meadow.shared.log_shipper import get_logger

logger = get_logger("meadow.player")


async def main() -> None:
    policy_name = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("COWORLD_MEADOW_POLICY", "sustainable")
    seed = int(os.environ.get("COWORLD_MEADOW_SEED", "0"))
    policy = make_policy(policy_name, seed=seed)
    url = os.environ["COWORLD_PLAYER_WS_URL"]
    logger.info("policy %s connecting to %s", policy_name, url)
    async with websockets.connect(url, ping_timeout=None) as websocket:
        try:
            while True:
                message = cast(dict[str, Any], json.loads(await websocket.recv()))
                # A slow policy (an LLM seat) can fall behind the round barrier while it thinks;
                # drain the queue so each act() answers the freshest observation, not a stale one.
                while message["type"] == "observation":
                    try:
                        message = cast(
                            dict[str, Any], json.loads(await asyncio.wait_for(websocket.recv(), timeout=0.05))
                        )
                    except TimeoutError:
                        break
                if message["type"] == "final":
                    logger.info("received final message, exiting")
                    return
                if message["type"] == "observation":
                    await websocket.send(json.dumps(policy.act(message)))
        except websockets.exceptions.ConnectionClosed:
            # The server exiting after the last round is the episode-over signal for a seat
            # still mid-act; a closed socket here is lifecycle, not an error.
            logger.info("server closed the connection, exiting")


asyncio.run(main())
