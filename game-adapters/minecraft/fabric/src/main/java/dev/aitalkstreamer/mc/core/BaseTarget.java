package dev.aitalkstreamer.mc.core;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.util.List;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Immutable A-registry snapshot. B checks its binding, not the current contents of A's database. */
public final class BaseTarget {
    private static final class Schema { private static final Wire WIRE = new Wire(); }
    private final JsonObject value;
    private BaseTarget(JsonObject value) { this.value = value.deepCopy(); }
    public static BaseTarget resolve(JsonObject goal, JsonElement raw, JsonElement expected, JsonObject observation) {
        if (!str(goal, "skill").equals("return_base")) {
            require(raw == null && expected == null, "GAME_BASE_CONTEXT_INVALID"); return null;
        }
        require(raw instanceof JsonObject && observation != null, "GAME_BASE_TARGET_REQUIRED");
        Schema.WIRE.validate("BaseTarget", raw);
        BaseTarget target = new BaseTarget(raw.getAsJsonObject());
        require(str(goal, "base_id").equals(target.baseId()), "GAME_BASE_CONTEXT_INVALID");
        for (String key : List.of("game_instance_id", "world_id"))
            require(target.value.get(key).equals(observation.get(key)), "GAME_BASE_CONTEXT_INVALID");
        require(observation.get("player") instanceof JsonObject player
                && player.get("position") instanceof JsonObject position
                && str(position, "dimension").equals(target.dimension()), "GAME_BASE_DIMENSION_CHANGED");
        if (expected != null) {
            Schema.WIRE.validate("BaseRef", expected);
            require(target.reference().equals(expected), "GAME_BASE_CHANGED");
        }
        return target;
    }
    public static BaseTarget forTask(JsonObject task, JsonObject observation) {
        return resolve(task.getAsJsonObject("goal"), task.get("base_target"), null, observation);
    }
    public JsonObject json() { return value.deepCopy(); }
    public JsonObject reference() {
        JsonObject result = new JsonObject();
        for (String key : List.of("game_instance_id", "world_id", "base_id", "base_revision", "world_revision")) result.add(key, value.get(key));
        return result;
    }
    public String baseId() { return str(value, "base_id"); }
    public long baseRevision() { return num(value, "base_revision"); }
    public long worldRevision() { return num(value, "world_revision"); }
    public String dimension() { return str(value.getAsJsonObject("position"), "dimension"); }
    public int x() { return (int) num(value.getAsJsonObject("position"), "x"); }
    public int y() { return (int) num(value.getAsJsonObject("position"), "y"); }
    public int z() { return (int) num(value.getAsJsonObject("position"), "z"); }
    public int radius() { return (int) num(value, "radius"); }
    public boolean reached(JsonObject position) {
        if (position == null || !dimension().equals(nullable(position, "dimension"))) return false;
        double dx = position.get("x").getAsDouble() - x(), dy = position.get("y").getAsDouble() - y(), dz = position.get("z").getAsDouble() - z();
        return dx * dx + dy * dy + dz * dz <= (double) radius() * radius();
    }
}
