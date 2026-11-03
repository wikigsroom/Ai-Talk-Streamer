package dev.aitalkstreamer.mc.core;

import com.google.gson.JsonObject;
import java.util.List;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Immutable facts from the item's dedicated server checks, never a client prediction. */
public record ItemUseReceipt(String taskId, String world, long epoch, String itemId, String purpose,
                             int baseline, int consumed, String destination, int serverRevision,
                             boolean inventoryConfirmed, boolean effectConfirmed, boolean cleanEnd) {
    public ItemUseReceipt {
        require(taskId != null && !taskId.isBlank() && world != null && !world.isBlank() && epoch >= 0
                && itemId != null && itemId.matches("[a-z0-9_.-]+:[a-z0-9_./-]+")
                && List.of("eat", "equip", "activate").contains(purpose) && baseline >= 0
                && consumed >= 0 && consumed <= 1 && consumed <= baseline
                && destination != null && !destination.isBlank() && destination.length() <= 256
                && serverRevision >= -1 && serverRevision <= 32767
                && (!inventoryConfirmed || serverRevision >= 0) && (consumed == 0 || inventoryConfirmed)
                && (!purpose.equals("equip") || consumed == 0), "GAME_ITEM_RECEIPT_INVALID");
    }
    public boolean matches(JsonObject task) {
        var goal = task.getAsJsonObject("goal");
        return str(task, "task_id").equals(taskId) && str(task, "world_session_id").equals(world)
                && num(task, "control_epoch") == epoch && str(goal, "skill").equals("use_item")
                && str(goal, "item_id").equals(itemId) && str(goal, "purpose").equals(purpose)
                && (!goal.has("target") || purpose.equals("activate") && targetMatches(goal.getAsJsonObject("target")));
    }
    private boolean targetMatches(JsonObject target) {
        return destination.equals(str(target, "dimension") + ":" + num(target, "x") + "," + num(target, "y") + "," + num(target, "z"));
    }
    public boolean complete() { return cleanEnd && inventoryConfirmed && effectConfirmed && (purpose.equals("equip") || consumed == 1); }
    public boolean hasEffect() { return consumed > 0 || effectConfirmed || purpose.equals("equip") && inventoryConfirmed; }
    public String summary() {
        return "Item " + itemId + ", purpose " + purpose + ", destination " + destination
                + "; confirmed consumed units " + consumed + "; server inventory revision " + serverRevision
                + "; inventory confirmed " + inventoryConfirmed + "; item-specific effect confirmed " + effectConfirmed
                + "; clean end " + cleanEnd + ".";
    }
}
