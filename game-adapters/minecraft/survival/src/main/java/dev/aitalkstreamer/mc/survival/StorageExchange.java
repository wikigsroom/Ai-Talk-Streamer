package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import java.util.*;
import java.util.function.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Exact ordinary-container transfers. Each PICKUP waits for a newer full server inventory. */
final class StorageExchange {
    static final long CLICK_MS=1500,TOTAL_MS=12000;
    record State(List<Stack> slots,Stack cursor) {
        State {
            require(slots!=null && (slots.size()==63 || slots.size()==90) && slots.stream().allMatch(Objects::nonNull)
                    && cursor!=null,"GAME_STORAGE_STATE_INVALID");slots=List.copyOf(slots);
        }
        State slot(int index,Stack stack) {var next=new ArrayList<>(slots);next.set(index,stack);return new State(next,cursor);}
        State cursor(Stack stack) {return new State(slots,stack);}
    }
    record Step(int slot,int button,State before,State after) { }
    static List<Step> plan(State before,int source,int destination,int amount,int maximum) {
        int split=before.slots().size()-36;
        require(before.cursor().equals(Stack.EMPTY) && source>=0 && source<before.slots().size()
                && destination>=0 && destination<before.slots().size() && (source<split)!=(destination<split),"GAME_STORAGE_MOVE_INVALID");
        Stack from=before.slots().get(source),to=before.slots().get(destination);
        require(amount>0 && amount<=from.count() && maximum>0 && maximum<=99 && to.count()+amount<=maximum
                && (to.equals(Stack.EMPTY) || from.type()==to.type()),"GAME_STORAGE_MOVE_INVALID");
        var steps=new ArrayList<Step>();var held=before.slot(source,Stack.EMPTY).cursor(from);
        steps.add(new Step(source,0,before,held));
        if(amount==from.count()) {
            var after=held.slot(destination,new Stack(from.type(),to.count()+amount)).cursor(Stack.EMPTY);
            steps.add(new Step(destination,0,held,after));
        } else {
            for(int i=0;i<amount;i++) {
                var after=held.slot(destination,new Stack(from.type(),to.count()+i+1)).cursor(new Stack(from.type(),from.count()-i-1));
                steps.add(new Step(destination,1,held,after));held=after;
            }
            var after=held.slot(source,held.cursor()).cursor(Stack.EMPTY);steps.add(new Step(source,0,held,after));
        }
        return List.copyOf(steps);
    }
    private final List<Step> steps;
    private final LongSupplier clock;
    private final BooleanSupplier current;
    private final Thread thread=Thread.currentThread();
    private final long deadline;
    private int index,beforeRevision;
    private long clickDeadline;
    private State confirmed;
    private boolean pending,sending,forced,closed;
    private String failure;
    StorageExchange(List<Step> steps,LongSupplier clock,BooleanSupplier current) {
        require(steps!=null && !steps.isEmpty() && steps.size()<=101,"GAME_STORAGE_MOVE_INVALID");
        this.steps=List.copyOf(steps);this.clock=Objects.requireNonNull(clock);this.current=Objects.requireNonNull(current);
        for(int i=0;i<steps.size();i++) {
            var step=steps.get(i);require(step!=null && (step.button()==0 || step.button()==1)
                    && step.slot()>=0 && step.slot()<step.before().slots().size()
                    && step.before().slots().size()==step.after().slots().size()
                    && (i==0 || steps.get(i-1).after().equals(step.before())),"GAME_STORAGE_MOVE_INVALID");
        }
        require(steps.getFirst().before().cursor().equals(Stack.EMPTY) && steps.getLast().after().cursor().equals(Stack.EMPTY),"GAME_STORAGE_MOVE_INVALID");
        deadline=clock.getAsLong()+TOTAL_MS;
    }
    private void thread(){require(thread==Thread.currentThread(),"GAME_WRONG_THREAD");}
    private void check(){thread();require(!closed && current.getAsBoolean(),"GAME_STORAGE_CONTEXT_CHANGED");
        require(failure==null,failure==null?"GAME_STORAGE_SERVER_DIVERGED":failure);
        require(clock.getAsLong()<deadline && (!pending || clock.getAsLong()<clickDeadline),"GAME_STORAGE_SERVER_TIMEOUT");}
    boolean advance(State actual,int revision,Consumer<Step> click) {
        check();
        if(pending) {
            if(confirmed==null)return false;
            require(actual.equals(confirmed),"GAME_STORAGE_SERVER_DIVERGED");pending=false;confirmed=null;index++;
        }
        if(index==steps.size())return true;
        var step=steps.get(index);require(actual.equals(step.before()),"GAME_STORAGE_SERVER_DIVERGED");
        require(revision>=0 && revision<=32767,"GAME_STORAGE_STATE_INVALID");beforeRevision=revision;
        clickDeadline=Math.min(deadline,clock.getAsLong()+CLICK_MS);pending=true;sending=true;forced=false;
        try {click.accept(step);require(forced,"GAME_STORAGE_RESYNC_HOOK_MISSING");}
        catch(RuntimeException|Error error){failure="GAME_STORAGE_CLICK_FAILED";throw error;}
        finally{sending=false;}
        return false;
    }
    boolean sending(){thread();return !closed && current.getAsBoolean() && sending;}
    int revision(int original){check();require(sending && !forced,"GAME_STORAGE_UNEXPECTED_CLICK");forced=true;return -1;}
    void confirm(State received,int revision) {
        thread();if(closed || !current.getAsBoolean() || !pending || sending || !forced || confirmed!=null || failure!=null)return;
        if(clock.getAsLong()>=clickDeadline || clock.getAsLong()>=deadline){failure="GAME_STORAGE_SERVER_TIMEOUT";return;}
        int delta=(revision-beforeRevision)&32767;
        if(revision<0 || revision>32767 || delta==0 || delta>=16384)return;
        if(!steps.get(index).after().equals(received)){failure="GAME_STORAGE_SERVER_DIVERGED";return;}
        confirmed=received;
    }
    void close(){thread();closed=true;confirmed=null;}
}
