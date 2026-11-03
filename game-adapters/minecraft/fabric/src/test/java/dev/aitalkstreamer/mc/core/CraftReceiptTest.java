package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.Json.*;

class CraftReceiptTest {
    private CraftReceipt receipt(int batches, int confirmed, int revision, boolean clean) {
        return new CraftReceipt("task", "world", 3, "minecraft:planks", "minecraft:oak_planks", 3, 5, 4, batches, confirmed, revision, clean);
    }
    @Test void completeMeansAllRoundedBatchesAndCleanEnd() {
        assertEquals(8, receipt(2, 2, 7, true).produced()); assertTrue(receipt(2, 2, 7, true).complete());
        assertFalse(receipt(2, 1, 7, true).complete()); assertFalse(receipt(2, 2, 7, false).complete());
    }
    @Test void batchCountsAreDerivedFromTheOriginalIncrement() {
        assertThrows(Rejected.class, () -> receipt(1, 1, 1, true)); assertThrows(Rejected.class, () -> receipt(2, 3, 1, true));
    }
    @Test void confirmedOutputRequiresAServerRevision() {
        assertThrows(Rejected.class, () -> receipt(2, 1, -1, false)); assertDoesNotThrow(() -> receipt(2, 0, -1, false));
        assertThrows(Rejected.class, () -> receipt(2, 1, 32768, false));
    }
    @Test void everyTaskContextAndQuantityIsBound() {
        var target = new InventoryTarget("minecraft:oak_planks", 3, 5, 1);
        var task = obj("task_id", "task", "world_session_id", "world", "control_epoch", 3);
        assertTrue(receipt(2, 2, 7, true).matches(task, target));
        for (String key : new String[]{"task_id", "world_session_id", "control_epoch"}) {
            var changed = task.deepCopy(); if (key.equals("control_epoch")) changed.addProperty(key, 4); else changed.addProperty(key, "other");
            assertFalse(receipt(2, 2, 7, true).matches(changed, target));
        }
        assertFalse(receipt(2, 2, 7, true).matches(task, new InventoryTarget("minecraft:oak_planks", 4, 5, 1)));
        assertFalse(receipt(2, 2, 7, true).matches(task, new InventoryTarget("minecraft:oak_planks", 3, 6, 1)));
    }
}
