package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class MaterialUseBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> method(String name,String prefix)throws Exception {return code.calls(name).entrySet().stream().filter(e->e.getKey().startsWith(prefix)).findFirst().orElseThrow().getValue();}
    List<String> own(String prefix)throws Exception {return method("dev/aitalkstreamer/mc/survival/ControlledMaterialUse",prefix);}
    boolean has(List<String> calls,String prefix) {return calls.stream().anyMatch(c->c.startsWith(prefix));}
    @Test void allThreeCompiledGarbageRankingBranchesFilterWholeStackCapacity()throws Exception {
        var calls=method("adris/altoclef/util/helpers/StorageHelper","getGarbageSlot(");
        assertEquals(3,calls.stream().filter(c->c.startsWith("dev/aitalkstreamer/mc/survival/ControlledMaterialUse:disposable")).count());
    }
    @Test void actualBuilderAndThrowawayCountsUseJointCapacityInsteadOfWholeInventoryCounts()throws Exception {
        for(String prefix:List.of("getNumberOfThrowawayBlocks(","getBuildingMaterialCount(")) {
            var calls=method("adris/altoclef/util/helpers/StorageHelper",prefix);
            assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ControlledMaterialUse:throwawayCount"));
            assertFalse(has(calls,"adris/altoclef/trackers/storage/ItemStorageTracker:getItemCount"));
        }
        assertTrue(has(method("adris/altoclef/tasks/construction/PlaceBlockTask","getMaterialCount("),"dev/aitalkstreamer/mc/survival/ControlledMaterialUse:structureCount"));
    }
    @Test void actualThrowawaySelectionUsesCapacityAndOriginalImportancePolicy()throws Exception {
        assertTrue(has(method("adris/altoclef/util/helpers/StorageHelper","getSlotWithThrowawayBlock(Ladris/altoclef/AltoClef;Z)"),"dev/aitalkstreamer/mc/survival/ControlledMaterialUse:throwawaySlot"));
        var calls=own("throwawaySlot(");
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ResourceMaterials:consumable"));
        assertTrue(has(calls,"adris/altoclef/util/helpers/ItemHelper:canThrowAwayStack"));
    }
    @Test void bothDirectAndSyntheticBlockUseCheckTheActualHeldMaterial()throws Exception {
        var direct=code.calls("dev/aitalkstreamer/mc/survival/SurvivalGui").entrySet().stream().filter(e->e.getKey().startsWith("lambda$block$")).findFirst().orElseThrow().getValue();
        assertTrue(has(direct,"dev/aitalkstreamer/mc/survival/ControlledMaterialUse:beforeBlock"));
        assertTrue(has(method("dev/aitalkstreamer/mc/survival/SurvivalGui","beforeUse("),"dev/aitalkstreamer/mc/survival/ControlledMaterialUse:beforeBlockHands"));
        assertTrue(has(own("beforeBlock("),"dev/aitalkstreamer/mc/survival/ResourceMaterials:removable"));
        assertTrue(has(own("beforeBlock("),"dev/aitalkstreamer/mc/survival/ResourceMaterials:externalUsable"));
    }
    @Test void everyRoutedGuiClickChecksActualDropContentsBeforeTheNativeClick()throws Exception {
        var calls=method("dev/aitalkstreamer/mc/survival/SurvivalGui","slot(");
        int guard=-1,nativeClick=-1;
        for(int i=0;i<calls.size();i++) {
            if(calls.get(i).startsWith("dev/aitalkstreamer/mc/survival/ControlledMaterialUse:beforeDrop"))guard=i;
            if(calls.get(i).startsWith("net/minecraft/client/network/ClientPlayerInteractionManager:clickSlot"))nativeClick=i;
        }
        // The lambda body contains the actual guarded native write.
        if(guard<0) {
            var all=code.calls("dev/aitalkstreamer/mc/survival/SurvivalGui").values();
            calls=all.stream().filter(c->has(c,"dev/aitalkstreamer/mc/survival/ControlledMaterialUse:beforeDrop")).findFirst().orElseThrow();
            for(int i=0;i<calls.size();i++) {
                if(calls.get(i).startsWith("dev/aitalkstreamer/mc/survival/ControlledMaterialUse:beforeDrop"))guard=i;
                if(calls.get(i).startsWith("net/minecraft/client/network/ClientPlayerInteractionManager:clickSlot"))nativeClick=i;
            }
        }
        assertTrue(guard>=0 && nativeClick>guard);
    }
    @Test void noMaterialSelectionHelperCreatesAnIndependentWriteOrNewOwner()throws Exception {
        var calls=code.calls("dev/aitalkstreamer/mc/survival/ControlledMaterialUse").values().stream().flatMap(List::stream).toList();
        for(String forbidden:List.of("dev/aitalkstreamer/mc/survival/SurvivalAuthority:open","net/minecraft/client/network/ClientPlayerInteractionManager:clickSlot","net/minecraft/client/network/ClientPlayerInteractionManager:interactBlock"))assertFalse(has(calls,forbidden));
    }
}
