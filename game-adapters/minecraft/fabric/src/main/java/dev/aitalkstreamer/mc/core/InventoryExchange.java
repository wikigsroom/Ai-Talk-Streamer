package dev.aitalkstreamer.mc.core;

import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Single player-handler exchange; component tokens are assigned by the live adapter. */
public final class InventoryExchange {
    public record Stack(int type, int count) {
        public static final Stack EMPTY = new Stack(0, 0);
        public Stack { require(type >= 0 && count >= 0 && count <= 99 && (type == 0) == (count == 0), "GAME_ITEM_STACK_INVALID"); }
    }
    public record State(List<Stack> slots, Stack cursor) {
        public State { slots = List.copyOf(slots); Objects.requireNonNull(cursor);
            require(slots.size() == 46, "GAME_ITEM_HANDLER_INVALID"); }
        public State swap(int first, int second) {
            require(first > 4 && first < 46 && second > 4 && second < 46 && first != second && cursor.equals(Stack.EMPTY), "GAME_ITEM_SWAP_INVALID");
            var next = new ArrayList<>(slots); Collections.swap(next, first, second); return new State(next, cursor);
        }
        public State slot(int slot, Stack value) {
            var next = new ArrayList<>(slots); next.set(slot, value); return new State(next, cursor);
        }
    }
    public static final long TIMEOUT_MS = 1500;
    private final Thread owner = Thread.currentThread();
    private final LongSupplier clock;
    private final BooleanSupplier current;
    private List<State> expected;
    private State confirmedState;
    private long deadline;
    private int beforeRevision, confirmedRevision = -1;
    private boolean sending, forced, confirmed, closed;
    private String failure;
    public InventoryExchange(LongSupplier clock, BooleanSupplier current) { this.clock = clock; this.current = current; }
    private void thread() { require(Thread.currentThread() == owner, "GAME_WRONG_THREAD"); }
    public void check() {
        thread(); require(!closed && current.getAsBoolean(), "GAME_ITEM_REVOKED");
        require(failure == null, failure == null ? "GAME_ITEM_EXCHANGE_FAILED" : failure);
        require(expected == null || confirmed || clock.getAsLong() < deadline, "GAME_ITEM_SERVER_TIMEOUT");
    }
    public void send(State before, State after, State actual, int revision, Runnable click) {
        sendAlternatives(before, List.of(after), actual, revision, click);
    }
    /** An interrupted consumption may have either zero or one exact server effect. No other
     * inventory delta is admitted; the caller must resolve the confirmed state before retry. */
    public void sendAlternatives(State before, List<State> after, State actual, int revision, Runnable click) {
        check(); require(expected == null && before.equals(actual) && revision >= 0 && revision <= 32767, "GAME_ITEM_STATE_CHANGED");
        require(after != null && !after.isEmpty() && after.size() <= 2 && new HashSet<>(after).size() == after.size()
                && after.stream().allMatch(Objects::nonNull), "GAME_ITEM_ALTERNATIVES_INVALID");
        expected = List.copyOf(after); beforeRevision = revision; deadline = clock.getAsLong() + TIMEOUT_MS; sending = true;
        try { click.run(); require(forced, "GAME_ITEM_RESYNC_HOOK_MISSING"); }
        catch (RuntimeException | Error error) { failure = "GAME_ITEM_CLICK_FAILED"; throw error; }
        finally { sending = false; }
    }
    public boolean sending() { thread(); return sending && !closed && current.getAsBoolean(); }
    public int revision(int vanilla) {
        check(); require(sending && expected != null && !forced, "GAME_ITEM_UNEXPECTED_CLICK"); forced = true; return -1;
    }
    /** Records packet facts; packet handling itself never receives a transaction exception. */
    public void confirm(State received, int revision) {
        thread(); if (closed || !current.getAsBoolean() || expected == null || sending || !forced || confirmed || failure != null) return;
        if (clock.getAsLong() >= deadline) { failure = "GAME_ITEM_SERVER_TIMEOUT"; return; }
        int delta = (revision - beforeRevision) & 32767;
        if (revision < 0 || revision > 32767 || delta == 0 || delta >= 16384) return;
        if (!expected.contains(received)) { failure = "GAME_ITEM_SERVER_DIVERGED"; return; }
        confirmed = true; confirmedRevision = revision; confirmedState = received;
    }
    public boolean confirmed() { check(); return confirmed; }
    public int confirmedRevision() { thread(); return confirmedRevision; }
    public State confirmedState() { check(); require(confirmed, "GAME_ITEM_NOT_CONFIRMED"); return confirmedState; }
    public void close() { thread(); closed = true; expected = null; confirmedState = null; }
}
