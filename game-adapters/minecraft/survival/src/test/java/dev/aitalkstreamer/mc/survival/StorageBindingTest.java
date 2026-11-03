package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Binding assertions inspect the actual offline-compiled pinned upstream tasks and native callbacks. */
class StorageBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> all(String name)throws Exception{return code.calls(name).values().stream().flatMap(List::stream).toList();}
    boolean calls(List<String> values,String marker){return values.stream().anyMatch(c->c.startsWith(marker));}
    @Test void actualPickupDelegatesTheTransferAndCompletionToOneControlledOwner()throws Exception{
        var methods=code.calls("adris/altoclef/tasks/container/PickupFromContainerTask");
        var opened=methods.get("onContainerOpenSubtask(Ladris/altoclef/AltoClef;Ladris/altoclef/trackers/storage/ContainerCache;)Ladris/altoclef/tasksystem/Task;");
        assertTrue(calls(opened,"dev/aitalkstreamer/mc/survival/ControlledStorage:opened"));assertFalse(calls(opened,"adris/altoclef/control/SlotHandler:clickSlot"));
        assertTrue(calls(methods.get("isFinished()Z"),"dev/aitalkstreamer/mc/survival/ControlledStorage:finished"));
    }
    @Test void actualDepositRemovesPredictedTrackerCompletionAndUncontrolledMoveTasks()throws Exception{
        var values=all("adris/altoclef/tasks/container/StoreInContainerTask");
        for(String name:List.of("prepare","opened","finished","stop"))assertTrue(calls(values,"dev/aitalkstreamer/mc/survival/ControlledStorage:"+name));
        assertFalse(calls(values,"adris/altoclef/tasks/container/ContainerStoredTracker:"));assertFalse(calls(values,"adris/altoclef/tasks/slot/MoveItemToSlotFromInventoryTask:"));
    }
    @Test void theActualDriverAndPacketCallbacksAdvanceTheStorageProtocol()throws Exception{
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1"),"dev/aitalkstreamer/mc/survival/ControlledStorage:checkpoint"));
        var methods=code.calls("dev/aitalkstreamer/mc/survival/SurvivalGameExecutor");
        assertTrue(calls(methods.get("clickRevision(I)I"),"dev/aitalkstreamer/mc/survival/ControlledStorage:clickRevision"));
        assertTrue(calls(methods.get("inventorySynchronized(Lnet/minecraft/network/packet/s2c/play/InventoryS2CPacket;)V"),"dev/aitalkstreamer/mc/survival/ControlledStorage:inventory"));
    }
    @Test void actualTaskAndChainCompletionWaitForThePendingContainerTransaction()throws Exception{
        assertTrue(calls(all("adris/altoclef/tasksystem/Task"),"dev/aitalkstreamer/mc/survival/ControlledStorage:retains"));
        assertTrue(calls(all("adris/altoclef/chains/SingleTaskChain"),"dev/aitalkstreamer/mc/survival/ControlledStorage:retains"));
        assertTrue(calls(all("adris/altoclef/tasksystem/TaskRunner"),"dev/aitalkstreamer/mc/survival/ControlledStorage:defers"));
    }
    @Test void everyGuiWriteSinkHonorsTheSamePendingStorageOwner()throws Exception{
        var methods=code.calls("dev/aitalkstreamer/mc/survival/SurvivalGui");
        for(var e:methods.entrySet())if(e.getKey().startsWith("lambda$slot$")||e.getKey().startsWith("lambda$recipe$")||e.getKey().startsWith("lambda$screen$")||e.getKey().startsWith("lambda$close$"))
            assertTrue(calls(e.getValue(),"dev/aitalkstreamer/mc/survival/ControlledStorage:guardGuiWrite"),e.getKey());
    }
    @Test void actualStorageChecksReservationsAndCreditsOnlyTheControlledLedger()throws Exception{
        var values=all("dev/aitalkstreamer/mc/survival/ControlledStorage");
        for(String marker:List.of("ResourceMaterials:removable","ResourceMaterials:usable","ResourceMaterials:externalUsable","StorageLedger:credit","StorageExchange:advance","SurvivalGui:storageSnapshot"))
            assertTrue(calls(values,"dev/aitalkstreamer/mc/survival/"+marker),marker);
    }
    @Test void doubleChestSiteChecksBothNativeBlockEntitiesAndTheConnectionDirection()throws Exception{
        var values=all("dev/aitalkstreamer/mc/survival/SurvivalGui$StorageSite");
        assertTrue(calls(values,"net/minecraft/block/ChestBlock:getFacing"));
        assertTrue(values.stream().filter(v->v.contains(":getBlockEntity(")).count()>=4);
        assertTrue(calls(values,"dev/aitalkstreamer/mc/survival/ControlledStorage:expects"));
    }
    @Test void openingProtectionAlsoBlocksEquipmentFoodShieldSupplyAndBacktracking()throws Exception{
        for(String name:List.of("ControlledEquipment","ControlledEatingTask","ControlledShield","ControlledSupplyTask","ResourceBranchRecovery"))
            assertTrue(calls(all("dev/aitalkstreamer/mc/survival/"+name),"dev/aitalkstreamer/mc/survival/ControlledStorage:blocksInventory"),name);
    }
    @Test void actualNearbyAndStashTasksRegisterOnlyConfirmedPositionFilteredCredits()throws Exception{
        for(String name:List.of("StoreInAnyContainerTask","StoreInStashTask")) {
            var values=all("adris/altoclef/tasks/container/"+name);
            assertTrue(calls(values,"dev/aitalkstreamer/mc/survival/ControlledStorage:watch"));
            assertTrue(calls(values,"dev/aitalkstreamer/mc/survival/ControlledStorage:unwatch"));
            assertFalse(calls(values,"adris/altoclef/tasks/container/ContainerStoredTracker:startTracking"));
        }
    }
    @Test void actualStoredTrackerNeverSubscribesToPredictedSlotChanges()throws Exception{
        var methods=code.calls("adris/altoclef/tasks/container/ContainerStoredTracker");
        assertFalse(calls(methods.get("startTracking()V"),"adris/altoclef/eventbus/EventBus:subscribe"));
        assertTrue(calls(methods.get("confirmed(Lnet/minecraft/item/Item;I)V"),"dev/aitalkstreamer/mc/survival/SurvivalAuthority:requireScope"));
        var remaining=methods.get("getUnstoredItemTargetsYouCanStore(Ladris/altoclef/AltoClef;[Ladris/altoclef/util/ItemTarget;)[Ladris/altoclef/util/ItemTarget;");
        assertFalse(calls(remaining,"adris/altoclef/trackers/storage/ItemStorage:hasItem"));
    }
}
