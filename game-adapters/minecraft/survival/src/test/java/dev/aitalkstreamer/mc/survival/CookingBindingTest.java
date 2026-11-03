package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Real compiled upstream/bridge/Minecraft wiring, without claiming a running client or Mixin. */
class CookingBindingTest {
    final HeldNativeProtocolTest code = new HeldNativeProtocolTest();
    List<String> all(String name) throws Exception { return code.calls(name).values().stream().flatMap(List::stream).toList(); }
    boolean calls(List<String> calls, String prefix) { return calls.stream().anyMatch(value -> value.startsWith(prefix)); }
    @Test void theActualFoodTreeSelectsConfirmedCookingAndDefersItsCompletionUntilCleanup() throws Exception {
        var methods = code.calls("adris/altoclef/tasks/resources/CollectFoodTask");
        assertTrue(calls(methods.get("onTick()Ladris/altoclef/tasksystem/Task;"), "dev/aitalkstreamer/mc/survival/ControlledCookingTask:select"));
        // Only the unrelated currentResourceTask keeps an isActive condition. Cooking must
        // survive an upstream interruption while its raw stack is inside the container.
        assertEquals(1, methods.get("onTick()Ladris/altoclef/tasksystem/Task;").stream()
                .filter(value -> value.equals("adris/altoclef/tasksystem/Task:isActive()Z")).count());
        assertFalse(calls(all("adris/altoclef/tasks/resources/CollectFoodTask"), "adris/altoclef/tasks/container/SmeltInSmokerTask:<init>"));
        var finished = methods.get("isFinished()Z");
        assertTrue(finished.indexOf("dev/aitalkstreamer/mc/survival/ControlledCookingTask:busy()Z")
                < finished.indexOf("dev/aitalkstreamer/mc/survival/ControlledSupplyTask:inventoryNutrition()I"));
        assertTrue(calls(all("adris/altoclef/tasks/resources/CollectFoodTask"), "dev/aitalkstreamer/mc/survival/ControlledCookingTask:foodPotential"));
    }
    @Test void anActiveCookingChildRetainsFoodPriorityBeforeSelectionOrEating() throws Exception {
        var priority = code.calls("adris/altoclef/chains/FoodChain").get("getPriority()F");
        int busy = priority.indexOf("dev/aitalkstreamer/mc/survival/ControlledCookingTask:busy()Z");
        assertTrue(busy >= 0 && busy < priority.indexOf("adris/altoclef/chains/FoodChain:calculateFood(Ladris/altoclef/AltoClef;)Lnet/minecraft/util/Pair;"));
        var tick = code.calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1").get("tick()V");
        assertTrue(tick.indexOf("dev/aitalkstreamer/mc/survival/ControlledCookingTask:checkpoint()V")
                < tick.indexOf("adris/altoclef/AltoClef:onClientTick()V"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/ControlledSupplyTask"), "dev/aitalkstreamer/mc/survival/SupplyPolicy:observe(JLdev/aitalkstreamer/mc/survival/SupplyPolicy$Facts;Z)"));
    }
    @Test void authoritativeSlotPacketsReachTheOriginalExecutorThroughTheRealBridge() throws Exception {
        for (var route : List.of(
                new String[]{"dev/aitalkstreamer/mc/mixin/InventorySyncMixin", "dev/aitalkstreamer/mc/McBridgeClient:inventorySlotSynchronized"},
                new String[]{"dev/aitalkstreamer/mc/McBridgeClient", "dev/aitalkstreamer/mc/MinecraftPort:inventorySlotSynchronized"},
                new String[]{"dev/aitalkstreamer/mc/MinecraftPort", "dev/aitalkstreamer/mc/ClientExecutor:inventorySlotSynchronized"},
                new String[]{"dev/aitalkstreamer/mc/survival/SurvivalGameExecutor", "dev/aitalkstreamer/mc/survival/ControlledCookingTask:synchronizedSlot"}))
            assertTrue(calls(all(route[0]), route[1]), Arrays.toString(route));
        var packet = code.calls("net/minecraft/network/packet/s2c/play/ScreenHandlerSlotUpdateS2CPacket");
        assertTrue(packet.keySet().containsAll(Set.of("getSyncId()I", "getRevision()I", "getSlot()I", "getStack()Lnet/minecraft/item/ItemStack;")));
        assertTrue(code.calls("net/minecraft/client/network/ClientPlayNetworkHandler").keySet().contains(
                "onScreenHandlerSlotUpdate(Lnet/minecraft/network/packet/s2c/play/ScreenHandlerSlotUpdateS2CPacket;)V"));
    }
    @Test void actualCookingReadsRuntimeRecipesAndComponentsAndAllWritesUseTheOwnedGuiSink() throws Exception {
        var calls = all("dev/aitalkstreamer/mc/survival/ControlledCookingTask");
        for (String marker : List.of("net/minecraft/recipe/RecipeManager:getFirstMatch", "net/minecraft/item/ItemStack:areItemsAndComponentsEqual",
                "adris/altoclef/BotBehaviour:isProtected", "dev/aitalkstreamer/mc/survival/SurvivalAuthority:owned",
                "dev/aitalkstreamer/mc/survival/CookingExchange:send", "dev/aitalkstreamer/mc/survival/SurvivalGui:slot"))
            assertTrue(calls(calls, marker), marker);
        assertFalse(calls(calls, "net/minecraft/client/network/ClientPlayerInteractionManager:clickSlot"));
        assertFalse(calls(calls, "net/minecraft/client/network/ClientPlayerEntity:closeHandledScreen"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalGui"), "dev/aitalkstreamer/mc/survival/ControlledCookingTask:guardGuiWrite"));
    }
    @Test void cancelledCookingDoesNotCloseMenusOrMoveInventoryDuringTreeCleanup() throws Exception {
        var methods = code.calls("dev/aitalkstreamer/mc/survival/ControlledCookingTask");
        assertEquals(List.of(), methods.get("onStop(Ladris/altoclef/tasksystem/Task;)V"));
        var packets = methods.entrySet().stream().filter(e -> e.getKey().startsWith("synchronized"))
                .flatMap(e -> e.getValue().stream()).toList();
        assertFalse(calls(packets, "dev/aitalkstreamer/mc/survival/SurvivalAuthority:write"));
        assertFalse(calls(packets, "dev/aitalkstreamer/mc/survival/SurvivalGui:slot"));
    }
}
