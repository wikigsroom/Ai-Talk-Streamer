package dev.aitalkstreamer.mc.core;

import java.util.Objects;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Task-local GUI ownership. Object identity is intentional; a type or sync ID is insufficient. */
public final class TaskGuiLease {
    public static final long OPEN_WITHIN_MS = 1500, IDLE_MS = 3000, MAX_OPEN_MS = 15000;
    // One vanilla smoking operation takes five seconds without producing a slot update.
    public static final long SMOKER_IDLE_MS = 10000;
    public static final long FURNACE_IDLE_MS=65000,FURNACE_MAX_OPEN_MS=75000;
    private final LongSupplier clock;
    private final BooleanSupplier current;
    private final Thread thread = Thread.currentThread();
    private Object world, player, previousHandler, screen, handler;
    private String kind;
    private int previousSync, sync;
    private long openingDeadline, idleDeadline, absoluteDeadline;
    private boolean expired;
    public TaskGuiLease(LongSupplier clock, BooleanSupplier current) {
        this.clock = Objects.requireNonNull(clock); this.current = Objects.requireNonNull(current);
    }
    private void thread() { require(thread == Thread.currentThread(), "GAME_WRONG_THREAD"); }
    public void expect(String kind, Object world, Object player, Object previousHandler, int previousSync) {
        thread(); require(current.getAsBoolean(), "GAME_GUI_REVOKED");
        require(this.kind == null && !expired, "GAME_GUI_ALREADY_EXPECTED");
        require(kind.equals("inventory") || kind.equals("crafting_table") || kind.equals("smoker") || kind.equals("furnace") || kind.equals("blast_furnace") || kind.equals("storage"), "GAME_GUI_UNSUPPORTED");
        require(world != null && player != null && previousHandler != null && previousSync >= 0, "GAME_GUI_CONTEXT");
        this.kind = kind; this.world = world; this.player = player; this.previousHandler = previousHandler; this.previousSync = previousSync;
        openingDeadline = clock.getAsLong() + OPEN_WITHIN_MS;
    }
    public boolean pending() { thread(); return live() && screen == null; }
    public boolean exists() { thread(); return kind != null || expired; }
    private boolean live() {
        if (kind == null || expired || !current.getAsBoolean()) return false;
        long now = clock.getAsLong();
        if (screen == null ? now >= openingDeadline : now >= idleDeadline || now >= absoluteDeadline) {
            expired = true; return false;
        }
        return true;
    }
    /** Only the first expected response can bind. Later screens cannot inherit the lease. */
    public boolean permits(String kind, Object world, Object player, Object screen, Object handler, int sync) {
        thread();
        if (!live() || !this.kind.equals(kind) || this.world != world || this.player != player || screen == null || handler == null || sync < 0) return false;
        if (this.screen == null) {
            if (kind.equals("inventory") ? handler != previousHandler || sync != previousSync : handler == previousHandler || sync == previousSync || sync == 0) return false;
            this.screen = screen; this.handler = handler; this.sync = sync;
            long now = clock.getAsLong(); idleDeadline = now + idleMs(); absoluteDeadline = now + maximumMs();
        }
        return this.screen == screen && this.handler == handler && this.sync == sync;
    }
    /** Call after a successful, already authorized operation; observations do not renew the lease. */
    public void progress() {
        thread(); require(live() && screen != null, "GAME_GUI_NOT_OWNED");
        idleDeadline = Math.min(absoluteDeadline, clock.getAsLong() + idleMs());
    }
    private boolean furnace() {return "furnace".equals(kind)||"blast_furnace".equals(kind);}
    private long maximumMs() {return furnace()?FURNACE_MAX_OPEN_MS:MAX_OPEN_MS;}
    private long idleMs() { return furnace()?FURNACE_IDLE_MS:"smoker".equals(kind) ? SMOKER_IDLE_MS : IDLE_MS; }
    public long remaining() {
        thread(); return !live() ? 0 : Math.max(0, (screen == null ? openingDeadline : Math.min(idleDeadline, absoluteDeadline)) - clock.getAsLong());
    }
    public String kind() { thread(); return kind; }
    public int sync() { thread(); return sync; }
    /** Forgetting ownership performs no game action, including after physical takeover. */
    public void clear() { thread(); kind = null; world = player = previousHandler = screen = handler = null; expired = false; }
}
