package dev.aitalkstreamer.mc.core;

import java.util.Objects;
import java.util.function.LongSupplier;
import com.google.gson.JsonObject;
import static dev.aitalkstreamer.mc.core.Json.obj;

/** Client-thread menu protection only. It never grants AUTO or writes movement/item inputs. */
public final class SingleplayerPausePolicy {
    public record Context(Object world, Object player, Object connection, Object server,
                          boolean published, boolean alive, boolean screenOpen, boolean paused, boolean presentationReady,
                          boolean inputsClear, boolean taskIdle, boolean physicalHeld) {
        boolean same(Context other) {
            return other != null && world == other.world && player == other.player
                    && connection == other.connection && server == other.server;
        }
    }
    public interface Port {
        Context context();
        default boolean preparingAuto() { return false; }
        /** Recheck the original object identities and open only the ordinary pause menu. */
        boolean openPauseMenu(Context expected);
    }
    public static final long CONFIRM_TIMEOUT_MS = 2000;
    public static final long PRESENTATION_WAIT_LIMIT_MS = 2000;
    private final LongSupplier clock;
    private Context scope;
    private String session, state = "WAITING_WORLD", reason = "NO_WORLD";
    private long epoch = -1, physicalEpoch = -1, waitingSince = -1;
    private long presentationSince = -1;
    private int requests;
    private boolean terminal, requested, confirmed;
    private boolean presentationTimedOut;
    public SingleplayerPausePolicy(LongSupplier clock) { this.clock = clock; }

    /** Real keyboard/mouse activity cancels a pending stop, including before its first tick. */
    public void physicalActivity(long currentEpoch) { physicalEpoch = currentEpoch; }

    public void tick(ControlArbiter control, String worldSession, Port port) {
        // The mode/epoch check and bounded menu call share the existing authority's monitor.
        // This is not a PAUSED input permit and cannot confirm release for an AUTO task.
        synchronized (control) {
            Context current = port.context();
            if (control.epoch() != epoch || !Objects.equals(session, worldSession) || !current.same(scope)) {
                epoch = control.epoch(); session = worldSession; scope = current;
                terminal = requested = confirmed = false; waitingSince = -1;
                presentationSince = -1; presentationTimedOut = false;
                state = "WAITING_WORLD"; reason = "NO_WORLD";
            }
            if (control.mode() != ControlArbiter.Mode.PAUSED) { finish("DISARMED", "CONTROL_MODE"); return; }
            if (current.world == null || current.player == null || current.connection == null || session == null) return;
            if (current.server == null) { finish("UNSUPPORTED", "MULTIPLAYER_WORLD"); return; }
            if (current.published) { finish("UNSUPPORTED", "LOCAL_WORLD_PUBLISHED"); return; }
            // The normal resume/respawn flow owns the menu until its fresh
            // gameplay confirmation and new lease handshake have completed.
            if (port.preparingAuto()) { state="WAITING_AUTO_RESUME";reason="RESUME_HANDSHAKE";return; }
            if (!current.alive) { finish("DEAD", "PLAYER_NOT_ALIVE"); return; }
            if (current.paused) { confirmed = true; finish("CONFIRMED", "GAME_PAUSE_OBSERVED"); return; }
            // A player may deliberately resume a protected world. Never reopen it in this epoch.
            if (terminal) { confirmed = false; return; }
            if (physicalEpoch == epoch || current.physicalHeld) { finish("CANCELLED", "PHYSICAL_ACTIVITY"); return; }
            long now = clock.getAsLong();
            if (requested) {
                if (now - waitingSince >= CONFIRM_TIMEOUT_MS) finish("FAILED", "PAUSE_NOT_CONFIRMED");
                return;
            }
            if (current.screenOpen) { state = "WAITING_GUI"; reason = "EXISTING_SCREEN"; waitingSince = -1; return; }
            if (!current.presentationReady && !presentationTimedOut) {
                if (presentationSince < 0) presentationSince = now;
                if (now - presentationSince < PRESENTATION_WAIT_LIMIT_MS) {
                    state = "WAITING_PRESENTATION"; reason = "FIRST_WORLD_FRAMES_PENDING"; return;
                }
                // An absent render receipt must never leave a live singleplayer world running indefinitely.
                presentationTimedOut = true;
            }
            if (waitingSince < 0) waitingSince = now;
            if (!control.released() || !current.inputsClear || !current.taskIdle) {
                state = "WAITING_RELEASE"; reason = "TASK_OR_INPUT_CLEANUP";
                if (now - waitingSince >= CONFIRM_TIMEOUT_MS) finish("FAILED", "CLEANUP_NOT_CONFIRMED");
                return;
            }
            requested = true; requests++; waitingSince = now;
            try {
                if (port.openPauseMenu(current)) { state = "WAITING_CONFIRMATION"; reason = "MENU_REQUESTED"; }
                else finish("FAILED", "CONTEXT_CHANGED");
            } catch (RuntimeException failure) { finish("FAILED", "MENU_REQUEST_FAILED"); }
        }
    }
    private void finish(String next, String why) { state = next; reason = why; terminal = true; }
    public JsonObject proof() {
        return obj("state", state, "reason", reason, "control_epoch", epoch, "world_session_id", session,
                "menu_request_count", requests, "pause_confirmed", confirmed, "input_actions_issued", 0,
                "presentation_wait_timed_out", presentationTimedOut);
    }
}
