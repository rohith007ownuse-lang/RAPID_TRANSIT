# Data-source honesty rules

This project measures nothing directly in simulation mode. The rules below are
the difference between a demo and a fabrication — they are enforced in code,
not just in prose.

## The four labels

| Label | Colour | Meaning |
|---|---|---|
| `LIVE` | green | a real sensor / model / stream measured it |
| `MODEL` | blue | a trained model inferred it (named model, real confidence) |
| `HEURISTIC` | amber | a rule-of-thumb estimated it (named, no confidence claimed) |
| `SIMULATION` | slate | the fleet simulator produced it for demonstration |

Every page shows its badge. Every `/api/*` response carries `simulation`
and `mode`.

## Non-negotiable rules

1. **Never present simulated values as real measurements.**
2. **No accuracy / precision / F1 / FPS / dataset claims** unless a real
   evaluation produced them and the script that did is in the repo.
3. **Unknown is `null`, never `0`.** A disconnected camera means unknown
   occupancy — not an empty bus. Loading states render `…` / `—`.
4. **Rules travel with data.** Thresholds (e.g. hotspot `radius_m` /
   `min_buses`) are part of the API payload, never hardcoded UI strings.
5. **Source is preserved across reconnects.** A live bus that drops and
   reconnects must not silently become a simulated bus
   (`preserve_data_source` in `websocket_hardening.py`).
6. **Assumptions are documented at their use site.** Example: bus tare 11 t,
   GVW 17 t, payload 6 t are project assumptions, stated where they are used.
7. **No synthetic frames.** A camera that cannot open reports `DISCONNECTED` +
   reason — never a fabricated image or FPS.
8. **The cabin heuristic is never labelled ML.** `estimator="heuristic"`,
   `estimator_type="development"`, `confidence=None`. The real-model slot
   (`FLEETIQ_CABIN_MODEL_PATH`) is reported honestly as available or not.
9. **Capacity fallbacks are documented.** Per-bus capacity wins; the 40-seat
   default is a stated fallback, never claimed as measured.
