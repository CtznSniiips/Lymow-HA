"""User-tunable parameters for the Lymow diagnostic MAP camera.

This is the ONE place to adjust how the map flags coverage issues. Edit a value, then reload
the Lymow integration (Settings → Devices & Services → Lymow → ⋮ → Reload) or restart Home
Assistant, and re-open the Lymow Map camera to see the effect on YOUR yard.

All AREAS are in square metres (m²) and all LENGTHS in metres (m), regardless of whether your
HA shows the labels in ft²/in — the map auto-converts the *display* to your HA unit system.

Tuning tips:
  • See too few missed-area rings?  lower MISSED_RING_MIN_M2.
  • Rings hugging zone edges (noise)? raise MISSED_RING_MIN_M2, or raise MOWED_FRAC.
  • Want finer detection of thin gaps? lower MISSED_CELL_M (slower render).
  • False single-pass flags at row-ends? raise TURNAROUND_EXCL_M.
"""

# ── Missed-area detection (Pass Coverage layer: un-mowed gaps circled in RED) ────────────────
# Smallest un-mowed gap that gets a ring. 0.04 m² ≈ 0.5 ft² ≈ a 6×6 in patch.
MISSED_RING_MIN_M2 = 0.04
# Rasterisation grid for the missed/covered test (m). Finer = catches thinner gaps, slower render.
MISSED_CELL_M = 0.15

# ── Single-pass detection (CHESS/checker zones that didn't get the 2nd cross pass: AMBER ring) ─
# Smallest single-pass patch that gets a ring. Single-pass is only flagged inside checker zones.
SINGLE_RING_MIN_M2 = 1.5

# ── Coverage swath ──────────────────────────────────────────────────────────────────────────
# Drawn swath width (m). Slightly wider than the real 16 in cut so adjacent passes tile cleanly
# AND so the round-joint blobs overlap enough to smooth the outer-edge serration (the perimeter
# pass's blobs poking out under RTK jitter). Purely cosmetic for the coverage render — too wide
# and the green over-represents past the real cut, so keep it modest. [Nate 2026-06-08: 0.45→0.52]
SWATH_DRAW_M = 0.52
# Real blade cut width (m) = 16 in. Used to anchor the mower-marker size and the overlap metric.
# Don't change this for tuning — it's a hardware fact, not a preference.
CUT_WIDTH_M = 0.4064

# ── Zone "mowed" gate ───────────────────────────────────────────────────────────────────────
# A zone is only analysed for misses if at least this fraction of it got coverage — so a zone
# you deliberately skipped isn't reported as one giant miss.
MOWED_FRAC = 0.30

# ── Turnaround (U-turn) pivot exclusion ─────────────────────────────────────────────────────
# Single-pass clusters whose centre is within this radius (m) of a row-end U-turn are dropped —
# the mower overlaps swaths through the pivot, so a "single-pass" flag there is a GPS artifact.
TURNAROUND_EXCL_M = 1.2

# ── Obstacle detection (un-mowed island the mower routed around) ─────────────────────────────
# An obstacle's un-mowed HOLE = the object + the mower's keep-out standoff on every side; we
# subtract the standoff to estimate the real object. A hole barely larger than the standoff ring
# has essentially NO object inside it — that's a small enclosed coverage gap (GPS jitter / a
# skipped cell on a straight pass), not something routed around. Reject when the estimated
# object's LONGEST side is under this (m). Validated vs Nate's 2026-06-06 backyard: phantom
# object 0.2 m, both real objects >= 0.6 m (a 16x24 in box and a ~1 ft milk can).
#   Phantom obstacles still slipping through?  raise toward 0.4.
#   Small real objects being dropped?          lower toward 0.2.
MIN_OBJECT_DIM = 0.3

# ── Dwell / stuck anomaly detection ─────────────────────────────────────────────────────────
# Flag when the mower is stuck in one spot WHILE MOWING: if its pose stays within DWELL_RADIUS_M
# for at least DWELL_TIME_S, it's not making progress. Classified by heading into a "spin" (a
# crop-circle — turns consistently one way) vs "jitter" (rocks back and forth). Validated against
# two real 2026-06-06 events (a jitter + a verified crop-circle spin).
#   Too many false flags on tight turns / slow patches?  lower DWELL_RADIUS_M or raise DWELL_TIME_S.
#   Missing brief real stalls?                            raise DWELL_RADIUS_M or lower DWELL_TIME_S.
DWELL_RADIUS_M = 0.25      # all recent poses must sit within this radius (m)
DWELL_TIME_S = 20.0        # ...for at least this long (s) — longer than any U-turn pivot
# Classification of a confirmed dwell, by how much the mower MOVED (path) and TURNED while pinned:
#   disregard (hidden)  if  < DWELL_DISREGARD_S  AND  turns < DWELL_DISREGARD_TURNS  (brief, no spin)
#   spin                if  turns >= DWELL_SPIN_TURNS         (crop circle)
#   excess-turn         if  turns >  DWELL_EXCESS_TURNS       (> half a turn — yard wear)
#   jitter              if  path  >= DWELL_JITTER_PATH_M      (>= 4 m thrash in place — HEAVY wear)
#   struggle            if  path  >= DWELL_STRUGGLE_PATH_M    (2-4 m — moderate thrash)
#   paused (info only)  otherwise                            (stationary: E-stop / RTK lock)
DWELL_DISREGARD_S = 25.0
DWELL_DISREGARD_TURNS = 0.1
DWELL_EXCESS_TURNS = 0.6
DWELL_SPIN_TURNS = 1.0
DWELL_JITTER_PATH_M = 4.0
DWELL_STRUGGLE_PATH_M = 2.0

# ── Channel corridor ribbon ─────────────────────────────────────────────────────────────────
# Channels arrive as a CENTRELINE path (A→B); we render a corridor RIBBON by offsetting it this
# far perpendicular to each side (m). Purely a map drawing — half the visible corridor width.
#   Ribbon too skinny / too fat?  adjust (0.15 ≈ ±6 in, 0.30 ≈ ±1 ft).
CHANNEL_RIBBON_HALFWIDTH_M = 0.25

# ── Zone "complete enough to judge" gate ────────────────────────────────────────────────────
# A zone is only flagged for obstacles / missed / single-pass / red-background once its mowed
# footprint covers at least this fraction of its area. Below it, the zone is still in progress
# (or merely transited on the way somewhere) so its un-reached ground is NOT a real defect.
# Combined with the task-list check (cleanZoneIds), this stops false flags on zones you didn't
# finish (a mid-mow recharge) or never intended to mow this run.
#   Too many false flags on partly-done / transited zones?  raise toward 0.90.
#   Real defects hidden on finished zones (e.g. big real obstacle)?  lower toward 0.65.
COMPLETE_FRAC = 0.80
