package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import org.objectweb.asm.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Inspects the actual prepared upstream, native MC and compiled bridge, without starting a game. */
class ShieldBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> all(String name)throws Exception{return code.calls(name).values().stream().flatMap(List::stream).toList();}
    boolean calls(List<String> c,String prefix){return c.stream().anyMatch(s->s.startsWith(prefix));}
    @Test void bothActualUpstreamShieldEntrypointsUseOwnedDemandsWithoutMovingMainhandOrCursor()throws Exception{
        for(String name:List.of("adris/altoclef/chains/MobDefenseChain","adris/altoclef/control/KillAura")){
            var methods=code.calls(name);var start=methods.get("startShielding(Ladris/altoclef/AltoClef;)V");var stop=methods.get("stopShielding(Ladris/altoclef/AltoClef;)V");
            assertTrue(calls(start,"dev/aitalkstreamer/mc/survival/ControlledShield:request"));assertTrue(calls(stop,"dev/aitalkstreamer/mc/survival/ControlledShield:withdraw"));
            for(var list:List.of(start,stop))for(String forbidden:List.of("adris/altoclef/control/SlotHandler:clickSlot","adris/altoclef/control/InputControls:hold","adris/altoclef/control/InputControls:release","adris/altoclef/util/helpers/StorageHelper:getGarbageSlot"))assertFalse(calls(list,forbidden),forbidden);
        }
    }
    @Test void rootTickCollectsFreshDemandAroundTheActualUpstreamTick()throws Exception{
        var tick=code.calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1").get("tick()V");
        assertTrue(tick.indexOf("dev/aitalkstreamer/mc/survival/ControlledShield:beginTick()V")<tick.indexOf("adris/altoclef/AltoClef:onClientTick()V"));
        assertTrue(tick.indexOf("dev/aitalkstreamer/mc/survival/ControlledShield:endTick()V")>tick.indexOf("adris/altoclef/AltoClef:onClientTick()V"));
        assertTrue(calls(all("adris/altoclef/tasksystem/TaskRunner"),"dev/aitalkstreamer/mc/survival/ControlledShield:defers"));
    }
    @Test void nativeShieldStartUsesOnlyOffhandAndTheSoleTypedActionPort()throws Exception{
        var start=code.calls("dev/aitalkstreamer/mc/survival/ControlledShield").get("start()V");assertTrue(calls(start,"dev/aitalkstreamer/mc/survival/SurvivalActions:interactItem"));
        var hands=new HashSet<String>();new ClassReader(code.bytes("dev/aitalkstreamer/mc/survival/ControlledShield")).accept(new ClassVisitor(Opcodes.ASM9){public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e){if(!n.equals("start"))return null;return new MethodVisitor(Opcodes.ASM9){public void visitFieldInsn(int o,String w,String n,String d){if(w.equals("net/minecraft/util/Hand"))hands.add(n);}};}},ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);
        assertEquals(Set.of("OFF_HAND"),hands);assertFalse(calls(start,"net/minecraft/client/network/ClientPlayerInteractionManager:interactItem"));
    }
    @Test void interruptedFoodCanResolveThroughTheOriginalCheckpointWithoutWinningFoodPriority()throws Exception{
        var checkpoint=code.calls("dev/aitalkstreamer/mc/survival/ControlledEatingTask").get("checkpoint()V");
        assertTrue(calls(checkpoint,"dev/aitalkstreamer/mc/survival/ControlledEatingTask:onTick"));assertFalse(calls(checkpoint,"dev/aitalkstreamer/mc/survival/EatingBudget:<init>"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/ControlledShield"),"dev/aitalkstreamer/mc/survival/ControlledEatingTask:interrupt"));
    }
    @Test void repeatedVanillaUseAndGuiWritesCannotBorrowAnActiveShieldTransaction()throws Exception{
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalGameExecutor"),"dev/aitalkstreamer/mc/survival/ControlledShield:busy"));
        assertTrue(calls(all("dev/aitalkstreamer/mc/survival/SurvivalActions"),"dev/aitalkstreamer/mc/survival/ControlledShield:allowItemUse"));
        assertEquals(3,all("dev/aitalkstreamer/mc/survival/SurvivalGui").stream().filter(s->s.startsWith("dev/aitalkstreamer/mc/survival/ControlledShield:guardGuiWrite")).count());
    }
    @Test void ownedShieldStopAlwaysUsesNativeReleaseAndForgetsOnlyItsOwnLedgerClaim()throws Exception{
        var stop=code.calls("dev/aitalkstreamer/mc/survival/SurvivalActions").entrySet().stream().filter(e->e.getKey().startsWith("lambda$stopShieldUse$")).flatMap(e->e.getValue().stream()).toList();
        assertTrue(calls(stop,"dev/aitalkstreamer/mc/survival/ControlledShield:guardShieldStop"));assertTrue(calls(stop,"net/minecraft/client/network/ClientPlayerInteractionManager:stopUsingItem"));assertTrue(calls(stop,"dev/aitalkstreamer/mc/survival/InteractionLedger:stop"));
    }
    @Test void revokedCleanupHasNoNativeItemInventoryOrInputWrites()throws Exception{
        var cleanup=code.calls("dev/aitalkstreamer/mc/survival/ControlledShield").entrySet().stream().filter(e->e.getKey().startsWith("lambda$new$")).flatMap(e->e.getValue().stream()).toList();
        assertTrue(calls(cleanup,"dev/aitalkstreamer/mc/survival/ShieldCycle:close"));for(String forbidden:List.of("dev/aitalkstreamer/mc/survival/SurvivalActions:","dev/aitalkstreamer/mc/survival/SurvivalGui:","dev/aitalkstreamer/mc/survival/SurvivalInputs:"))assertFalse(calls(cleanup,forbidden));
    }
    @Test void nativeShieldUseSelectsTheSuppliedHandAndIsAnAnimationRatherThanAServerBlockReceipt()throws Exception{
        var use=code.calls("net/minecraft/item/ShieldItem").get("use(Lnet/minecraft/world/World;Lnet/minecraft/entity/player/PlayerEntity;Lnet/minecraft/util/Hand;)Lnet/minecraft/util/TypedActionResult;");
        assertTrue(calls(use,"net/minecraft/entity/player/PlayerEntity:setCurrentHand"));assertTrue(calls(use,"net/minecraft/util/TypedActionResult:consume"));
        var owned=all("dev/aitalkstreamer/mc/survival/ControlledShield");assertTrue(calls(owned,"net/minecraft/client/network/ClientPlayerEntity:getActiveHand"));assertTrue(calls(owned,"net/minecraft/item/ItemStack:areItemsAndComponentsEqual"));
    }
}
