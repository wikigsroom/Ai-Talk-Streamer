package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Public counts are increments; only the local executor receives an inventory total. */
public record InventoryTarget(String itemId, int baseline, int requestedIncrement, int outputPerBatch) {
    public InventoryTarget {
        require(itemId != null && !itemId.isBlank(), "GAME_ITEM_UNKNOWN");
        require(baseline >= 0, "GAME_INVENTORY_COUNT_INVALID");
        require(requestedIncrement >= 1 && requestedIncrement <= 4096, "GAME_ITEM_COUNT_INVALID");
        require(outputPerBatch >= 1 && outputPerBatch <= 4096, "GAME_CRAFT_OUTPUT_COUNT_INVALID");
        long batches = ((long) requestedIncrement + outputPerBatch - 1) / outputPerBatch;
        require((long) baseline + batches * outputPerBatch <= Integer.MAX_VALUE, "GAME_ITEM_TARGET_TOO_LARGE");
    }
    public int batches() { return (requestedIncrement + outputPerBatch - 1) / outputPerBatch; }
    public int plannedIncrement() { return batches() * outputPerBatch; }
    public int targetTotal() { return baseline + plannedIncrement(); }
    public static InventoryTarget gather(JsonObject goal, JsonObject observation) {
        require(str(goal, "skill").equals("gather"), "GAME_INVENTORY_TARGET_KIND");
        return new InventoryTarget(str(goal, "item_id"), count(observation, str(goal, "item_id")),
                Math.toIntExact(num(goal, "count")), 1);
    }
    public static int count(JsonObject observation, String itemId) {
        require(observation != null && observation.get("inventory") instanceof JsonArray, "GAME_INVENTORY_UNAVAILABLE");
        long total = 0;
        for (JsonElement element : observation.getAsJsonArray("inventory")) {
            JsonObject entry = element.getAsJsonObject();
            if (!str(entry, "item_id").equals(itemId)) continue;
            long amount = num(entry, "count");
            require(amount >= 0 && amount <= Integer.MAX_VALUE, "GAME_INVENTORY_COUNT_INVALID");
            total += amount;
            require(total <= Integer.MAX_VALUE, "GAME_INVENTORY_COUNT_INVALID");
        }
        return (int) total;
    }
}
