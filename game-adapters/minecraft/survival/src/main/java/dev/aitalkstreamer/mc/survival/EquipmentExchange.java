package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.function.*;
import dev.aitalkstreamer.mc.core.InventoryExchange;
import dev.aitalkstreamer.mc.core.InventoryExchange.State;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;
import static dev.aitalkstreamer.mc.core.Json.require;

/** One original-owner exchange, with an authoritative baseline and no speculative retries. */
public final class EquipmentExchange {
    public static final long TOTAL_MS=8000;
    @FunctionalInterface public interface Click { void send(EquipmentPlan.Step step); }
    private final LongSupplier clock;
    private final Thread thread=Thread.currentThread();
    private final BooleanSupplier owner;
    private final long deadline;
    private final List<EquipmentPlan.Step> steps;
    private InventoryExchange pending;
    private int index;
    private boolean closed,finished;
    public EquipmentExchange(State before,List<EquipmentPlan.Step> transfers,LongSupplier clock,BooleanSupplier owner) {
        EquipmentPlan.ready(before);require(transfers.size()<=3,"GAME_EQUIPMENT_PLAN_INVALID");
        this.clock=clock;this.owner=owner;deadline=clock.getAsLong()+TOTAL_MS;
        var planned=new ArrayList<EquipmentPlan.Step>();planned.add(new EquipmentPlan.Step(before,before,0,0,EquipmentPlan.Action.PICKUP));
        var expected=before;
        for(var step:transfers){require(step.before().equals(expected),"GAME_EQUIPMENT_PLAN_INVALID");planned.add(step);expected=step.after();}
        require(expected.cursor().equals(InventoryExchange.Stack.EMPTY),"GAME_EQUIPMENT_CURSOR_REMAINS");steps=List.copyOf(planned);
    }
    public void check() {
        require(Thread.currentThread()==thread,"GAME_WRONG_THREAD");
        require(!closed&&owner.getAsBoolean(),"GAME_EQUIPMENT_REVOKED");
        if(clock.getAsLong()>=deadline)throw new LocalTaskFailure(EQUIPMENT_TIMEOUT);
        if(pending!=null)pending.check();
    }
    public boolean advance(State actual,int revision,Click click) {
        check();if(finished)return true;
        if(pending!=null){
            if(!pending.confirmed())return false;
            require(actual.equals(pending.confirmedState()),"GAME_EQUIPMENT_STATE_CHANGED");pending.close();pending=null;index++;
        }
        if(index==steps.size()){finished=true;return true;}
        var step=steps.get(index);require(actual.equals(step.before()),"GAME_EQUIPMENT_STATE_CHANGED");
        pending=new InventoryExchange(clock,owner);pending.send(step.before(),step.after(),actual,revision,()->click.send(step));return false;
    }
    public void confirm(State received,int revision){require(Thread.currentThread()==thread,"GAME_WRONG_THREAD");if(!closed&&owner.getAsBoolean()&&pending!=null)pending.confirm(received,revision);}
    public int revision(int original){check();require(pending!=null,"GAME_EQUIPMENT_NO_CLICK");return pending.revision(original);}
    public boolean sending(){return !closed&&owner.getAsBoolean()&&pending!=null&&pending.sending();}
    public void close(){require(Thread.currentThread()==thread,"GAME_WRONG_THREAD");closed=true;if(pending!=null)pending.close();}
}
