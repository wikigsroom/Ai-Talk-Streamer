package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Actual compiled upstream, bridge and pinned vanilla calls; no real Mixin/client acceptance. */
class EatingBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> all(String name)throws Exception{return code.calls(name).values().stream().flatMap(List::stream).toList();}
    boolean calls(List<String> values,String marker){return values.stream().anyMatch(s->s.startsWith(marker));}
    @Test void actualFoodChainUsesTheOwnedChildAndDoesNotForceEquipOrHoldAnAsyncUse()throws Exception{
        var chain=code.calls("adris/altoclef/chains/FoodChain");var start=chain.get("startEat(Ladris/altoclef/AltoClef;Lnet/minecraft/item/Item;)V");
        assertTrue(calls(start,"dev/aitalkstreamer/mc/survival/ControlledEatingTask:select"));
        for(String forbidden:List.of("adris/altoclef/control/SlotHandler:forceEquipItem","adris/altoclef/control/InputControls:hold"))assertFalse(calls(start,forbidden));
        var priority=chain.get("getPriority()F");assertTrue(priority.indexOf("dev/aitalkstreamer/mc/survival/ControlledEatingTask:busy()Z")
                <priority.indexOf("adris/altoclef/chains/FoodChain:calculateFood(Ladris/altoclef/AltoClef;)Lnet/minecraft/util/Pair;"));
        var stop=chain.get("stopEat()V");assertEquals(List.of("dev/aitalkstreamer/mc/survival/ControlledEatingTask:interrupt()V"),stop);
    }
    @Test void originalOwnerAndBudgetSurviveTaskResetsAndAreCheckedBeforeUpstreamTicks()throws Exception{
        var eating=code.calls("dev/aitalkstreamer/mc/survival/ControlledEatingTask");
        assertFalse(calls(eating.get("onStart()V"),"dev/aitalkstreamer/mc/survival/EatingBudget:<init>"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/ControlledEatingTask"),"dev/aitalkstreamer/mc/survival/SurvivalAuthority:owned"));
        var tick=code.calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1").get("tick()V");
        int checkpoint=tick.indexOf("dev/aitalkstreamer/mc/survival/ControlledEatingTask:checkpoint()V");assertTrue(checkpoint>=0&&checkpoint<tick.indexOf("adris/altoclef/AltoClef:onClientTick()V"));
    }
    @Test void equippedFoodUsesExactlyOneOwnedMainHandRequestAndTheInventoryResyncSink()throws Exception{
        var eating=code.calls("dev/aitalkstreamer/mc/survival/ControlledEatingTask");var tick=eating.get("onTick()Ladris/altoclef/tasksystem/Task;");
        assertEquals(1,tick.stream().filter(c->c.startsWith("dev/aitalkstreamer/mc/survival/SurvivalActions:interactItem")).count());
        for(String marker:List.of("dev/aitalkstreamer/mc/survival/EatingBudget:issue","dev/aitalkstreamer/mc/survival/SurvivalInputs:select","dev/aitalkstreamer/mc/core/InventoryExchange:confirmedState"))assertTrue(calls(tick,marker),marker);
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/ControlledEatingTask"),"dev/aitalkstreamer/mc/survival/SurvivalGui:slot"));
        assertFalse(calls(all("dev/aitalkstreamer/mc/survival/ControlledEatingTask"),"net/minecraft/client/network/ClientPlayerInteractionManager:clickSlot"));
    }
    @Test void actualHealthAndFullInventoryPacketsReachTheOriginalEatingTaskReadOnly()throws Exception{
        for(var route:List.of(new String[]{"dev/aitalkstreamer/mc/mixin/ItemUseSyncMixin","dev/aitalkstreamer/mc/McBridgeClient:itemHealth"},
                new String[]{"dev/aitalkstreamer/mc/McBridgeClient","dev/aitalkstreamer/mc/MinecraftPort:itemHealth"},
                new String[]{"dev/aitalkstreamer/mc/MinecraftPort","dev/aitalkstreamer/mc/ClientExecutor:itemHealth"},
                new String[]{"dev/aitalkstreamer/mc/survival/SurvivalGameExecutor","dev/aitalkstreamer/mc/survival/ControlledEatingTask:health"},
                new String[]{"dev/aitalkstreamer/mc/survival/SurvivalGameExecutor","dev/aitalkstreamer/mc/survival/ControlledEatingTask:inventory"}))assertTrue(calls(all(route[0]),route[1]),Arrays.toString(route));
        var eating=code.calls("dev/aitalkstreamer/mc/survival/ControlledEatingTask");
        for(String method:List.of("health(I)V","inventory(Lnet/minecraft/network/packet/s2c/play/InventoryS2CPacket;)V")){
            assertFalse(calls(eating.get(method),"dev/aitalkstreamer/mc/survival/SurvivalAuthority:write"));
            assertFalse(calls(eating.get(method),"dev/aitalkstreamer/mc/survival/SurvivalGui:slot"));
        }
    }
    @Test void vanillaRepeatSuppressionIncludesTheChildButAllowsAnInterruptedEmergencyUse()throws Exception{
        assertTrue(calls(all("dev/aitalkstreamer/mc/MinecraftPort"),"dev/aitalkstreamer/mc/ClientExecutor:ownsUseTransaction"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalGameExecutor"),"dev/aitalkstreamer/mc/survival/ControlledEatingTask:blocksRepeatedUse"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalActions"),"dev/aitalkstreamer/mc/survival/ControlledEatingTask:guardItemUse"));
        assertTrue(calls(code.calls("dev/aitalkstreamer/mc/survival/ControlledEatingTask").get("onStop(Ladris/altoclef/tasksystem/Task;)V"),"dev/aitalkstreamer/mc/survival/ControlledEatingTask:interrupt"));
    }
    @Test void thePinnedVanillaFoodPathAndHoneyOverrideReallyInsertTheirRemainders()throws Exception{
        for(var route:List.of(new String[]{"net/minecraft/entity/player/PlayerEntity","net/minecraft/entity/player/HungerManager:eat"},
                new String[]{"net/minecraft/entity/player/PlayerEntity","net/minecraft/component/type/FoodComponent:usingConvertsTo"},
                new String[]{"net/minecraft/entity/player/PlayerEntity","net/minecraft/entity/player/PlayerInventory:insertStack"},
                new String[]{"net/minecraft/item/HoneyBottleItem","net/minecraft/entity/player/PlayerInventory:insertStack"},
                new String[]{"net/minecraft/entity/player/PlayerInventory","net/minecraft/entity/player/PlayerInventory:getEmptySlot"}))assertTrue(calls(all(route[0]),route[1]),Arrays.toString(route));
    }
    @Test void supplyAndNormalCompletionWaitForFoodInventoryRestoration()throws Exception{
        for(String name:List.of("dev/aitalkstreamer/mc/survival/ControlledSupplyTask","dev/aitalkstreamer/mc/survival/SurvivalGui","adris/altoclef/tasks/resources/CollectFoodTask"))
            assertTrue(calls(all(name),"dev/aitalkstreamer/mc/survival/ControlledEatingTask:busy"),name);
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalGui"),"dev/aitalkstreamer/mc/survival/ControlledEatingTask:guardGuiWrite"));
    }
    @Test void evenALocallyFinishedBiteSendsItsOwnedNativeStopBeforeReadingZeroEffect()throws Exception{
        var release=code.calls("dev/aitalkstreamer/mc/survival/ControlledEatingTask").get("releaseUse()V");
        assertTrue(calls(release,"dev/aitalkstreamer/mc/survival/SurvivalActions:stopFoodUse"));
        assertFalse(calls(release,"dev/aitalkstreamer/mc/survival/SurvivalActions:stopUsing"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalActions"),"dev/aitalkstreamer/mc/survival/ControlledEatingTask:guardFoodStop"));
        var nativeStop=code.calls("net/minecraft/client/network/ClientPlayerInteractionManager").get("stopUsingItem(Lnet/minecraft/entity/player/PlayerEntity;)V");
        assertTrue(calls(nativeStop,"net/minecraft/network/packet/c2s/play/PlayerActionC2SPacket:<init>"));
        assertTrue(calls(nativeStop,"net/minecraft/client/network/ClientPlayNetworkHandler:sendPacket"));
    }
}
