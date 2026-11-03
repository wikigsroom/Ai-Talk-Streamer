package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.Json.*;

class ItemUseReceiptTest {
    ItemUseReceipt receipt(String purpose, int consumed, boolean inventory, boolean effect, boolean clean) {
        return new ItemUseReceipt("task", "world", 2, "minecraft:bread", purpose, 3, consumed, "fixture:destination", inventory ? 8 : -1, inventory, effect, clean);
    }
    @Test void consumptionRequiresInventoryAndItsDedicatedEffectAndCleanup() {
        assertTrue(receipt("eat", 1, true, true, true).complete()); assertFalse(receipt("eat", 1, true, false, true).complete());
        assertFalse(receipt("eat", 1, true, true, false).complete()); assertFalse(receipt("eat", 0, false, true, true).complete());
    }
    @Test void equipmentDoesNotPretendToConsumeAnItem() {
        assertTrue(receipt("equip", 0, true, true, true).complete());
        assertThrows(Rejected.class, () -> receipt("equip", 1, true, true, true));
    }
    @Test void placementCanRetainAPartialBlockEffectBeforeInventoryConfirmation() {
        var partial = receipt("activate", 0, false, true, false); assertTrue(partial.hasEffect()); assertFalse(partial.complete());
    }
    @Test void confirmedEquipmentSwapSurvivesCancellationBeforeTheNextDriverTick() {
        var acknowledged = receipt("equip", 0, true, false, false);
        assertTrue(acknowledged.hasEffect()); assertFalse(acknowledged.complete());
        assertFalse(receipt("equip", 0, false, false, false).hasEffect());
    }
    @Test void aConfirmedConsumptionRequiresAnActualServerRevision() {
        assertThrows(Rejected.class, () -> receipt("eat", 1, false, false, false));
        assertThrows(Rejected.class, () -> new ItemUseReceipt("task", "world", 2, "minecraft:bread", "eat", 3, 1, "hand", -1, true, true, true));
    }
    @Test void bindingCoversTaskWorldEpochItemAndPurpose() {
        var receipt = receipt("eat", 1, true, true, true);
        var task = obj("task_id", "task", "world_session_id", "world", "control_epoch", 2,
                "goal", obj("skill", "use_item", "item_id", "minecraft:bread", "purpose", "eat"));
        assertTrue(receipt.matches(task)); task.getAsJsonObject("goal").addProperty("purpose", "activate"); assertFalse(receipt.matches(task));
        task.getAsJsonObject("goal").addProperty("purpose", "eat"); task.addProperty("task_id", "other"); assertFalse(receipt.matches(task));
        task.addProperty("task_id", "task"); task.addProperty("control_epoch", 3); assertFalse(receipt.matches(task));
        task.addProperty("control_epoch", 2); task.addProperty("world_session_id", "other"); assertFalse(receipt.matches(task));
    }
}
