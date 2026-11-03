package dev.aitalkstreamer.mc.survival;

import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Inspects real compiled upstream wiring; it does not initialize Minecraft or prove server effects. */
class SupplyBindingTest {
    final HeldNativeProtocolTest bytecode=new HeldNativeProtocolTest();
    @Test void theActualFoodChainSelectsTheOriginalOwnedSupplyTree() throws Exception {
        var priority=bytecode.calls("adris/altoclef/chains/FoodChain").get("getPriority()F");
        assertTrue(priority.stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/ControlledSupplyTask:select")));
        assertFalse(priority.stream().anyMatch(c->c.startsWith("adris/altoclef/tasks/resources/CollectFoodTask:<init>")));
        assertTrue(priority.stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/SupplyPolicy:validateSettings")));
    }
    @Test void theActualTaskRetainsTheRealCollectionChildOwnerAndOriginalClock() throws Exception {
        var methods=bytecode.calls("dev/aitalkstreamer/mc/survival/ControlledSupplyTask");
        var all=methods.values().stream().flatMap(List::stream).toList();
        assertTrue(all.contains("adris/altoclef/tasks/resources/CollectFoodTask:<init>(D)V"));
        for(String marker:List.of("SurvivalAuthority:owned","SurvivalAuthority:session","SupplyPolicy:observe"))
            assertTrue(all.stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/"+marker)),marker);
        assertFalse(methods.get("onStart()V").stream().anyMatch(c->c.contains("SupplyPolicy:<init>")));
        var tick=bytecode.calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1").get("tick()V");
        assertTrue(tick.indexOf("dev/aitalkstreamer/mc/survival/ControlledSupplyTask:checkpoint()V")>=0);
        assertTrue(tick.indexOf("dev/aitalkstreamer/mc/survival/ControlledSupplyTask:checkpoint()V")
                <tick.indexOf("adris/altoclef/AltoClef:onClientTick()V"));
    }
    @Test void collectionAdmissionReadsRealStockRatherThanTheProtectedConsumptionScore() throws Exception {
        var priority=bytecode.calls("adris/altoclef/chains/FoodChain").get("getPriority()F");
        int stock=priority.indexOf("dev/aitalkstreamer/mc/survival/ControlledSupplyTask:inventoryNutrition()I");
        int admission=priority.indexOf("dev/aitalkstreamer/mc/survival/SupplyPolicy:needsCollection(IIIZ)Z");
        assertTrue(stock>=0 && admission>stock);
        assertEquals(1,priority.stream().filter(c->c.startsWith("dev/aitalkstreamer/mc/survival/ControlledSupplyTask:select")).count());
    }
    @Test void foodSelectionUsesActualStackComponentsAndRechecksTheEquippedStack() throws Exception {
        var chain=bytecode.calls("adris/altoclef/chains/FoodChain");
        var calculate=chain.get("calculateFood(Ladris/altoclef/AltoClef;)Lnet/minecraft/util/Pair;");
        assertTrue(calculate.stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/ControlledSupplyTask:allowedFood")));
        assertFalse(calculate.stream().anyMatch(c->c.startsWith("adris/altoclef/multiversion/item/ItemVer:getFoodComponent")));
        var start=chain.get("startEat(Ladris/altoclef/AltoClef;Lnet/minecraft/item/Item;)V");
        assertTrue(start.stream().anyMatch(c->c.contains("ControlledEatingTask:select")));
        assertFalse(start.stream().anyMatch(c->c.contains("InputControls:hold") || c.contains("SlotHandler:forceEquipItem")));
        var eating=bytecode.calls("dev/aitalkstreamer/mc/survival/ControlledEatingTask").get("onTick()Ladris/altoclef/tasksystem/Task;");
        int check=-1,use=-1;
        for(int i=0;i<eating.size();i++) {
            if(eating.get(i).contains("ControlledEatingTask:canEat"))check=i;
            if(eating.get(i).contains("SurvivalActions:interactItem"))use=i;
        }
        assertTrue(check>=0 && use>check);
    }
    @Test void foodResourceConversionsUseFiniteTargetsAndNativeInventoryCompletion() throws Exception {
        var methods=bytecode.calls("adris/altoclef/tasks/resources/CollectFoodTask");
        var tick=methods.get("onTick()Ladris/altoclef/tasksystem/Task;");
        for(String helper:List.of("breadTarget","wheatTarget"))
            assertTrue(tick.stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/SupplyPolicy:"+helper)));
        assertTrue(methods.get("isFinished()Z").stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/ControlledSupplyTask:inventoryNutrition")));
    }
}
