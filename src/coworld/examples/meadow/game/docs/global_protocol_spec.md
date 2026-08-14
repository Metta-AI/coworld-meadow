# Meadow Global Protocol

Connect to the game's `/global` WebSocket for a read-only live view. The game sends a `state` snapshot on connect,
then roughly every 0.5 seconds until the episode finishes:

```json
{
  "type": "state",
  "round": 14,
  "rounds": 60,
  "stock": 58.41,
  "stock_capacity": 100.0,
  "collapse_threshold": 10.0,
  "collapsed": false,
  "collapse_round": null,
  "scores": [16.0, 12.5],
  "total_harvested": [16.0, 14.5],
  "player_names": ["P0", "P1"],
  "last_round": {
    "round": 13,
    "stock_before": 57.0,
    "demands": [1, 2],
    "harvests": [1.0, 2.0],
    "stock_after_harvest": 54.0,
    "stock_after_regrowth": 58.41,
    "sanctions": [{ "by": 0, "target": 1 }],
    "messages": [{ "slot": 0, "text": "hold at 1 each" }],
    "scores": [16.0, 12.5],
    "collapsed": false
  },
  "connected": [0, 1],
  "submitted": [0],
  "started": true,
  "paused": false,
  "round_seconds": 20.0,
  "done": false
}
```

Messages sent by the viewer are drained and ignored. The `/admin` WebSocket accepts
`{"command": "pause"}`, `{"command": "resume"}`, and `{"command": "round_seconds", "round_seconds": 5.0}` and answers
each command with a fresh snapshot.
