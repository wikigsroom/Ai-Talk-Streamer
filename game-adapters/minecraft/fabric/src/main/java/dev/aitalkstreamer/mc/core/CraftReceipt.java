package dev.aitalkstreamer.mc.core;

import com.google.gson.JsonObject;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Immutable local result of server-synchronized, task-owned crafting transactions. */
public record CraftReceipt(String taskId, String world, long epoch, String recipeId, String itemId,
                           int baseline, int requested, int perBatch, int batches, int confirmedBatches,
                           int lastServerRevision, boolean cleanEnd) {
    public CraftReceipt {
        require(taskId != null && world != null && recipeId != null && itemId != null && epoch >= 0
                        && !recipeId.isBlank() && recipeId.length() <= 160,
                "GAME_CRAFT_RECEIPT_CONTEXT");
        InventoryTarget target = new InventoryTarget(itemId, baseline, requested, perBatch);
        require(batches == target.batches() && confirmedBatches >= 0 && confirmedBatches <= batches
                && lastServerRevision >= -1 && lastServerRevision <= 32767
                && (confirmedBatches == 0 || lastServerRevision >= 0), "GAME_CRAFT_RECEIPT_COUNTS");
    }
    public int produced() { return Math.multiplyExact(confirmedBatches, perBatch); }
    public boolean matches(JsonObject task, InventoryTarget target) {
        return taskId.equals(str(task, "task_id")) && world.equals(str(task, "world_session_id"))
                && epoch == num(task, "control_epoch") && itemId.equals(target.itemId())
                && baseline == target.baseline() && requested == target.requestedIncrement();
    }
    public boolean complete() { return cleanEnd && confirmedBatches == batches; }
}
