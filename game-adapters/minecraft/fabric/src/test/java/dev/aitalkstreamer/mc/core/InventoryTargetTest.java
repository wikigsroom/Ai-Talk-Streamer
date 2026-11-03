package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.Test;
import java.util.List;
import static dev.aitalkstreamer.mc.core.Json.*;
import static org.junit.jupiter.api.Assertions.*;

class InventoryTargetTest {
    private final JsonObject goal = obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4);
    private JsonObject stock(int count) { return obj("inventory", List.of(obj("item_id", "minecraft:oak_log", "count", count))); }
    @Test void threeLogsPlusFourRequestedRequiresSevenInTheExecutor() {
        var target = InventoryTarget.gather(goal, stock(3));
        assertEquals(3, target.baseline()); assertEquals(4, target.requestedIncrement()); assertEquals(7, target.targetTotal());
        assertEquals(4, num(goal, "count"));
    }
    @Test void existingStockAboveTheRequestedIncrementDoesNotShortCircuit() {
        assertEquals(14, InventoryTarget.gather(goal, stock(10)).targetTotal());
    }
    @Test void splitStacksAreSummedWithoutIncludingAnotherItem() {
        var observed = stock(3); observed.getAsJsonArray("inventory").add(obj("item_id", "minecraft:oak_log", "count", 2));
        observed.getAsJsonArray("inventory").add(obj("item_id", "minecraft:stone", "count", 64));
        assertEquals(9, InventoryTarget.gather(goal, observed).targetTotal());
    }
    @Test void craftingRoundsNewOutputToFullBatchesBeforeAddingExistingStock() {
        var target = new InventoryTarget("minecraft:oak_planks", 3, 5, 4);
        assertEquals(2, target.batches()); assertEquals(8, target.plannedIncrement()); assertEquals(11, target.targetTotal());
    }
    @Test void executorTotalCanExceedTheWireIncrementLimit() {
        var target = new InventoryTarget("minecraft:oak_log", 4096, 4096, 1);
        assertEquals(8192, target.targetTotal());
    }
    @Test void overflowIsRejectedBeforeCreatingAnImpossibleExecutorTarget() {
        assertEquals("GAME_ITEM_TARGET_TOO_LARGE", assertThrows(Rejected.class,
                () -> new InventoryTarget("minecraft:oak_log", Integer.MAX_VALUE, 1, 1)).code);
        assertThrows(Rejected.class, () -> new InventoryTarget("minecraft:oak_planks", Integer.MAX_VALUE - 5, 5, 4));
    }
    @Test void negativeAndOverflowedObservedCountsAreRefused() {
        assertThrows(Rejected.class, () -> InventoryTarget.gather(goal, stock(-1)));
        var observed = stock(Integer.MAX_VALUE); observed.getAsJsonArray("inventory").add(obj("item_id", "minecraft:oak_log", "count", 1));
        assertThrows(Rejected.class, () -> InventoryTarget.gather(goal, observed));
    }
    @Test void unknownInventoryDoesNotBecomeAnEmptyBaseline() {
        assertThrows(Rejected.class, () -> InventoryTarget.gather(goal, new JsonObject()));
        assertThrows(Rejected.class, () -> InventoryTarget.gather(goal, obj("inventory", null)));
    }
    @Test void invalidIncrementsAndBatchSizesAreRefused() {
        for (int count : List.of(0, -1, 4097)) assertThrows(Rejected.class, () -> new InventoryTarget("minecraft:oak_log", 0, count, 1));
        for (int batch : List.of(0, -1, 4097)) assertThrows(Rejected.class, () -> new InventoryTarget("minecraft:oak_log", 0, 4, batch));
    }
}
