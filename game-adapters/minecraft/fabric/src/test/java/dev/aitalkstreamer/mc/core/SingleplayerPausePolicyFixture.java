package dev.aitalkstreamer.mc.core;

import com.google.gson.JsonObject;
import static dev.aitalkstreamer.mc.core.Json.*;

/** JVM boundary fixture, not real game input or a live-world survival acceptance. */
public final class SingleplayerPausePolicyFixture {
    private static int checks;
    private static void check(boolean value, String why) { checks++; if (!value) throw new AssertionError(why); }
    private static final class Harness implements SingleplayerPausePolicy.Port {
        long now; final ControlArbiter control = new ControlArbiter(() -> now, () -> {});
        final SingleplayerPausePolicy policy = new SingleplayerPausePolicy(() -> now);
        Object world = new Object(), player = new Object(), connection = new Object(), server = new Object();
        String session = "world-session-fixture";
        boolean published, alive = true, screen, paused, presentation = true, clear = true, idle = true, held, accepted = true, throwing;
        int opens;boolean preparing;
        Harness() { control.attach("controller-fixture"); control.world(session); release(); control.observe(1); }
        void release() { control.release(control.epoch(), () -> {}); }
        void tick() { policy.tick(control, session, this); }
        void stop() { control.stop(ControlArbiter.Mode.PAUSED); release(); }
        String state() { return str(policy.proof(), "state"); }
        public SingleplayerPausePolicy.Context context() {
            return new SingleplayerPausePolicy.Context(world, player, connection, server,
                    published, alive, screen, paused, presentation, clear, idle, held);
        }
        public boolean preparingAuto() { check(Thread.holdsLock(control), "resume state shares authority monitor"); return preparing; }
        public boolean openPauseMenu(SingleplayerPausePolicy.Context expected) {
            check(Thread.holdsLock(control), "same authority monitor covers menu request");
            check(control.mode() == ControlArbiter.Mode.PAUSED && control.released(), "never grants input authority");
            opens++; if (throwing) throw new IllegalStateException("fixture"); return accepted;
        }
    }
    public static void main(String[] args) {
        Harness h = new Harness(); h.tick();
        check(h.opens == 1 && h.state().equals("WAITING_CONFIRMATION"), "request is not pause confirmation");
        h.tick(); check(h.opens == 1, "one request while confirmation pending");
        h.paused = true; h.tick(); check(h.policy.proof().get("pause_confirmed").getAsBoolean(), "actual pause confirms");
        h.paused = false; h.tick(); h.tick();
        check(h.opens == 1 && !h.policy.proof().get("pause_confirmed").getAsBoolean(), "human resume never reopens menu");
        h.stop(); h.tick(); check(h.opens == 2, "new explicit stop rearms");

        h = new Harness(); h.control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY); h.release(); h.tick();
        check(h.opens == 0 && h.state().equals("DISARMED"), "manual commentary is untouched");
        h = new Harness(); h.control.beginAuto("controller-fixture", h.session, h.control.epoch(), true); h.tick();
        check(h.opens == 0 && h.state().equals("DISARMED"), "AUTO is untouched even before lease grant");

        h = new Harness(); h.preparing=true;h.tick();h.player=new Object();h.now=9000;h.tick();
        check(h.opens==0 && h.state().equals("WAITING_AUTO_RESUME"),"fresh respawn player cannot be paused mid-handshake");
        h.preparing=false;h.control.observe(2);h.control.beginAuto("controller-fixture",h.session,h.control.epoch(),true);h.tick();
        check(h.opens==0 && h.state().equals("DISARMED"),"confirmed resume goes directly to AUTO without a pause menu");
        h = new Harness();h.preparing=true;h.tick();h.preparing=false;h.stop();h.tick();
        check(h.opens==1,"cancelled resume restores normal explicit-stop pause protection");

        h = new Harness(); h.server = null; h.tick(); check(h.opens == 0 && h.state().equals("UNSUPPORTED"), "multiplayer cannot be paused");
        h = new Harness(); h.published = true; h.tick(); check(h.opens == 0 && h.state().equals("UNSUPPORTED"), "LAN world cannot be paused");
        h = new Harness(); h.alive = false; h.tick(); check(h.opens == 0 && h.state().equals("DEAD"), "no automatic respawn or death-screen replacement");
        h.player = new Object(); h.alive = true; h.tick(); check(h.opens == 1, "replacement live player has separate scope");

