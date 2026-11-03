package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ResourceRecoveryBindingTest {
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    List<String> method(String name,String prefix)throws Exception {return code.calls(name).entrySet().stream().filter(e->e.getKey().startsWith(prefix)).findFirst().orElseThrow().getValue();}
    boolean has(List<String> calls,String prefix){return calls.stream().anyMatch(s->s.startsWith(prefix));}
    @Test void thePreparedTaskDispatchesTypedChildFailuresThroughItsActualOwner()throws Exception {
        assertTrue(has(method("adris/altoclef/tasksystem/Task","tick("),"adris/altoclef/tasksystem/Task:onChildFailure"));
        assertTrue(has(method("adris/altoclef/tasksystem/Task","tick("),"adris/altoclef/tasksystem/Task:stopped"));
    }
    @Test void actualCollectorStopsBeforeRecordingFailureAndReplanning()throws Exception {
        var calls=method("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask","onChildFailure(");
        int stop=-1,record=-1;for(int i=0;i<calls.size();i++){if(calls.get(i).startsWith("dev/aitalkstreamer/mc/survival/ResourceBranchRecovery:stop"))stop=i;if(calls.get(i).startsWith("dev/aitalkstreamer/mc/survival/ResourceMaterials:failed"))record=i;}
        assertTrue(stop>=0 && record>stop);assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ResourceBranchRecovery:ready"));
    }
    @Test void sourceFactoryRejectionsUseTheSameFailureRegistry()throws Exception {
        var calls=method("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask","onTick(");
        assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ResourceBranchRecovery:recoverable"));assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/ResourceMaterials:failed"));
    }
    @Test void recoveryInvalidatesOldCalculationsBeforeCancellingAndReleasingInputs()throws Exception {
        var calls=method("dev/aitalkstreamer/mc/survival/ResourceBranchRecovery","stop(");
        int generation=-1,cancel=-1;for(int i=0;i<calls.size();i++){if(calls.get(i).startsWith("dev/aitalkstreamer/mc/survival/SurvivalAsync:invalidate"))generation=i;if(calls.get(i).contains(":forceCancel("))cancel=i;}
        assertTrue(generation>=0 && cancel>generation);
        for(String prefix:List.of("dev/aitalkstreamer/mc/survival/SurvivalCallbacks:clearRootEvents","dev/aitalkstreamer/mc/survival/SurvivalActions:finishOwned","dev/aitalkstreamer/mc/survival/SurvivalGui:finishOwned"))assertTrue(has(calls,prefix));
        assertTrue(calls.stream().anyMatch(s->s.contains(":clearAllKeys(")));assertTrue(calls.stream().anyMatch(s->s.contains(":clearControlledQueue(")));
    }
    @Test void recoveryAdmissionChecksAllTransactionsAndTheActualGuiState()throws Exception {
        var calls=method("dev/aitalkstreamer/mc/survival/ResourceBranchRecovery","ready(");
        for(String name:List.of("ConfirmedCraftTask:busy","ControlledCookingTask:busy","ControlledFoodCookingTask:within","ControlledEatingTask:busy","ControlledEquipment:busy","ControlledShield:busy","SurvivalGui:backtrackReady","SurvivalAuthority:requireScope","ResourceMaterials:desired"))assertTrue(has(calls,"dev/aitalkstreamer/mc/survival/"+name));
        var gui=method("dev/aitalkstreamer/mc/survival/SurvivalGui","backtrackReady(");
        assertTrue(has(gui,"dev/aitalkstreamer/mc/survival/SurvivalGui:permits"));assertTrue(gui.stream().anyMatch(s->s.contains(":getCursorStack(")));assertTrue(gui.stream().anyMatch(s->s.contains(":getSlot(")));
    }
    @Test void recoveryCannotOpenAnotherRootOrResetSelectionBudgets()throws Exception {
        var calls=code.calls("dev/aitalkstreamer/mc/survival/ResourceBranchRecovery").values().stream().flatMap(List::stream).toList();
        for(String prefix:List.of("dev/aitalkstreamer/mc/survival/SurvivalAuthority:open","dev/aitalkstreamer/mc/survival/MaterialReservations:clear","dev/aitalkstreamer/mc/survival/ControlledTaskRunner:start"))assertFalse(has(calls,prefix));
    }
    @Test void nextAcquisitionWaitsForRealJobQuiescenceBeforeConsumingAnotherSelection()throws Exception {
        var calls=method("dev/aitalkstreamer/mc/survival/ControlledRecipeResourcesTask","onTick(");
        int wait=-1,select=-1;for(int i=0;i<calls.size();i++){if(calls.get(i).startsWith("dev/aitalkstreamer/mc/survival/SurvivalAsync:quiescent"))wait=i;if(select<0 && calls.get(i).startsWith("dev/aitalkstreamer/mc/survival/ResourceMaterials:select"))select=i;}
        assertTrue(wait>=0 && select>wait);
    }
}
