# Lymow Diagnostic Map & Coverage Analytics — Design

Built on `beta/2.1.14`. Ports & extends ideas from **Mortimer452/Lymow-One-MQTT** (MIT) —
per-zone history + RTK heat-map — credited in the code headers.

## Principle: one spatial engine, many views
Everything is one **pose-trail / telemetry accumulator**. Per-zone history, coverage, heatmaps,
obstacle and pass analysis are not four separate features — they are *views* of the same per-tick
data, aggregated either **by zone polygon** or **by spatial grid**.

## Decoded data sources (cloud; validated on hardware)
| Source | Meaning |
|---|---|
| `pose` (x/y/theta), ENU metres | live position + heading. The **breadcrumb pose-trail** (one point per frame) is the *primary* coverage source — it covers everything, including transit. |
| QUERY_PATH `333`-bounded segments | **MAIN-AREA cut** — sparse back-propagated deltas, zone-confined |
| QUERY_PATH `444`-bounded segments | **PERIMETER cut** — the closed boundary laps, zone-confined |
| per-pose `tele` | RTK SNR/sats/accuracy, WiFi/cell RSSI, LoRa, correction age — only present with a live link |
| derived `current_zone` / `current_channel` | point-in-polygon location |
| `cleanInfo.areaInfo.cleanZoneIds` | zones in the current task |
| `cleanReport` (`mowEndType`, `usedBattery`, …) | authoritative task completion |
| `errorCodes` / `warningCodes` | incidents (bumper, channel/perimeter obstacle, stuck, slip, cliff) |
| ❌ `baseOutput.twist` / blade telemetry | BLE-only, never on the cloud — no velocity/blade signal |

### 333 vs 444 — the validated model
`333` and `444` are **both ACTUAL cut**, not a plan: `444` = the perimeter laps (cut first in each
zone), `333` = the main-area strips. Both are sparse, zone-only echoes; the **dense** record is the
breadcrumb. Their *growth per pull* drives the **Activity** state machine — 444 growing → perimeter,
333 growing → main, neither but moving → travel (order-independent, so a main-first mow tags
correctly). *(Earlier revisions mislabelled `444` as a "planned route"; it is not — there is no
planned route in the cloud telemetry.)*

### Back-propagation
On a comms blackout the mower buffers poses and dumps them in a rapid burst on reconnect, so the
breadcrumb self-heals (no spatial hole) — but those burst poses are sparse and carry stale telemetry.
They're detected by burst timing and tagged `conn="backprop"` (the violet Connection-Type class).
Coverage there is real but low-confidence: surfaced as the Pass-Coverage **amber "thin-tracking"** hint,
and excluded from obstacle detection so the sparse sampling can't fabricate phantoms.

## Subsystems
- **`path_engine.py`** — `simplify_path` (render-only curvature thinning), `segment_rows` (split the
  track into straight mowing rows for the pass styles), `classify_segments` (staticity split of the
  QUERY_PATH stream: the large static route vs the small live cut delta), `CutAccumulator`.
- **`pass_coverage.py`** — double- vs single-pass analysis for cross-cut (chess) zones + missed-area
  detection on a fine grid.
- **`obstacles.py`** — **plan-free** detection: an enclosed un-mowed island inside a mowed zone = something
  the mower drove around. Coverage is rasterised as a *dense swath* (not one cell per sample) and
  back-prop regions are masked, so GPS jitter and sparse blackout sampling don't create false obstacles.
- **`zone_stats.py`** — per-zone point-in-polygon coverage + visit history (last_mowed, mow_count,
  time-in-zone, incidents); completion gated on `cleanReport.mowEndType`; a mid-task recharge is treated
  as *suspend* (the session survives dock→charge→resume).
- **`map_render.py`** (split out of `camera.py`) — coverage styles (Green Checker / Gradient / Logical
  Passes / Activity / Paths Off), Pass Coverage (missed + single-pass + amber thin-data), Connection
  Type, telemetry heatmaps (absolute scales + no-data hatch), corridor ribbons, mower glyph with
  headlight beams. In its own module so it never shares `camera.py` with the RTSP stream camera.

## Honest constraints
- ~0.6 s live pose rate (sparser through a back-prop burst) → coarse spatial resolution; heat/coverage
  fill in over time.
- No "actively cutting" signal (blade telemetry is BLE-only) → mowing-vs-transit is geometric, plus the
  333/444 activity phase.
- Coverage = the accumulated pose-trail, not a ground-truth swath; thresholds live in `map_tuning.py`.
- Per-zone area/duration is the session total from the cloud, not a per-zone breakdown — flagged, not faked.

## Data flow
```
MQTT PbOutput   ──► state merge
QUERY_PATH      ──► classify_segments (cut / route) + 333/444 activity phase
each frame      ──► breadcrumb append (pose + tele + conn + act)  ──► coverage / heatmaps
                ──► obstacles (coverage holes) · pass_coverage · zone_stats
cleanReport     ──► zone_stats.finalize (mow_count, last_mowed, end_type)
                       ▼
            Map camera layers       per-zone sensors       telemetry / diagnostic sensors
```