        h = new Harness(); h.world = null; h.tick(); check(h.opens == 0, "title screen untouched");
        h.world = new Object(); h.screen = true; h.tick(); h.now = 9000; h.tick();
        check(h.opens == 0 && h.state().equals("WAITING_GUI"), "loading and existing container never get closed or timed out");
        h.screen = false; h.tick(); check(h.opens == 1, "loading completed without physical input can be protected");
        h = new Harness(); h.screen = true; h.tick(); h.policy.physicalActivity(h.control.epoch()); h.screen = false; h.tick();
        check(h.opens == 0 && h.state().equals("CANCELLED"), "human closing a GUI cancels pending menu");
        h = new Harness(); h.policy.physicalActivity(h.control.epoch()); h.tick();
        check(h.opens == 0 && h.state().equals("CANCELLED"), "physical input before first tick is retained");
        h.stop(); h.tick(); check(h.opens == 1, "old-epoch physical event cannot block a later stop");
        h = new Harness(); h.held = true; h.tick(); h.held = false; h.tick();
        check(h.opens == 0, "held physical key cancels instead of postponing an intrusive menu");

        h = new Harness(); h.control.stop(ControlArbiter.Mode.PAUSED); h.tick();
        check(h.opens == 0 && h.state().equals("WAITING_RELEASE"), "arbiter release must be confirmed");
        h.release(); h.tick(); check(h.opens == 1, "release cleanup unlocks only menu protection");
        for (int kind = 0; kind < 2; kind++) {
            h = new Harness(); if (kind == 0) h.clear = false; else h.idle = false;
            h.tick(); h.now = 1999; h.tick(); check(h.opens == 0 && h.state().equals("WAITING_RELEASE"), "owned input or task cleanup still pending");
            h.now = 2000; h.tick(); h.clear = h.idle = true; h.tick();
            check(h.opens == 0 && h.state().equals("FAILED"), "cleanup timeout never silently retries");
        }
        h = new Harness(); h.tick(); h.now = 2000; h.tick(); h.tick();
        check(h.opens == 1 && h.state().equals("FAILED"), "unconfirmed menu is not successful and does not spam");
        h = new Harness(); h.accepted = false; h.tick(); h.tick(); check(h.opens == 1 && h.state().equals("FAILED"), "context refusal is bounded");
        h = new Harness(); h.throwing = true; h.tick(); h.tick(); check(h.opens == 1 && h.state().equals("FAILED"), "menu failure leaves control paused");
        check(h.control.mode() == ControlArbiter.Mode.PAUSED && h.control.released(), "failure does not change authority or release proof");
        h = new Harness(); h.paused = true; h.tick(); check(h.opens == 0 && h.state().equals("CONFIRMED"), "already-paused world needs no menu action");
        h.paused = false; h.connection = new Object(); h.tick(); check(h.opens == 1, "replacement connection cannot inherit stale confirmation");
        h.server = new Object(); h.tick(); check(h.opens == 2, "integrated server identity scopes action");
        h.session = "world-session-replacement"; h.tick(); check(h.opens == 3, "world session scopes action");
        h = new Harness(); h.presentation = false; h.tick(); h.now = 1999; h.tick();
        check(h.opens == 0 && h.state().equals("WAITING_PRESENTATION"), "wait for completed world frames before cold-entry menu");
        h.presentation = true; h.tick();
        check(h.opens == 1 && !h.policy.proof().get("presentation_wait_timed_out").getAsBoolean(), "frame readiness opens menu without timeout");
        h = new Harness(); h.presentation = false; h.tick(); h.now = 2000; h.tick();
        check(h.opens == 1 && h.policy.proof().get("presentation_wait_timed_out").getAsBoolean(), "missing frames have bounded safety fallback");
        h.paused = true; h.tick(); check(h.state().equals("CONFIRMED"), "fallback still requires actual paused observation");
        h.stop(); h.now = 9000; h.paused = false; h.tick();
        check(h.opens == 1 && h.state().equals("WAITING_PRESENTATION"), "new epoch cannot inherit render timeout");
        h.policy.physicalActivity(h.control.epoch()); h.tick();
        check(h.state().equals("CANCELLED") && h.opens == 1, "physical input cancels first-frame wait");
        h = new Harness(); h.presentation = false; h.alive = false; h.tick();
        check(h.state().equals("DEAD") && h.opens == 0, "frame wait never replaces death screen");
        h = new Harness(); h.presentation = false; h.server = null; h.tick();
        check(h.state().equals("UNSUPPORTED") && h.opens == 0, "frame wait never pauses multiplayer");
        h = new Harness(); h.presentation = false; h.screen = true; h.tick(); h.now = 9000; h.tick();
        h.screen = false; h.tick(); check(h.state().equals("WAITING_PRESENTATION"), "existing GUI does not consume render wait allowance");
        JsonObject proof = h.policy.proof(); check(num(proof, "input_actions_issued") == 0, "diagnostics never claim game input");
        System.out.println("PASS: " + checks + " singleplayer pause authority/lifecycle/GUI/physical/cleanup/confirmation checks; JVM_FIXTURE_NOT_REAL_GAME");
    }
}
