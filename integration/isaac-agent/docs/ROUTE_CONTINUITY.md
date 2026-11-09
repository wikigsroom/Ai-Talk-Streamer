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

Validation includes the complete existing suite plus `test_route_memory.py`.
Synthetic scenarios are regression evidence, not actual game progress. No new
model or dependency download is required. CPU-only operation remains supported.
