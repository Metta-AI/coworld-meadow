"""Physical resource settings identify replicas independently of policy seeds."""

import hashlib
import json

from coworld.examples.meadow.game.engine import MeadowConfig


def scenario_family(config: MeadowConfig) -> str:
    physical = {
        name: getattr(config, name)
        for name in (
            "num_players",
            "rounds",
            "stock_start",
            "stock_capacity",
            "regrowth_rate",
            "collapse_threshold",
            "max_harvest",
        )
    }
    encoded = json.dumps(physical, sort_keys=True, separators=(",", ":")).encode()
    return "meadow-" + hashlib.sha256(encoded).hexdigest()
