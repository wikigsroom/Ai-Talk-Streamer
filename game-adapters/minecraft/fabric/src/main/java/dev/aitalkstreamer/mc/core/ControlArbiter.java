package dev.aitalkstreamer.mc.core;

import java.util.*;
import java.util.function.LongSupplier;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Input permission and time fences are local and independent of the model/network. */
public final class ControlArbiter {
    public enum Mode { PAUSED, MANUAL_COMMENTARY, AUTO }
    public record Permit(String controller, String lease, String world, long epoch) { }
    public record Stop(long epoch, String reason) { }
    public static final long CLIENT_PROGRESS_TIMEOUT_MS = 2000;
    private final LongSupplier clock;
    private final Runnable revoke;
    private final LinkedHashMap<Long, Long> heartbeats = new LinkedHashMap<>(), observations = new LinkedHashMap<>();
    private final NavigableMap<Long, String> revocations = new TreeMap<>();
    private Mode mode = Mode.PAUSED;
    private String controller, world, lease;
    private long epoch, deadline, grantSeq, heartbeatSeq;
    private boolean ready, released = true, releasing;
    public ControlArbiter(LongSupplier clock, Runnable revoke) { this.clock = clock; this.revoke = revoke; }
    public synchronized void attach(String controller) { stop(Mode.PAUSED, "GAME_CONTROLLER_CHANGED"); this.controller = controller; heartbeats.clear(); heartbeatSeq = 0; }
    public synchronized long world(String world) { long stopped = stop(Mode.PAUSED, "GAME_WORLD_CHANGED"); this.world = world; observations.clear(); return stopped; }
    /** A resumed game thread must not make a stalled AUTO session fresh again. */
    public synchronized Stop observe(long seq) {
        require(seq > 0, "GAME_OBSERVATION_SEQUENCE");
        boolean stalled = mode == Mode.AUTO && !clientFresh();
        Stop result = stalled ? new Stop(stop(Mode.PAUSED, "GAME_CLIENT_TICK_STALLED"), "GAME_CLIENT_TICK_STALLED") : null;
        observations.put(seq, clock.getAsLong()); trim(observations, 128); return result;
    }
    private boolean clientFresh() {
        return !observations.isEmpty() && clock.getAsLong() - observations.lastEntry().getValue() <= CLIENT_PROGRESS_TIMEOUT_MS;
    }
    public synchronized long heartbeat() { heartbeats.put(++heartbeatSeq, clock.getAsLong()); trim(heartbeats, 64); return heartbeatSeq; }
    public synchronized long lastHeartbeat() { return heartbeatSeq; }
    private static void trim(LinkedHashMap<Long, Long> values, int maximum) {
        while (values.size() > maximum) values.remove(values.keySet().iterator().next());
    }
    public synchronized void beginAuto(String controller, String world, long expectedEpoch, boolean gameplay) {
        require(Objects.equals(this.controller, controller), "GAME_CONTROLLER_CHANGED");
        require(Objects.equals(this.world, world) && world != null, "GAME_WORLD_CHANGED");
        require(expectedEpoch == epoch, "GAME_CONTROL_CONFLICT");
        require(gameplay && released && clientFresh(),
                "GAME_PRECONDITION_FAILED");
        stop(Mode.PAUSED); mode = Mode.AUTO; lease = "lease-" + UUID.randomUUID();
        deadline = clock.getAsLong() + 3000; grantSeq = 0; ready = false;
    }
    public synchronized boolean grant(String controller, String lease, long epoch, long grantSeq, long heartbeat, long ttl) {
        require(mode == Mode.AUTO && clock.getAsLong() < deadline, "GAME_LEASE_EXPIRED");
        require(Objects.equals(this.controller, controller) && Objects.equals(this.lease, lease) && this.epoch == epoch,
                "GAME_LEASE_CONTEXT");
        require(clientFresh(), "GAME_CLIENT_TICK_STALLED");
        require(grantSeq > this.grantSeq && ttl >= 1000 && ttl <= 10000, "GAME_LEASE_SEQUENCE");
        Long origin = heartbeats.get(heartbeat);
        require(origin != null && origin + ttl > clock.getAsLong(), "GAME_HEARTBEAT_REFERENCE_EXPIRED");
        boolean first = !ready; this.grantSeq = grantSeq; deadline = origin + ttl; ready = true; return first;
    }
    public synchronized void authorize(String controller, String lease, String world, long epoch, long seq, long within) {
        require(allowed(), "GAME_MODE_BLOCKED");
        require(Objects.equals(this.controller, controller) && Objects.equals(this.lease, lease) && epoch == this.epoch,
                "GAME_CONTROL_CONFLICT");
        require(Objects.equals(this.world, world), "GAME_WORLD_CHANGED");
        Long observed = observations.get(seq);
        require(observed != null && within >= 250 && within <= 2000 && clock.getAsLong() - observed <= within,
                "GAME_OBSERVATION_EXPIRED");
    }
    public synchronized boolean allowed() { return mode == Mode.AUTO && ready && clock.getAsLong() < deadline && clientFresh(); }
    public synchronized Permit permit() {
        require(allowed(), "GAME_MODE_BLOCKED"); return new Permit(controller, lease, world, epoch);
    }
    /** The permission check and the bounded client-thread input write are indivisible. */
    public synchronized void actuate(Permit permit, Runnable action) {
        require(permit != null && permit.epoch() == epoch && Objects.equals(permit.controller(), controller)
                && Objects.equals(permit.lease(), lease) && Objects.equals(permit.world(), world), "GAME_CONTROL_CONFLICT");
        require(allowed(), "GAME_MODE_BLOCKED"); require(!releasing, "GAME_INPUT_RELEASE_IN_PROGRESS"); released = false; action.run();
    }
    /** An old queued release cannot clear keys or confirm release for a newer epoch. */
    public synchronized boolean release(long expectedEpoch, Runnable action) {
        if (expectedEpoch != epoch) return false;
        boolean outer = releasing; releasing = true; released = false;
        try {
            action.run(); if (expectedEpoch != epoch) return false;
            released = true; return true;
        } catch (RuntimeException | Error failure) {
            if (expectedEpoch == epoch) released = false; throw failure;
        } finally { releasing = outer; }
    }
    public synchronized Stop expireAndStop() {
        if (mode != Mode.AUTO) return null;
        String reason = clock.getAsLong() >= deadline ? "LEASE_EXPIRED" : !clientFresh() ? "GAME_CLIENT_TICK_STALLED" : null;
        return reason == null ? null : new Stop(stop(Mode.PAUSED, reason), reason);
    }
    public synchronized boolean expire() {
        return expireAndStop() != null;
    }
    public synchronized long stop(Mode next) {
        return stop(next, "CONTROL_REVOKED");
    }
    public synchronized long stop(Mode next, String reason) {
        require(next != Mode.AUTO, "GAME_INVALID_STOP_MODE");
        require(reason != null && !reason.isBlank() && reason.length() <= 256, "GAME_INVALID_STOP_REASON");
        mode = next; ready = false; lease = null; deadline = 0; grantSeq = 0; long stopped = ++epoch;
        revocations.put(stopped, reason); while (revocations.size() > 64) revocations.pollFirstEntry();
        released = false; revoke.run(); return stopped;
    }
    /** First cause after the original permit, including a stop whose game-thread cleanup is still queued. */
    public synchronized String revocationReason(Permit original) {
        if (original == null || revocations.isEmpty() || original.epoch() < revocations.firstKey() - 1) return null;
        var first = revocations.higherEntry(original.epoch());
        if (first != null) return first.getValue();
        if (original.epoch() == epoch && mode == Mode.AUTO) {
            if (clock.getAsLong() >= deadline) return "LEASE_EXPIRED";
            if (!clientFresh()) return "GAME_CLIENT_TICK_STALLED";
        }
        return null;
    }
    public synchronized Mode mode() { return mode; }
    public synchronized long epoch() { return epoch; }
    public synchronized boolean released() { return released; }
    public synchronized boolean ready() { return allowed(); }
    public synchronized String lease() { return lease; }
    public synchronized String controller() { return controller; }
    public synchronized long grantSeq() { return grantSeq; }
    public synchronized long remaining() { return mode == Mode.AUTO ? Math.max(0, deadline - clock.getAsLong()) : 0; }
}
