package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Checks the executed module's collector and cleanup branches, not a second implementation. */
class ResourceSettlementBindingTest {
    static final String PREFIX="dev/aitalkstreamer/mc/survival/";
    final HeldNativeProtocolTest code=new HeldNativeProtocolTest();
    MethodNode method(String type,String name)throws Exception {
        var c=new ClassNode();new ClassReader(code.bytes(PREFIX+type)).accept(c,ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);
        return c.methods.stream().filter(m->m.name.equals(name)).findFirst().orElseThrow();
    }
    List<MethodInsnNode> calls(MethodNode m){return Arrays.stream(m.instructions.toArray()).filter(i->i instanceof MethodInsnNode).map(i->(MethodInsnNode)i).toList();}
    boolean is(MethodInsnNode m,String type,String name){return m.owner.equals(PREFIX+type)&&m.name.equals(name);}
    @Test void successAndNoTaskFactoriesBothStopBeforeRecordingPostCleanupInventory()throws Exception {
        var c=calls(method("ControlledRecipeResourcesTask","onTick"));int finished=0;
        for(int i=0;i<c.size();i++)if(is(c.get(i),"ResourceMaterials","finish")) {
            finished++;assertTrue(i>=2);assertTrue(is(c.get(i-1),"ResourceMaterials","stock"));assertTrue(is(c.get(i-2),"ResourceBranchRecovery","stop"));
            assertTrue(is(c.get(i+1),"ControlledRecipeResourcesTask","settled"));
        }
        assertEquals(2,finished);
    }
    @Test void everySuccessfulRetirementReturnsBeforeAnotherSourceCanBeCreated()throws Exception {
        var m=method("ControlledRecipeResourcesTask","onTick");int exits=0;
        for(var ins:m.instructions)if(ins instanceof MethodInsnNode call&&is(call,"ResourceMaterials","finish")) {
            var next=ins.getNext();
            while(next!=null && !(next instanceof MethodInsnNode))next=next.getNext();
            assertInstanceOf(MethodInsnNode.class,next);assertEquals("settled",((MethodInsnNode)next).name);
            next=next.getNext();while(next!=null&&next.getOpcode()<0)next=next.getNext();assertEquals(Opcodes.ACONST_NULL,next.getOpcode());
            next=next.getNext();while(next!=null&&next.getOpcode()<0)next=next.getNext();assertEquals(Opcodes.ARETURN,next.getOpcode());exits++;
        }
        assertEquals(2,exits);
    }
    @Test void oldAndCleanupSubmittedCalculationsAreInvalidatedOnBothSidesOfStop()throws Exception {
        var c=calls(method("ResourceBranchRecovery","stop"));var generations=new ArrayList<Integer>();int stop=-1,cancel=-1;
        for(int i=0;i<c.size();i++) {
            if(is(c.get(i),"SurvivalAsync","invalidate"))generations.add(i);
            if(c.get(i).owner.equals("adris/altoclef/tasksystem/Task")&&c.get(i).name.equals("stop"))stop=i;
            if(c.get(i).name.equals("forceCancel"))cancel=i;
        }
        assertEquals(2,generations.size());assertTrue(generations.get(0)<stop && stop<generations.get(1) && generations.get(1)<cancel);
    }
    @Test void settlingClearsOnlyTheOldBranchAndPreservesAllOriginalLimits()throws Exception {
        var m=method("ControlledRecipeResourcesTask","settled");assertTrue(calls(m).isEmpty());var fields=new HashMap<String,Integer>();
        for(var ins:m.instructions)if(ins instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTFIELD) {
            var previous=ins.getPrevious();while(previous.getOpcode()<0)previous=previous.getPrevious();fields.put(f.name,previous.getOpcode());
        }
        assertEquals(Map.of("child",Opcodes.ACONST_NULL,"selected",Opcodes.ACONST_NULL,"beforeChild",Opcodes.ACONST_NULL,"finished",Opcodes.ICONST_0,"settling",Opcodes.ICONST_1),fields);
    }
    @Test void allRetirementPathsUseTheSameSettlingStateIncludingTypedFailures()throws Exception {
        var tick=calls(method("ControlledRecipeResourcesTask","onTick"));var failed=calls(method("ControlledRecipeResourcesTask","onChildFailure"));
        assertEquals(3,tick.stream().filter(m->is(m,"ControlledRecipeResourcesTask","settled")).count());
        assertEquals(1,failed.stream().filter(m->is(m,"ControlledRecipeResourcesTask","settled")).count());
        for(var c:List.of(tick,failed))for(var call:c)if(is(call,"ResourceBranchRecovery","stop"))
            assertEquals("(Ladris/altoclef/tasksystem/Task;Ladris/altoclef/tasksystem/Task;)V",call.desc);
    }
    @Test void aFinishedWrapperStillTicksItsChildWhenAnActualTransactionNeedsCleanup()throws Exception {
        var m=method("ControlledRecipeResourcesTask","onTick");boolean sawFinished=false,sawReady=false,sawReturn=false;
        for(var ins:m.instructions) {
            if(ins instanceof MethodInsnNode c) {
                if(c.name.equals("isFinished"))sawFinished=true;
                if(sawFinished&&is(c,"ResourceBranchRecovery","ready"))sawReady=true;
                if(is(c,"ResourceBranchRecovery","stop")){assertTrue(sawFinished&&sawReady&&sawReturn);return;}
            }
            if(sawReady&&ins.getOpcode()==Opcodes.ARETURN)sawReturn=true;
        }
        fail("No completed-child retirement branch");
    }
    @Test void foodPreparationOwnershipIsCheckedAgainstTheActualSubtree()throws Exception {
        var ready=calls(method("ResourceBranchRecovery","ready"));
        assertEquals(1,ready.stream().filter(c->is(c,"ControlledFoodCookingTask","within")).count());
        assertFalse(ready.stream().anyMatch(c->is(c,"ControlledFoodCookingTask","busy")));
        var within=calls(method("ControlledFoodCookingTask","within"));
        assertTrue(within.stream().anyMatch(c->is(c,"ControlledFoodCookingTask","busy")));
        assertTrue(within.stream().anyMatch(c->c.owner.equals("adris/altoclef/tasksystem/Task")&&c.name.equals("thisOrChildSatisfies")));
    }
    @Test void noRetirementBranchCanRenewRootsOrResetMaterialBudgets()throws Exception {
        for(String type:List.of("ControlledRecipeResourcesTask","ResourceBranchRecovery"))for(var c:code.calls(PREFIX+type).values())
            for(var call:c)for(String forbidden:List.of("SurvivalAuthority:open","MaterialReservations:clear","ResourceMaterials:enter","ControlledTaskRunner:start"))assertFalse(call.startsWith(PREFIX+forbidden));
    }
}
