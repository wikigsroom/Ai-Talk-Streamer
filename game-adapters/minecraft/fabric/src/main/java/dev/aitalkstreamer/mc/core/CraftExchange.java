package dev.aitalkstreamer.mc.core;

import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Exact stack/component tokens, bounded PICKUP steps and one outstanding server resync. */
public final class CraftExchange {
    public record Stack(int type, int count, int limit) {
        public static final Stack EMPTY = new Stack(0, 0, 64);
        public Stack { require(type >= 0 && count >= 0 && limit >= 1 && limit <= 99
                && count <= limit && (type == 0) == (count == 0), "GAME_CRAFT_STACK_INVALID"); }
        public boolean empty() { return count == 0; }
        public Stack count(int count) { return count == 0 ? EMPTY : new Stack(type, count, limit); }
    }
    public record State(List<Stack> slots, Stack cursor) {
        public State { slots = List.copyOf(slots); Objects.requireNonNull(cursor);
            require(slots.size() >= 5 && slots.size() <= 128, "GAME_CRAFT_HANDLER_INVALID"); }
        /** Result slot is recomputed by the server; all material/other slots and cursor must match. */
        public boolean matches(State other) {
            return other != null && slots.size() == other.slots.size() && cursor.equals(other.cursor)
                    && slots.subList(1, slots.size()).equals(other.slots.subList(1, other.slots.size()));
        }
        public State slot(int slot, Stack value) { var next = new ArrayList<>(slots); next.set(slot, value); return new State(next, cursor); }
    }
    public record Step(int slot, int button, boolean craft, State before, State after) {
        public Step { require(slot >= 0 && slot < before.slots.size() && (button == 0 || button == 1)
                && before.slots.size() == after.slots.size(), "GAME_CRAFT_STEP_INVALID"); }
    }
    private CraftExchange() { }
    public static Step pickup(State before, int slot, int button) {
        require(slot > 0 && slot < before.slots.size() && (button == 0 || button == 1), "GAME_CRAFT_STEP_INVALID");
        Stack source = before.slots.get(slot), cursor = before.cursor, nextSlot, nextCursor;
        if (cursor.empty()) {
            require(!source.empty(), "GAME_CRAFT_SOURCE_EMPTY");
            int take = button == 0 ? source.count : (source.count + 1) / 2;
            nextSlot = source.count(source.count - take); nextCursor = source.count(take);
        } else {
            require(source.empty() || source.type == cursor.type, "GAME_CRAFT_COMPONENT_CHANGED");
            int move = Math.min(button == 0 ? cursor.count : 1, cursor.limit - source.count);
            require(move > 0, "GAME_CRAFT_DESTINATION_FULL");
            nextSlot = cursor.count(source.count + move); nextCursor = cursor.count(cursor.count - move);
        }
        var after = new ArrayList<>(before.slots); after.set(slot, nextSlot);
        return new Step(slot, button, false, before, new State(after, nextCursor));
    }
    public static List<Step> moveOne(State before, int source, int destination) {
        require(before.cursor.empty() && source != destination && before.slots.get(destination).empty(), "GAME_CRAFT_GRID_NOT_EMPTY");
        List<Step> steps = new ArrayList<>();
        steps.add(pickup(before, source, 0)); steps.add(pickup(steps.getLast().after, destination, 1));
        if (!steps.getLast().after.cursor.empty()) steps.add(pickup(steps.getLast().after, source, 0));
        return List.copyOf(steps);
    }
    public static List<Step> storeCursor(State before, List<Integer> inventory) {
        require(inventory.size() == new HashSet<>(inventory).size()
                && inventory.stream().allMatch(i -> i > 0 && i < before.slots.size()), "GAME_CRAFT_INVENTORY_INVALID");
        List<Step> steps = new ArrayList<>(); State current = before;
        for (int slot : inventory) {
            if (current.cursor.empty()) break;
            Stack value = current.slots.get(slot);
            if (value.empty() || value.type == current.cursor.type && value.count < value.limit) {
                Step step = pickup(current, slot, 0); steps.add(step); current = step.after;
            }
        }
        require(current.cursor.empty(), "GAME_CRAFT_OUTPUT_SPACE_UNAVAILABLE"); return List.copyOf(steps);
    }
    public static Step output(State before, Stack result, List<Integer> grid, List<Stack> remainders) {
        require(before.cursor.empty() && !result.empty() && before.slots.getFirst().equals(result)
                && grid.size() == remainders.size() && grid.size() == new HashSet<>(grid).size(), "GAME_CRAFT_RESULT_CHANGED");
        var after = new ArrayList<>(before.slots);
        for (int i = 0; i < grid.size(); i++) {
            int slot = grid.get(i); require(slot > 0 && slot < after.size(), "GAME_CRAFT_GRID_INVALID");
            Stack used = after.get(slot); require(used.empty() || used.count == 1, "GAME_CRAFT_GRID_INVALID");
            require(!used.empty() || remainders.get(i).empty(), "GAME_CRAFT_REMAINDER_INVALID");
            after.set(slot, remainders.get(i));
        }
        after.set(0, Stack.EMPTY);
        return new Step(0, 0, true, before, new State(after, result));
    }

