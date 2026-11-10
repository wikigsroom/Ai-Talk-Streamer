# Large-room pit stalemate correction

The 2026-11-11 native gameplay observation stayed in stage 3, room 80, visit 42 with three stationary enemies at 20 HP each. Frames advanced and the weapon emitted shots, but the player remained about 282 units from the nearest enemy. There was no pending DSH choice.

The Python firing-lane planner admitted the current tile using nominal TearRange 360 minus 25 (335). The native movement planner capped engagement range at 235. Since tears cross pits but the player cannot, this disagreement prevented Python from supplying a route around the pits while the short native forecast could not make the detour on its own. The player also held Proptosis; nominal range alone is not evidence that a shot did useful damage.

`firing_position` now caps the lane range at the native planner's existing 235-unit ceiling. Shorter nominal ranges retain their lower bound. This creates a reachable cardinal waypoint around the pits, preserved by the ordinary movement-penalty path. No game statistics, saves, pickups or model ownership change.

The sanitized observed layout is `tests/fixtures/stage3-pit-range-stall.json`; the regression exercises real candidate generation and reachable waypoints. Offline replay and a live room clear must be reported separately. This patch does not prove coverage of every item combination or a complete run.
