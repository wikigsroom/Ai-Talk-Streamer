package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import org.objectweb.asm.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ResourceCraftBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> all(String n)throws Exception{return code.calls(n).values().stream().flatMap(List::stream).toList();}
    boolean calls(List<String> list,String prefix){return list.stream().anyMatch(s->s.startsWith(prefix));}
    @Test void actualInventoryCraftUsesAConfirmedChildAndPreservesItsVirtualMaterialCollector()throws Exception{
        var methods=code.calls("adris/altoclef/tasks/CraftInInventoryTask");var tick=methods.get("onResourceTick(Ladris/altoclef/AltoClef;)Ladris/altoclef/tasksystem/Task;");
        assertTrue(calls(tick,"dev/aitalkstreamer/mc/survival/ControlledResourceCraftTask:<init>"));
        assertTrue(calls(all("adris/altoclef/tasks/CraftInInventoryTask"),"adris/altoclef/tasks/CraftInInventoryTask:collectRecipeSubTask"));
        for(String old:List.of("adris/altoclef/tasks/CraftGenericManuallyTask:","adris/altoclef/tasks/CraftGenericWithRecipeBooksTask:","adris/altoclef/tasks/slot/ReceiveCraftingOutputSlotTask:"))assertFalse(calls(tick,old));
    }
    @Test void actualTableConstructorsRetainTargetArraysAndCollectOptionsWithTheNewChild()throws Exception{
        var calls=all("adris/altoclef/tasks/container/CraftInTableTask");assertEquals(2,calls.stream().filter(s->s.startsWith("dev/aitalkstreamer/mc/survival/ControlledResourceCraftTask:<init>")).count());
        assertFalse(calls(calls,"adris/altoclef/tasks/container/DoCraftInTableTask:<init>"));
    }
    @Test void bothWrappersStopDiscardingOrRearrangingUnknownCursorItems()throws Exception{
        for(String name:List.of("adris/altoclef/tasks/CraftInInventoryTask","adris/altoclef/tasks/container/CraftInTableTask")){
            var methods=code.calls(name);
            for(String key:List.of("onResourceStart(Ladris/altoclef/AltoClef;)V","onResourceStop(Ladris/altoclef/AltoClef;Ladris/altoclef/tasksystem/Task;)V"))
                for(String forbidden:List.of("adris/altoclef/control/SlotHandler:clickSlot","adris/altoclef/util/helpers/StorageHelper:closeScreen","net/minecraft/client/network/ClientPlayerEntity:closeHandledScreen"))assertFalse(calls(methods.get(key),forbidden));
        }
    }
    @Test void actualParentTicksAndRootFinishChecksRespectTheConfirmedDescendant()throws Exception{
        assertTrue(calls(code.calls("adris/altoclef/tasksystem/Task").get("tick(Ladris/altoclef/tasksystem/TaskChain;)V"),"dev/aitalkstreamer/mc/survival/ConfirmedCraftTask:retains"));
        assertTrue(calls(code.calls("adris/altoclef/chains/SingleTaskChain").get("onTick()V"),"dev/aitalkstreamer/mc/survival/ConfirmedCraftTask:retains"));
        assertTrue(calls(code.calls("dev/aitalkstreamer/mc/survival/ConfirmedCraftTask").get("retains(Ladris/altoclef/tasksystem/Task;)Z"),"adris/altoclef/tasksystem/Task:thisOrChildSatisfies"));
    }
    @Test void nativeResourceCaptureReadsCurrentServerRecipesAndActualStockWithoutTheOldGlobalRecipeCache()throws Exception{
        var capture=code.calls("dev/aitalkstreamer/mc/survival/CraftSpec").get("captureResource(Ladris/altoclef/util/RecipeTarget;)Ldev/aitalkstreamer/mc/survival/CraftSpec;");
        for(String prefix:List.of("dev/aitalkstreamer/mc/survival/SurvivalAuthority:requireScope","net/minecraft/client/network/ClientPlayNetworkHandler:getRecipeManager","net/minecraft/recipe/RecipeManager:values","dev/aitalkstreamer/mc/survival/ResourceRecipePlan:select","adris/altoclef/util/RecipeTarget:getTargetCount"))assertTrue(calls(capture,prefix),prefix);
        assertFalse(calls(capture,"adris/altoclef/util/JankCraftingRecipeMapping:"));
    }
    @Test void materialAcquisitionAndTableCreationRunInsideTheSameRoot()throws Exception{
        var all=all("dev/aitalkstreamer/mc/survival/ControlledResourceCraftTask");
        for(String prefix:List.of("dev/aitalkstreamer/mc/survival/SurvivalAuthority:session","adris/altoclef/tasks/resources/CollectRecipeCataloguedResourcesTask:<init>","java/util/function/Supplier:get","dev/aitalkstreamer/mc/survival/ConfirmedCraftTask:<init>"))assertTrue(calls(all,prefix),prefix);
        assertFalse(calls(all,"dev/aitalkstreamer/mc/survival/SurvivalAuthority:open"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/ControlledResourceCraftTask$OpenTable"),"adris/altoclef/tasks/container/DoStuffInContainerTask:<init>"));
    }
    @Test void foodDoesNotBorrowAnActiveCraftingCursorAndDeadlinesAreCheckedBeforeUpstreamTicks()throws Exception{
        assertTrue(calls(code.calls("adris/altoclef/chains/FoodChain").get("getPriority()F"),"dev/aitalkstreamer/mc/survival/ConfirmedCraftTask:busy"));
        var tick=code.calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1").get("tick()V");
        assertTrue(tick.indexOf("dev/aitalkstreamer/mc/survival/ConfirmedCraftTask:checkpoint()V")<tick.indexOf("adris/altoclef/AltoClef:onClientTick()V"));
    }
    @Test void remainingAllocatedMaterialsAreCheckedWithoutFreezingEveryUnrelatedStack()throws Exception{
        var tick=code.calls("dev/aitalkstreamer/mc/survival/ConfirmedCraftTask").get("onTick()Ladris/altoclef/tasksystem/Task;");
        assertTrue(calls(tick,"dev/aitalkstreamer/mc/survival/CraftPlan:remainingBySlot"));assertTrue(calls(tick,"net/minecraft/item/ItemStack:areItemsAndComponentsEqual"));
        assertFalse(calls(tick,"net/minecraft/item/ItemStack:areEqual"));
    }
    @Test void evenTheLastBatchClosesItsOwnedConfirmedEmptyScreenBeforeSettingFinished()throws Exception{
        var events=new ArrayList<String>();new ClassReader(code.bytes("dev/aitalkstreamer/mc/survival/ConfirmedCraftTask")).accept(new ClassVisitor(Opcodes.ASM9){public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e){if(!n.equals("onTick"))return null;return new MethodVisitor(Opcodes.ASM9){public void visitMethodInsn(int o,String w,String n,String d,boolean i){if(w.equals("dev/aitalkstreamer/mc/survival/SurvivalGui")&&n.equals("close"))events.add("close");}public void visitFieldInsn(int o,String w,String n,String d){if(o==Opcodes.PUTFIELD&&n.equals("finished"))events.add("finished");}};}},ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);
        assertEquals(List.of("close","finished"),events);
    }
    @Test void stoppingTheInternalChildCannotMoveOrDiscardCursorItems()throws Exception{
        var stop=code.calls("dev/aitalkstreamer/mc/survival/ControlledResourceCraftTask").get("onStop(Ladris/altoclef/tasksystem/Task;)V");
        for(String prefix:List.of("dev/aitalkstreamer/mc/survival/SurvivalGui:","dev/aitalkstreamer/mc/survival/SurvivalActions:","dev/aitalkstreamer/mc/survival/SurvivalInputs:"))assertFalse(calls(stop,prefix));
    }
}
