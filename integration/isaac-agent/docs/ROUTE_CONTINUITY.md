# Observed-floor strategic route continuity

`RouteMemory` keeps a bounded observed graph, native visited facts, selected
multi-room goals, physical-target deferrals/failures and no-progress edge counts.
It is shared by strategic offers and the free ordinary-route fallback. A pickup
or paid/special door always needs a fresh current-room DSH plan and native guard.
Only free ordinary steps of a chosen goal may continue between decisions.

State is private `logs/route-memory.json`, scoped by seed/restart/floor/type/
dimension. Visit/controller/bridge IDs continue fencing executable authorizations;
they do not erase semantic refusal memory. Relevant changed conditions reopen
offers for DSH, never authorize them. Previously visited native-map rooms remain
previously visited when a new controller surveys their layout. No hidden graph
edges or unobserved contents are inferred.

Meaningful observation/content/resource progress resets edge counts. Re-entering
a known room or choosing another goal does not. The same directed edge is limited
to two traversals without progress; an exhausted graph safely holds rather than
oscillating. Shared-corridor backtracking after a new branch remains possible.
Door alternatives use walkable `door_path_distance`, including wall-cell doors.

Route endpoints also use the real execution `door_is_usable` policy and current
resources. A closed `super_secret` entrance or unsupported challenge gate cannot
be advertised through a free corridor. Every door, including a special door
without route metadata, obeys the same no-progress edge limit. An unavailable
goal is explicitly removed before a fresh choice rather than kept as stale intent.

Observed boss trapdoors remain productive destinations after clearing the room.
Returning there is labelled `observed_floor_exit`; an old persisted boss record
without exit observations allows one `survey_cleared_boss_exit` visit, without
claiming a trapdoor exists. An observed missing exit is not reoffered as a goal.
Actual floor-exit offers remain ordinary bounded DSH choices. A next-stage receipt
requires the same run, an issued observed exit and the next native stage, not an
arbitrary room change. No pickup, paid step or old authorization is inherited.

Validation includes the complete existing suite plus `test_route_memory.py`.
Synthetic scenarios are regression evidence, not actual game progress. No new
model or dependency download is required. CPU-only operation remains supported.

### Native engine loading boundary

An actual native IsPaused or ControlsEnabled=false observation permits a bounded ten-second wait for loading, excluding ordinary pause acknowledgements, death and manual takeover. Heartbeats cannot roll that deadline forward. State remains stale after 1.5 seconds; expired input/target authorization and stale speech are never valid. Hosts should only postpone their disconnected-gameplay pause while StrategyService.native_engine_hold_grace() is true, rechecking under their control lock.

The native input guard sends a fresh observation after a room identity change or engine input-unhold and waits up to 500ms for its response before declaring a five-second combat lease lost. It does not renew leaseUntil, release pauseHold, use items or change any game/save data. A real disconnection or loading over the budget still stops normally.