    public static final class Confirmation {
        public static final long TIMEOUT_MS = 1500;
        private final Thread thread = Thread.currentThread();
        private final LongSupplier clock;
        private final BooleanSupplier current;
        private Step pending;
        private long deadline;
        private int previousRevision, lastRevision = -1, crafts;
        private boolean sending, forced, cancelled;
        private String failure;
        public Confirmation(LongSupplier clock, BooleanSupplier current) { this.clock = clock; this.current = current; }
        private void thread() { require(Thread.currentThread() == thread, "GAME_WRONG_THREAD"); }
        public void check() {
            thread(); require(!cancelled && current.getAsBoolean(), "GAME_CRAFT_REVOKED");
            if (failure != null) throw new dev.aitalkstreamer.mc.core.Json.Rejected(failure);
            require(pending == null || clock.getAsLong() < deadline, "GAME_CRAFT_SERVER_TIMEOUT");
        }
        public boolean pending() { check(); return pending != null; }
        /** Must wrap exactly one already-authorized vanilla click; no retransmission on timeout. */
        public void send(Step step, State actual, int revision, Runnable click) {
            check(); require(pending == null && step.before.matches(actual) && revision >= 0 && revision <= 32767,
                    "GAME_CRAFT_STATE_CHANGED");
            pending = step; previousRevision = revision; forced = false; deadline = clock.getAsLong() + TIMEOUT_MS; sending = true;
            try { click.run(); require(forced, "GAME_CRAFT_RESYNC_HOOK_MISSING"); }
            catch (RuntimeException | Error error) { failure = "GAME_CRAFT_CLICK_FAILED"; throw error; }
            finally { sending = false; }
        }
        public int revision(int vanilla) {
            check(); require(sending && pending != null && !forced, "GAME_CRAFT_UNEXPECTED_CLICK"); forced = true;
            // ScreenHandler revisions are nonnegative 15-bit values. A mismatch asks
            // vanilla to send the full authoritative inventory after applying this click.
            return -1;
        }
        public boolean sending() { thread(); return sending && !cancelled && current.getAsBoolean(); }
        /** Callback only records facts; errors surface on the task tick, never in packet application. */
        public void confirm(State server, int revision) {
            thread(); if (cancelled || !current.getAsBoolean() || pending == null || sending || !forced || failure != null) return;
            if (clock.getAsLong() >= deadline) { failure = "GAME_CRAFT_SERVER_TIMEOUT"; return; }
            int delta = (revision - previousRevision) & 32767;
            if (revision < 0 || revision > 32767 || delta == 0 || delta >= 16384) return;
            if (!pending.after.matches(server)) { failure = "GAME_CRAFT_SERVER_DIVERGED"; return; }
            if (pending.craft) crafts++;
            lastRevision = revision; pending = null;
        }
        public int crafts() { thread(); return crafts; }
        public int lastRevision() { thread(); return lastRevision; }
        public void cancel() { thread(); cancelled = true; pending = null; }
    }
}
