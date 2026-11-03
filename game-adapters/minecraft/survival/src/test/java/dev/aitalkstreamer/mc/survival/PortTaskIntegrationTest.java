package dev.aitalkstreamer.mc.survival;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.*;
import org.junit.jupiter.api.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.BooleanSupplier;
import static dev.aitalkstreamer.mc.core.Json.*;
import static org.junit.jupiter.api.Assertions.*;

/** New port session + actual survival runner + actual native arbiter/input ledger. Game effects are fixtures. */
class PortTaskIntegrationTest {
    final AtomicLong now = new AtomicLong(10000);
    final ControlArbiter control = new ControlArbiter(now::get, () -> {});
    final Map<String, Boolean> keys = new HashMap<>();
    final InputLedger<String> ledger = new InputLedger<>(keys::put, key -> false);
    final InputLeaseFence fence = new InputLeaseFence(ledger::release);
    final List<Runnable> signals = new ArrayList<>();
    final List<JsonObject> results = new ArrayList<>();
    InventoryTarget receivedTarget;
    BaseTarget receivedBase;
    Runnable tick = () -> {}, stop = () -> {};
    final ControlledTaskRunner<String> driver = new ControlledTaskRunner<>(new ControlledTaskRunner.Runtime<>() {
        public void start(String task, Runnable finished) { signals.add(finished); SurvivalAuthority.write(() -> ledger.press("forward")); }
        public void tick() { SurvivalAuthority.requireScope(); tick.run(); }
        public void stop() { stop.run(); signals.getLast().run(); }
        public List<Runnable> cleanup() { return List.of(); }
    });
    final ExecutorTaskSession port = new ExecutorTaskSession(new ExecutorTaskSession.Runtime() {
        public void start(JsonObject task, ControlArbiter actual, ControlArbiter.Permit permit, InventoryTarget target, BaseTarget base, Runnable finished) {
            receivedTarget = target; receivedBase = base;
            var actualBoundary = new ArbiterBoundary(actual, permit, str(task, "task_id"));
            var input = fence.ticket();
            var boundary = new SurvivalAuthority.Boundary() {
                public boolean current(SurvivalAuthority.Context context) { return actualBoundary.current(context); }
                public void actuate(SurvivalAuthority.Context context, BooleanSupplier open, Runnable write) {
                    actualBoundary.actuate(context, open, () -> { input.check(); write.run(); });
                }
                public void releaseOwnedInputs(SurvivalAuthority.Context context) {
                    if (!actual.release(permit.epoch(), input::release)) input.release();
                }
            };
            var context = new SurvivalAuthority.Context(str(task, "task_id"), permit.controller(), permit.lease(), permit.world(), permit.epoch());
            driver.start(context, boundary, () -> "FIXTURE_GAME_TASK", signal -> finished.run());
        }
        public void tick() { driver.tick(); }
        public void cancel() { driver.cancel(); }
    });
    int number;
    @BeforeEach void setup() { control.world("session-1"); control.attach("controller-1"); grant(); }
    private void grant() {
        control.release(control.epoch(), () -> {}); control.observe(1);
        control.beginAuto("controller-1", "session-1", control.epoch(), true);
        control.grant("controller-1", control.lease(), control.epoch(), 1, control.heartbeat(), 10000);
    }
    private JsonObject observation(long seq, int x) {
        return obj("game_instance_id", "instance-1", "bridge_boot_id", "boot-1", "world_id", "world-1", "world_session_id", "session-1",
                "control_epoch", control.epoch(), "seq", seq, "screen", "gameplay", "player", obj("position", position(x)), "inventory", List.of());
    }
    private JsonObject position(int x) { return obj("dimension", "minecraft:overworld", "x", x, "y", 64, "z", 0); }
    private void start() {
        var task = obj("task_id", "task-" + ++number, "game_instance_id", "instance-1", "bridge_boot_id", "boot-1", "world_id", "world-1",
                "world_session_id", "session-1", "control_epoch", control.epoch(), "goal", obj("skill", "navigate", "target", position(10), "radius", 1.0));
        port.start(task, observation(1, 0), control, results::add);
    }
    @AfterEach void cleanup() { stop = () -> {}; port.cancel("TEST_CLEANUP"); driver.cancel(); }
    @Test void originalPermitReachesRealInputAndCleanupPrecedesLaterEffectVerification() {
        start(); assertTrue(keys.get("forward")); assertFalse(control.released());
        tick = () -> signals.getLast().run(); port.tick(observation(2, 10));
        assertFalse(keys.get("forward")); assertTrue(control.released()); assertFalse(driver.active()); assertTrue(results.isEmpty());
        port.tick(observation(3, 10)); assertEquals("succeeded", str(results.getFirst(), "state")); assertFalse(port.active());
    }
    @Test void revokedOldCallbackCannotReleaseTheReplacementInput() {
        start(); Runnable old = signals.getFirst(); port.cancel("cancel"); start(); assertTrue(keys.get("forward"));
        tick = old; port.tick(observation(2, 10)); port.tick(observation(3, 10));
        assertTrue(port.active()); assertTrue(driver.active()); assertTrue(keys.get("forward")); assertEquals(1, results.size());
    }
    @Test void upstreamStopFailureRetainsBothRootsUntilCleanupIsRetried() {
        start(); stop = () -> { throw new IllegalStateException("stop"); };
        assertThrows(IllegalStateException.class, () -> port.cancel("cancel"));
        assertTrue(port.active()); assertTrue(driver.active()); assertTrue(results.isEmpty()); assertFalse(keys.get("forward"));
        stop = () -> {}; port.cancel("retry"); assertFalse(port.active()); assertFalse(driver.active()); assertEquals("cancelled", str(results.getFirst(), "state"));
    }
    @Test void worldChangeReleasesOriginalInputsAndCannotYieldVerifiedArrival() {
        start(); control.world("session-2"); var changed = observation(2, 10); changed.addProperty("world_session_id", "session-2");
        port.tick(changed); assertFalse(keys.get("forward")); assertFalse(driver.active());
        assertEquals("cancelled", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void aCancelledDriverWhichInvokesCompletionStillCannotReportSuccess() {
        start(); port.cancel("OPERATOR_CANCELLED"); port.tick(observation(2, 10));
        assertEquals(1, results.size()); assertEquals("cancelled", str(results.getFirst(), "state")); assertFalse(keys.get("forward"));
    }
    private void goHome() {
        var task = obj("task_id", "home-1", "game_instance_id", "instance-1", "bridge_boot_id", "boot-1", "world_id", "world-1",
                "world_session_id", "session-1", "control_epoch", control.epoch(), "goal", obj("skill", "return_base", "base_id", "base-1"),
                "base_target", obj("game_instance_id", "instance-1", "world_id", "world-1", "base_id", "base-1", "base_revision", 1,
                        "world_revision", 3, "position", position(10), "radius", 2, "source", "operator_observed",
                        "registered_world_session_id", "session-old", "registered_seq", 1));
        port.start(task, observation(1, 0), control, results::add);
    }
    @Test void actualRunnerReleasesOriginalInputBeforeALaterRegisteredBaseArrival() {
        goHome(); assertEquals("base-1", receivedBase.baseId()); assertEquals(10, receivedBase.x());
        assertTrue(keys.get("forward")); tick = () -> signals.getLast().run(); port.tick(observation(2, 10));
        assertFalse(keys.get("forward")); assertTrue(control.released()); assertTrue(results.isEmpty());
        port.tick(observation(3, 10)); assertEquals("succeeded", str(results.getFirst(), "state")); assertFalse(driver.active());
    }
    @Test void endedActualRunnerDoesNotProveReturnToAnUnreachedBase() {
        goHome(); tick = () -> signals.getLast().run(); port.tick(observation(2, 0)); port.tick(observation(3, 0));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
        assertFalse(keys.get("forward")); assertTrue(control.released());
    }
    private JsonObject stock(long seq, int count) {
        var observed = observation(seq, 0);
        observed.add("inventory", GSON.toJsonTree(List.of(obj("item_id", "minecraft:oak_log", "count", count))));
        return observed;
    }
    private void collect(int baseline) {
        var task = obj("task_id", "collect-1", "game_instance_id", "instance-1", "bridge_boot_id", "boot-1", "world_id", "world-1",
                "world_session_id", "session-1", "control_epoch", control.epoch(),
                "goal", obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4));
        port.start(task, stock(1, baseline), control, results::add);
    }
    @Test void actualRunnerReceivesTheIncrementTargetAndDoesNotAcceptOnlyOneNewLog() {
        collect(3); assertEquals(7, receivedTarget.targetTotal()); assertTrue(keys.get("forward"));
        tick = () -> signals.getLast().run(); port.tick(stock(2, 4)); assertTrue(control.released());
        port.tick(stock(3, 4)); assertEquals("failed", str(results.getFirst(), "state"));
        assertEquals("partial", str(results.getFirst(), "effect_status")); assertFalse(driver.active());
    }
    @Test void existingStockAboveTheIncrementStillRequiresFourNewLogsWithTheRealRunner() {
        collect(10); assertEquals(14, receivedTarget.targetTotal());
        tick = () -> signals.getLast().run(); port.tick(stock(2, 14)); port.tick(stock(3, 14));
        assertEquals("succeeded", str(results.getFirst(), "state")); assertTrue(control.released()); assertFalse(keys.get("forward"));
    }
}
