package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;
import static dev.aitalkstreamer.mc.core.Json.*;
import static dev.aitalkstreamer.mc.survival.CraftClicks.*;
import dev.aitalkstreamer.mc.survival.CraftClicks.Stack;

/** A bounded raw batch, one fuel item, exact component tokens and authoritative furnace updates. */
public final class CookingExchange {
    public static final long CLICK_MS = 1500, COOK_MS = 8000;
    private final Thread thread = Thread.currentThread();
    private final LongSupplier clock;
    private final BooleanSupplier current;
    private final Stack raw, cooked, fuel;
    private final long cookingMillis;
    private final int inputs, outputPerInput;
    private State server, expected;
    private long deadline, cookDeadline;
    private int revision, beforeRevision, inserted, fuelInserted;
    private boolean sending, forced, closed, cooking, done;
    private LocalTaskFailure.Reason failure;

    public CookingExchange(State initial, Stack raw, Stack cooked, Stack fuel, int revision,
                           LongSupplier clock, BooleanSupplier current) {
        this(initial,raw,cooked,fuel,revision,clock,current,COOK_MS);
    }
    public CookingExchange(State initial, Stack raw, Stack cooked, Stack fuel, int revision,
                           LongSupplier clock, BooleanSupplier current,long cookingMillis) {
        this(initial,raw,cooked,fuel,revision,clock,current,cookingMillis,1);
    }
    public CookingExchange(State initial, Stack raw, Stack cooked, Stack fuel, int revision,
                           LongSupplier clock, BooleanSupplier current,long cookingMillis,int inputs) {
        require(initial.slots().size() == 39 && initial.cursor().empty()
                && initial.slots().subList(0, 3).stream().allMatch(Stack::empty)
                && raw.count() == 1 && !cooked.empty() && fuel.count() == 1
                && inputs>0 && inputs<=4 && inputs<=raw.limit() && (long)cooked.count()*inputs<=cooked.limit()
                && cookingMillis>0 && cookingMillis<=65000
                && validRevision(revision), "GAME_COOKING_INITIAL_STATE_INVALID");
        this.server = initial; this.raw = raw.count(inputs); this.cooked = cooked.count(cooked.count()*inputs); this.fuel = fuel;
        this.inputs=inputs;this.outputPerInput=cooked.count();
        this.revision = revision; this.clock = clock; this.current = current;
        this.cookingMillis=cookingMillis;
    }
    private static boolean validRevision(int value) { return value >= 0 && value <= 32767; }
    private static boolean newer(int value, int previous) {
        int delta = (value - previous) & 32767; return validRevision(value) && delta > 0 && delta < 16384;
    }
    private void thread() { require(Thread.currentThread() == thread, "GAME_WRONG_THREAD"); }
    public void check() {
        thread(); require(!closed && current.getAsBoolean(), "GAME_COOKING_REVOKED");
        if (failure != null) throw new LocalTaskFailure(failure);
        if (expected != null && clock.getAsLong() >= deadline
                || cooking && !done && clock.getAsLong() >= cookDeadline) throw new LocalTaskFailure(COOKING_SERVER_TIMEOUT);
    }
    public boolean pending() { check(); return expected != null || cooking && !done && !coherent(server); }
    public boolean sending() { thread(); return !closed && sending && current.getAsBoolean(); }
    public State server() { check(); return server; }
    public boolean cooked() { check(); return done; }
    public int lastRevision() { thread(); return revision; }
    /** Slot zero is an input here. Crafting's result-slot exception must never be reused. */
    public static Step pickup(State before, int slot, int button) {
        require(slot >= 0 && slot < 39 && before.slots().size() == 39, "GAME_COOKING_SLOT_INVALID");
        if (slot != 0) return CraftClicks.pickup(before, slot, button);
        // Delegate the exact PICKUP arithmetic with input temporarily mapped to a normal slot.
        var values = new ArrayList<>(before.slots()); Collections.swap(values, 0, 3);
        var move = CraftClicks.pickup(new State(values, before.cursor()), 3, button);
        values = new ArrayList<>(move.after().slots()); Collections.swap(values, 0, 3);
        return new Step(0, button, false, before, new State(values, move.after().cursor()));
    }
    public static List<Step> moveOne(State before, int source, int destination) {
        require(source >= 3 && source < 39 && (destination == 0 || destination == 1)
                && before.cursor().empty() && before.slots().get(destination).empty(), "GAME_COOKING_MOVE_INVALID");
        List<Step> steps = new ArrayList<>(); steps.add(pickup(before, source, 0));
        steps.add(pickup(steps.getLast().after(), destination, 1));
        if (!steps.getLast().after().cursor().empty()) steps.add(pickup(steps.getLast().after(), source, 0));
        return List.copyOf(steps);
    }
    private int rawUnits(Stack value) {return value.empty()?0:value.type()==raw.type() && value.limit()==raw.limit() && value.count()<=inputs?value.count():-1;}
    private int cookedUnits(Stack value) {return value.empty()?0:value.type()==cooked.type() && value.limit()==cooked.limit()
            && value.count()<=cooked.count() && value.count()%outputPerInput==0?value.count()/outputPerInput:-1;}
    private boolean coherent(State value) {
        int input=rawUnits(value.slots().get(0)),output=cookedUnits(value.slots().get(2));
        return input>=0 && output>=0 && input+output==inserted;
    }
    /** A full acknowledgement must conserve all raw units inserted so far, including cooking during loading. */
    private boolean legalAdvance(State from, State to) {
        if (to.slots().size() != 39) return false;
        if (!from.cursor().equals(to.cursor()) || !from.slots().subList(3, 39).equals(to.slots().subList(3, 39))) return false;
        Stack input = from.slots().get(0), heat = from.slots().get(1), output = from.slots().get(2);
        boolean burned = heat.equals(fuel) && to.slots().get(1).empty();
        if (!heat.equals(to.slots().get(1)) && !burned) return false;
        if (!cooking || done) return input.equals(to.slots().get(0)) && output.equals(to.slots().get(2));
        return coherent(to) && rawUnits(to.slots().get(0))<=rawUnits(input)
                && cookedUnits(to.slots().get(2))>=cookedUnits(output);
    }
    public void send(Step step, State actual, int actualRevision, Runnable click) {
        check(); require(expected == null && step.before().equals(actual) && server.equals(actual)
                && (!cooking || done || coherent(server))
                && validRevision(actualRevision) && !step.craft(), "GAME_COOKING_STATE_CHANGED");
        require(step.slot()!=2 || done,"GAME_COOKING_STATE_CHANGED");
        if (step.slot()==0) {
            int before=rawUnits(actual.slots().get(0)),after=rawUnits(step.after().slots().get(0));
            require(!done && before>=0 && after==before+1 && inserted<inputs,"GAME_COOKING_STATE_CHANGED");
            inserted++;
        }
        if (step.slot()==1 && !step.after().slots().get(1).empty()) {
            require(actual.slots().get(1).empty() && step.after().slots().get(1).equals(fuel) && fuelInserted==0,"GAME_COOKING_STATE_CHANGED");
            fuelInserted++;
        }
        expected = step.after(); beforeRevision = actualRevision; forced = false;
        deadline = clock.getAsLong() + CLICK_MS; sending = true;
        // Residual heat can cook before new fuel is inserted. The first raw insertion
        // starts the fixed deadline, including fuel preparation and cursor return.
        if (!cooking && inserted>0) {
            cooking = true; cookDeadline = clock.getAsLong() + cookingMillis;
        }
        try { click.run(); require(forced, "GAME_COOKING_RESYNC_HOOK_MISSING"); }
        catch (RuntimeException | Error error) { failure = COOKING_SERVER_DIVERGED; throw error; }
        finally { sending = false; }
    }
    public int revision(int original) {
        check(); require(sending && expected != null && !forced, "GAME_COOKING_UNEXPECTED_CLICK"); forced = true; return -1;
    }
    /** Full resync is the only acknowledgement for a click; predicted local contents never count. */
    public void inventory(State received, int receivedRevision) {
        thread(); if (closed || !current.getAsBoolean() || failure != null || sending) return;
        if (expected == null) {
            if (!newer(receivedRevision, revision)) return;
            if (!legalAdvance(server, received)) { failure = COOKING_SERVER_DIVERGED; return; }
        } else {
            if (!forced || !newer(receivedRevision, beforeRevision)) return;
            if (clock.getAsLong() >= deadline) { failure = COOKING_SERVER_TIMEOUT; return; }
            if (!legalAdvance(expected, received)) { failure = COOKING_SERVER_DIVERGED; return; }
            expected = null;
        }
        server = received; revision = receivedRevision; completed();
    }
    /** Partial updates may transiently show input consumed before output arrives. Only a complete
     * legal state can authorize collection; no packet callback performs or authorizes a write. */
    public void slot(int slot, Stack value, int receivedRevision) {
        thread(); if (closed || !current.getAsBoolean() || expected != null || failure != null || !cooking || done) return;
        if (slot < 0 || slot >= 39 || !validRevision(receivedRevision)) { failure = COOKING_SERVER_DIVERGED; return; }
        if (receivedRevision != revision && !newer(receivedRevision, revision)) return;
        Stack old = server.slots().get(slot);
        boolean valid = old.equals(value) || slot == 0 && rawUnits(value)>=0 && rawUnits(value)<rawUnits(old)
                || slot == 1 && old.equals(fuel) && value.empty()
                || slot == 2 && cookedUnits(value)>cookedUnits(old) && cookedUnits(value)<=inserted;
        if (!valid) { failure = COOKING_SERVER_DIVERGED; return; }
        server = server.slot(slot, value); revision = receivedRevision; completed();
    }
    private void completed() {
        if (cooking && !done && clock.getAsLong() >= cookDeadline) { failure = COOKING_SERVER_TIMEOUT; return; }
        if (cooking && inserted==inputs && server.slots().get(0).empty() && server.slots().get(2).equals(cooked)) done = true;
    }
    public void cancel() { thread(); closed = true; expected = null; }
}
