package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Checks the actual compiled upstream wrappers, original packet route and task retention. */
class SmeltingBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> all(String name)throws Exception{return code.calls(name).values().stream().flatMap(List::stream).toList();}
    boolean has(List<String> calls,String prefix){return calls.stream().anyMatch(s->s.startsWith(prefix));}
    @Test void allThreeActualWorkstationWrappersConstructTheConfirmedResourceChild()throws Exception {
        for(String name:List.of("SmeltInFurnaceTask","SmeltInBlastFurnaceTask","SmeltInSmokerTask")) {
            var calls=all("adris/altoclef/tasks/container/"+name);
            assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledSmeltingTask:<init>"),name);
            assertFalse(has(calls,"adris/altoclef/tasks/container/"+name+"$Do"+name+":<init>"),name);
        }
    }
    @Test void wrappersWaitForChildCleanupAndNoLongerDropOrMoveCursorStacksOnStop()throws Exception {
        for(String name:List.of("SmeltInFurnaceTask","SmeltInBlastFurnaceTask","SmeltInSmokerTask")) {
            var methods=code.calls("adris/altoclef/tasks/container/"+name);
            assertTrue(has(methods.get("isFinished()Z"),"dev/aitalkstreamer/mc/survival/ControlledSmeltingTask:isFinished"));
            var stop=methods.get("onResourceStop(Ladris/altoclef/AltoClef;Ladris/altoclef/tasksystem/Task;)V");
            assertFalse(has(stop,"adris/altoclef/util/helpers/StorageHelper:"));assertFalse(has(stop,"adris/altoclef/control/SlotHandler:"));
        }
    }
    @Test void resourceSmeltingUsesTheOriginalRootReservationsAndBoundedMaterialCollector()throws Exception {
        var calls=all("dev/aitalkstreamer/mc/survival/ControlledSmeltingTask");
        for(String method:List.of("enter","leave","conversionFuel","select"))assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ResourceMaterials:"+method));
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask:<init>"));assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledCookingTask:resource"));
        assertFalse(has(calls,"dev/aitalkstreamer/mc/survival/SurvivalAuthority:open"));
    }
    @Test void nativeRecipesAndFuelTimesDetermineTheActualConversion()throws Exception {
        var calls=all("dev/aitalkstreamer/mc/survival/ControlledSmeltingTask");
        assertTrue(has(calls,"net/minecraft/block/entity/AbstractFurnaceBlockEntity:createFuelTimeMap"));
        assertTrue(has(calls,"net/minecraft/recipe/AbstractCookingRecipe:craft"));assertTrue(has(calls,"net/minecraft/item/Item:hasRecipeRemainder"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/CookingWorkstation"),"net/minecraft/recipe/RecipeManager:getFirstMatch"));
    }
    @Test void openingInventoryComesFromTheActualFullPacketBeforeAResourceTransactionExists()throws Exception {
        var packet=code.calls("dev/aitalkstreamer/mc/survival/SurvivalGameExecutor").get("inventorySynchronized(Lnet/minecraft/network/packet/s2c/play/InventoryS2CPacket;)V");
        assertTrue(has(packet,"dev/aitalkstreamer/mc/survival/SurvivalGui:synchronizedInventory"));
        var calls=all("dev/aitalkstreamer/mc/survival/ControlledCookingTask");assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/SurvivalGui:furnaceSnapshot"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/SurvivalGui"),"net/minecraft/network/packet/s2c/play/InventoryS2CPacket:getContents"));
    }
    @Test void eachExactNativeMenuAndRecipeTypeIsPresentInTheCompiledAdapter()throws Exception {
        String bytes=new String(code.bytes("dev/aitalkstreamer/mc/survival/CookingWorkstation"),java.nio.charset.StandardCharsets.ISO_8859_1);
        for(String name:List.of("FurnaceScreenHandler","BlastFurnaceScreenHandler","SmokerScreenHandler","FurnaceScreen","BlastFurnaceScreen","SmokerScreen","SMELTING","BLASTING","SMOKING"))assertTrue(bytes.contains(name),name);
    }
    @Test void actualTaskAndChainCompletionRetainTheCookingPath()throws Exception {
        for(String name:List.of("adris/altoclef/tasksystem/Task","adris/altoclef/chains/SingleTaskChain"))assertTrue(has(all(name),"dev/aitalkstreamer/mc/survival/ControlledCookingTask:retains"));
    }
    @Test void foodDistinguishesItsOwnCraftingAndCookingFromAResourceFurnace()throws Exception {
        var priority=code.calls("adris/altoclef/chains/FoodChain").get("getPriority()F");
        for(String route:List.of("dev/aitalkstreamer/mc/survival/SurvivalGui:furnaceOpen","dev/aitalkstreamer/mc/survival/ControlledCookingTask:supplyBusy","dev/aitalkstreamer/mc/survival/ControlledSupplyTask:retainsCraft"))assertTrue(has(priority,route));
    }
    @Test void workstationPreparationCanUseEquipmentAndCraftingUntilTheFurnaceInventoryIsOwned()throws Exception {
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ControlledEquipment"),"dev/aitalkstreamer/mc/survival/ControlledCookingTask:blocksInventory"));
        assertTrue(has(all("dev/aitalkstreamer/mc/survival/ControlledResourceCraftTask"),"dev/aitalkstreamer/mc/survival/ControlledCookingTask:blocksInventory"));
        assertFalse(has(code.calls("dev/aitalkstreamer/mc/survival/ControlledSmeltingTask").get("onStop(Ladris/altoclef/tasksystem/Task;)V"),"dev/aitalkstreamer/mc/survival/SurvivalGui:"));
    }
}
