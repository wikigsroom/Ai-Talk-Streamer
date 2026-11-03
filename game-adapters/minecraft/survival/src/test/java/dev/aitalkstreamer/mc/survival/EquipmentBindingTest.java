package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import org.objectweb.asm.*;
import static org.junit.jupiter.api.Assertions.*;

/** Actual compiled shared equipment entry points and pinned native slot checks; no client acceptance. */
class EquipmentBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> all(String name)throws Exception{return code.calls(name).values().stream().flatMap(List::stream).toList();}
    boolean calls(List<String> values,String marker){return values.stream().anyMatch(c->c.startsWith(marker));}
    @Test void actualSharedHandOffhandDeequipAndRefreshEntriesUseOneControlledOwner()throws Exception{
        var methods=code.calls("adris/altoclef/control/SlotHandler");
        for(String method:List.of("forceEquipItem(Lnet/minecraft/item/Item;)Z","forceEquipItemToOffhand(Lnet/minecraft/item/Item;)V",
                "forceEquipItem(Ladris/altoclef/util/ItemTarget;Z)Z","forceEquipSlot(Ladris/altoclef/util/slots/Slot;)V",
                "forceDeequip(Ljava/util/function/Predicate;)Z","refreshInventory()V")){
            var entry=methods.get(method);assertNotNull(entry,method);assertTrue(calls(entry,"dev/aitalkstreamer/mc/survival/ControlledEquipment:"),method);
            assertFalse(calls(entry,"adris/altoclef/control/SlotHandler:clickSlotForce"),method);
        }
    }
    @Test void armorTaskPreservesAcquisitionButDropsItsOldThrowAndQuickMovePaths()throws Exception{
        var methods=code.calls("adris/altoclef/tasks/misc/EquipArmorTask");var tick=methods.get("onTick()Ladris/altoclef/tasksystem/Task;");
        assertTrue(calls(tick,"adris/altoclef/tasks/squashed/CataloguedResourceTask:<init>"));assertTrue(calls(tick,"dev/aitalkstreamer/mc/survival/ControlledEquipment:armor"));
        assertFalse(calls(tick,"adris/altoclef/tasks/slot/MoveItemToSlotFromInventoryTask:<init>"));assertFalse(calls(tick,"adris/altoclef/control/SlotHandler:clickSlot"));
        assertTrue(calls(methods.get("armorEquipped()Z"),"dev/aitalkstreamer/mc/survival/ControlledEquipment:busy"));
    }
    @Test void originalEquipmentCheckpointRunsBeforeAnyUpstreamChainAndRealRunnerDefersDependentTasks()throws Exception{
        var tick=code.calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1").get("tick()V");
        int checkpoint=tick.indexOf("dev/aitalkstreamer/mc/survival/ControlledEquipment:checkpoint()V");assertTrue(checkpoint>=0&&checkpoint<tick.indexOf("adris/altoclef/AltoClef:onClientTick()V"));
        assertTrue(calls(code.calls("adris/altoclef/tasksystem/TaskRunner").get("tick()V"),"dev/aitalkstreamer/mc/survival/ControlledEquipment:defers"));
    }
    @Test void pendingEquipmentDefersUserAndFoodChainsWhileOtherSurvivalChainsRemainEligible()throws Exception{
        var types=new HashSet<String>();new ClassReader(code.bytes("dev/aitalkstreamer/mc/survival/ControlledEquipment")).accept(new ClassVisitor(Opcodes.ASM9){
            public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e){if(!n.equals("defers"))return null;return new MethodVisitor(Opcodes.ASM9){public void visitTypeInsn(int opcode,String type){if(opcode==Opcodes.INSTANCEOF)types.add(type);}};}
        },ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);
        assertEquals(Set.of("adris/altoclef/chains/UserTaskChain","adris/altoclef/chains/FoodChain"),types);
    }
    @Test void fullServerInventoryAndRevisionHooksReachTheEquipmentExchangeWithoutPacketWrites()throws Exception{
        var executor=all("dev/aitalkstreamer/mc/survival/SurvivalGameExecutor");assertTrue(calls(executor,"dev/aitalkstreamer/mc/survival/ControlledEquipment:inventory"));
        assertTrue(calls(executor,"dev/aitalkstreamer/mc/survival/ControlledEquipment:clickRevision"));
        var packet=code.calls("dev/aitalkstreamer/mc/survival/ControlledEquipment").get("inventory(Lnet/minecraft/network/packet/s2c/play/InventoryS2CPacket;)V");
        assertTrue(calls(packet,"dev/aitalkstreamer/mc/survival/EquipmentExchange:confirm"));assertFalse(calls(packet,"dev/aitalkstreamer/mc/survival/SurvivalGui:slot"));
    }
    @Test void nativeSlotAdmissionUsesActualInsertTakeAndCapacityChecksWithExactComponents()throws Exception{
        var equipment=all("dev/aitalkstreamer/mc/survival/ControlledEquipment");
        for(String marker:List.of("net/minecraft/screen/slot/Slot:canTakeItems","net/minecraft/screen/slot/Slot:canInsert","net/minecraft/screen/slot/Slot:getMaxItemCount",
                "net/minecraft/item/ItemStack:areItemsAndComponentsEqual","dev/aitalkstreamer/mc/survival/SurvivalAuthority:owned","dev/aitalkstreamer/mc/survival/SurvivalGui:slot"))assertTrue(calls(equipment,marker),marker);
        assertFalse(calls(equipment,"net/minecraft/client/network/ClientPlayerInteractionManager:clickSlot"));
    }
    @Test void predictedEquipmentCannotEnterVanillaOrDirectGameplayAndOtherInventoryTransactions()throws Exception{
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalActions"),"dev/aitalkstreamer/mc/survival/ControlledEquipment:busy"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalGui"),"dev/aitalkstreamer/mc/survival/ControlledEquipment:guardGuiWrite"));
        for(String name:List.of("ControlledEatingTask","ControlledSupplyTask","SurvivalGameExecutor"))
            assertTrue(calls(all("dev/aitalkstreamer/mc/survival/"+name),"dev/aitalkstreamer/mc/survival/ControlledEquipment:busy"),name);
    }
    @Test void revokedEquipmentCleanupNeverMovesInventoryOrRestoresAFormerSelectedSlot()throws Exception{
        var cleanup=code.calls("dev/aitalkstreamer/mc/survival/ControlledEquipment").entrySet().stream().filter(e->e.getKey().startsWith("lambda$new$"))
                .flatMap(e->e.getValue().stream()).toList();assertTrue(calls(cleanup,"dev/aitalkstreamer/mc/survival/EquipmentExchange:close"));
        assertFalse(calls(cleanup,"dev/aitalkstreamer/mc/survival/SurvivalGui:slot"));assertFalse(calls(cleanup,"dev/aitalkstreamer/mc/survival/SurvivalInputs:select"));
    }
    @Test void genericOffhandItemsUseTheExactInventoryStackRatherThanAnArmorOnlySelector()throws Exception{
        var offhand=code.calls("dev/aitalkstreamer/mc/survival/ControlledEquipment").get("offhand(Lnet/minecraft/item/Item;)Z");
        assertTrue(calls(offhand,"net/minecraft/item/ItemStack:isOf"));
        assertTrue(calls(offhand,"dev/aitalkstreamer/mc/survival/ControlledEquipment:<init>(III)V"));
        assertFalse(calls(offhand,"dev/aitalkstreamer/mc/survival/ControlledEquipment:armor"));
    }
    @Test void anUpstreamSlotRetainsItsPlayerAndWindowIdentityUntilAdmission()throws Exception{
        var entry=code.calls("adris/altoclef/control/SlotHandler").get("forceEquipSlot(Ladris/altoclef/util/slots/Slot;)V");
        assertTrue(calls(entry,"dev/aitalkstreamer/mc/survival/ControlledEquipment:mainSlot(Ladris/altoclef/util/slots/Slot;)Z"));
        assertFalse(calls(entry,"adris/altoclef/util/slots/Slot:getInventorySlot"));
        var admission=code.calls("dev/aitalkstreamer/mc/survival/ControlledEquipment").get("mainSlot(Ladris/altoclef/util/slots/Slot;)Z");
        assertTrue(calls(admission,"adris/altoclef/util/slots/Slot:getWindowSlot"));
        assertTrue(calls(admission,"adris/altoclef/util/slots/Slot:getInventorySlot"));
    }
}
