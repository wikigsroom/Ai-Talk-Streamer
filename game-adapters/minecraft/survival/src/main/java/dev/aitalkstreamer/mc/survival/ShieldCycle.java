package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import java.util.EnumSet;
import java.util.function.BooleanSupplier;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** Per-root shield demand. A missing demand expires; one caller cannot release another caller's shield. */
final class ShieldCycle {
    enum Source { THREAT, MELEE }
    enum Action { NONE, WAIT, START, KEEP, STOP }
    static final long WAIT_MS = 8000, HOLD_MS = 10000, TOTAL_MS = 60000, QUIET_MS = 2000;
    static final int MAX_STARTS = 64;
    private final EnumSet<Source> requests = EnumSet.noneOf(Source.class);
    private final EnumSet<Source> heldFor = EnumSet.noneOf(Source.class);
    private long lastNow, episodeAt = -1, lastDemand = -1, waitAt = -1, issuedAt;
    private int starts;
    private boolean open, issued, meleeMuted, closed;

    ShieldCycle(long now) { if (now < 0) throw new IllegalArgumentException(); lastNow = now; }
    private void clock(long now) {
        if (closed || now < lastNow) throw new IllegalStateException("GAME_SHIELD_CLOCK_OR_OWNER_INVALID");
        lastNow = now;
        if (episodeAt >= 0 && now - episodeAt >= TOTAL_MS || issued && now - issuedAt >= HOLD_MS)
            throw new LocalTaskFailure(SHIELD_TIMEOUT);
    }
    void begin(long now) {
        if (closed || open || now < lastNow) throw new IllegalStateException("GAME_SHIELD_TICK_INVALID");
        // Only a genuinely quiet, released interval ends an encounter. Priority changes do not reset it.
        if (!issued && lastDemand >= 0 && now - lastDemand >= QUIET_MS) { episodeAt = waitAt = -1; starts = 0; }
        clock(now); open = true; requests.clear(); meleeMuted = false;
    }
    void request(Source source) {
        if (!open || closed) throw new IllegalStateException("GAME_SHIELD_OUTSIDE_TICK");
        if (source != Source.MELEE || !meleeMuted) requests.add(source);
    }
    void withdraw(Source source) { if (!closed) requests.remove(source); }
    boolean demanded(Source source) { return !closed && (requests.contains(source) || issued && heldFor.contains(source)); }
    boolean busy() { return !closed && (issued || !requests.isEmpty()); }
    boolean issued() { return !closed && issued; }
    boolean attacksBlocked() { return !closed && requests.contains(Source.THREAT); }
    boolean beforeAttack() {
        if (closed || attacksBlocked()) return false;
        if (!open) return !busy();
        meleeMuted = true; requests.remove(Source.MELEE); return true;
    }
    void suppress() { requests.clear(); meleeMuted = true; }
    Action finish(long now, boolean available, boolean usingShield) {
        return finish(now, () -> available, usingShield);
    }
    Action finish(long now, BooleanSupplier available, boolean usingShield) {
        if (!open || closed) throw new IllegalStateException("GAME_SHIELD_OUTSIDE_TICK");
        clock(now); open = false;
        boolean want = !requests.isEmpty();
        if (want) { if (episodeAt < 0) episodeAt = now; lastDemand = now; }
        if (issued) {
            if (!want || !usingShield) return Action.STOP;
            heldFor.clear(); heldFor.addAll(requests); return Action.KEEP;
        }
        if (!want) { waitAt = -1; return Action.NONE; }
        if (waitAt < 0) waitAt = now;
        if (now - waitAt >= WAIT_MS) throw new LocalTaskFailure(SHIELD_TIMEOUT);
        if (!available.getAsBoolean()) return Action.WAIT;
        if (starts >= MAX_STARTS) throw new LocalTaskFailure(SHIELD_LIMIT);
        starts++; issued = true; issuedAt = now; waitAt = -1;
        heldFor.clear(); heldFor.addAll(requests); return Action.START;
    }
    void accepted(boolean accepted, boolean usingShield) {
        if (!issued || !accepted || !usingShield) throw new LocalTaskFailure(SHIELD_USE_REJECTED);
    }
    void stopped() { issued = false; heldFor.clear(); }
    void close() { closed = true; issued = open = false; requests.clear(); heldFor.clear(); }
}
