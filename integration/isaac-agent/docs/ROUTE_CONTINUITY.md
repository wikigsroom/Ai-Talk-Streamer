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

### Strategic exit alternative and host control revisions

A native observed, safe reachable boss exit is offered alongside remaining
rewards even when the local policy prefers health or treasure backtracking.
DSH chooses whether to leave; local preferences cannot hide that alternative.
Offer construction and execution both recheck exit availability, clear state,
enemies/projectiles, current dangers, exit obstructions and path reachability.
No old choice may execute after an exit disappears or a spike blocks it.

A host watchdog must recheck its observed control revision under the control
lock before a delayed health/identity failure or terminal observation can stop
play. An explicit pause withdraws autopilot before clearing the armed flag;
that transient combination must not increment the completed owner's revision.
Current genuine failures still stop normally. Recording/drink resume guards
remain strict; hosts cannot adopt another owner's pause.

The existing observed stage-eight Devil Room trapdoor toward Sheol is retained for the Satan run goal. Other Devil Rooms are not assumed to provide that route. Exit-obstruction checks retain the moving-spike veto; inert pedestal/retracted-spike markers still use actual path geometry and native collision guards.

### Stable observations and executable remote frontiers

Schema 2 rebuilds only the observation cache, leaving game/save data untouched.
Schema 1 can contain a new stage combined with a previous floor's map and is not
inherited. During native pause or ControlsEnabled=false, graph observation and
offer annotation suspend before mutating the floor, visited rooms, objectives or
goal. The real packet and all freshness/authorization guards remain unchanged.
The first stable packet supplies the actual new floor and map.

For a clear stable room, each observed door stores its local path reachability,
using the executor's door_path_distance and native unreachable-door slots.
A physically blocked exit cannot advertise a remote frontier through cleared
corridors. New actual geometry/entry observations can make it reachable again;
resource, door-admission and paid-terminal approval checks still apply separately.

Progress signatures exclude destination-clear flags, free-door opening phases,
door thresholds, timed spike phases and reallocated hazard entity IDs. Actual
room discovery, clear/content changes, permanent geometry changes and resource
or inventory gains retain their existing meaning. Animation and merely choosing
another goal cannot reset the edge repetition budget. No new model is involved.

The native bundle also exposes a fixed `NativeRefreshObservation` hook. It only
requests the existing full native observation/TCP exchange when simulation/Mod
callbacks are quiet. Its acknowledgment never certifies freshness, resumes
input, changes a lease or clears an ordinary pause. Real state loss still stops.
