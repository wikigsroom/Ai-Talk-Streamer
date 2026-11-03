package dev.aitalkstreamer.mc.core;

import com.google.gson.JsonObject;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Game-thread observations only. No disk, network, respawn or input ownership. */
public final class PlayerLifeEvents {
    private String world;
    private Boolean alive;
    private long previousSeq;

    public void reset() { world = null; alive = null; previousSeq = 0; }

    public JsonObject observe(JsonObject sample, String taskId) {
        String nextWorld = str(sample, "world_session_id");
        if (!Objects.equals(world, nextWorld)) { reset(); world = nextWorld; }
        JsonObject player = sample.get("player") instanceof JsonObject value ? value : null;
        boolean deadScreen = "death".equals(str(sample, "screen"));
        Double health = player == null || !player.has("health") || player.get("health").isJsonNull()
                ? null : player.get("health").getAsDouble();
        Boolean next = null;
        if (deadScreen || (health != null && health <= 0)) next = Boolean.FALSE;
        // A newly created client player can expose its default positive health
        // while the terrain/loading menu is still receiving the saved state.
        // It cannot establish a living baseline for a newly joined world. Once
        // life is known, ordinary menus retain continuity (including respawn).
        else if (health != null && health > 0 && (alive != null
                || Set.of("gameplay", "inventory", "container").contains(str(sample, "screen")))) next = Boolean.TRUE;
        // An unknown observation breaks continuity; it cannot prove a subsequent respawn.
        if (next == null) { alive = null; previousSeq = 0; return null; }
        String kind = !next && alive == null ? "player_dead_observed"
                : Boolean.TRUE.equals(alive) && !next ? "player_death"
                : Boolean.FALSE.equals(alive) && next ? "player_respawn" : null;
        long before = previousSeq; alive = next; previousSeq = num(sample, "seq");
        if (kind == null) return null;
        JsonObject data = obj("source", "client_observation", "health", health, "screen", sample.get("screen"),
                "position", player == null ? null : player.get("position"), "previous_observation_seq", before == 0 ? null : before,
                "cause_known", false, "inventory_restored_verified", false, "requires_review", true);
        return obj("event_id", "event-" + UUID.randomUUID(), "world_session_id", nextWorld,
                "seq", sample.get("seq"), "occurred_at", sample.get("observed_at"), "kind", kind,
                "severity", next ? "important" : "critical", "task_id", taskId, "data", data.deepCopy());
    }
}
