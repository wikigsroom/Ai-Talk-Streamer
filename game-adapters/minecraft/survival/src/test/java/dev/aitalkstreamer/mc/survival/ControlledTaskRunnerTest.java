package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.*;
import org.junit.jupiter.api.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.function.*;
import static org.junit.jupiter.api.Assertions.*;

/** The actual runner + native arbiter/input ledger; only the game's task effects are fixtures. */
class ControlledTaskRunnerTest {
    private final AtomicLong now = new AtomicLong(10000);
    private final ControlArbiter control = new ControlArbiter(now::get, () -> {});
    private final Map<String, Boolean> keys = new HashMap<>();
    private final InputLedger<String> ledger = new InputLedger<>(keys::put, key -> false);
    private final InputLeaseFence fence = new InputLeaseFence(ledger::release);
    private final List<Runnable> signals = new ArrayList<>();
    private final List<String> order = new ArrayList<>(), results = new ArrayList<>();
    private Runnable tickAction = () -> {}, stopAction = () -> {}, firstCleanup = () -> {}, inputCleanup = () -> {};
    private Runnable beforeComplete = () -> {};
    private final AtomicInteger ticks = new AtomicInteger();
    private int taskNumber;
    private final ControlledTaskRunner<String> runner = new ControlledTaskRunner<>(new ControlledTaskRunner.Runtime<>() {
        public void start(String task, Runnable finished) {
            assertTrue(SurvivalAuthority.inScope()); signals.add(finished);
            SurvivalAuthority.write(() -> ledger.press("use"));
        }
        public void tick() { ticks.incrementAndGet(); tickAction.run(); }
        public void beforeComplete() { beforeComplete.run(); }
        public void stop() {
            assertFalse(SurvivalAuthority.inScope()); SurvivalAuthority.requireOwnerScope();
            order.add("stop"); stopAction.run();
            if (!signals.isEmpty()) signals.getLast().run(); // Upstream cancel also emits completion.
        }
        public List<Runnable> cleanup() {
            return List.of(() -> { order.add("path"); firstCleanup.run(); }, () -> order.add("overrides"), () -> order.add("pulses"));
        }
    });
    @BeforeEach void setup() {
        control.world("world"); control.attach("controller"); control.release(control.epoch(), () -> {}); control.observe(1);
        control.beginAuto("controller", "world", control.epoch(), true);
        control.grant("controller", control.lease(), control.epoch(), 1, control.heartbeat(), 10000);
    }
    private void start() { start(results::add); }
    private void start(Consumer<String> completed) {
        var permit = control.permit(); String id = "task-" + ++taskNumber;
        var context = new SurvivalAuthority.Context(id, permit.controller(), permit.lease(), permit.world(), permit.epoch());
        runner.start(context, boundary(id, permit), () -> "fixture task", completed);
    }
    private SurvivalAuthority.Boundary boundary(String id, ControlArbiter.Permit permit) {
        var actual = new ArbiterBoundary(control, permit, id); var ticket = fence.ticket();
        return new SurvivalAuthority.Boundary() {
            public boolean current(SurvivalAuthority.Context context) { return actual.current(context); }
            public void actuate(SurvivalAuthority.Context context, BooleanSupplier open, Runnable effect) {
                actual.actuate(context, open, () -> { ticket.check(); effect.run(); });
            }
            public void releaseOwnedInputs(SurvivalAuthority.Context context) {
                order.add("inputs"); inputCleanup.run(); ticket.release();
            }
        };
    }
    @AfterEach void cleanup() {
        stopAction = () -> {}; firstCleanup = () -> {}; inputCleanup = () -> {}; runner.cancel();
    }
    @Test void completionRestoresAllInputsBeforeRequestingEffectVerification() {
        start(); tickAction = () -> signals.getFirst().run(); runner.tick();
        assertFalse(runner.active()); assertFalse(keys.get("use")); assertTrue(ledger.empty());
        assertEquals(List.of("stop", "path", "overrides", "pulses", "inputs"), order);
        assertEquals(List.of("EXECUTION_FINISHED_REQUIRES_EFFECT_VERIFICATION"), results);
    }
    @Test void cancellationNeverPublishesASuccessOrCompletionRequest() {
        start(); runner.cancel(); assertTrue(results.isEmpty()); assertFalse(keys.get("use")); assertFalse(runner.active());
    }
    @Test void aSupplyFailureClosesTheActualRootAndReleasesItsOwnedInputs() {
        var policy=new SupplyPolicy(now.get(),40,new SupplyPolicy.Facts(0,0),new SupplyPolicy.Limits(3000,2000,96));
        start();var signal=signals.getFirst();
        tickAction=()->{var decision=policy.observe(now.get(),new SupplyPolicy.Facts(0,0));
            if(decision.mode()==SupplyPolicy.Mode.FAILED)throw new LocalTaskFailure(decision.reason());};
        now.addAndGet(1000);control.observe(2);runner.tick();assertTrue(runner.active());
        now.addAndGet(1000);control.observe(3);
        assertEquals(LocalTaskFailure.Reason.SUPPLY_NO_PROGRESS,assertThrows(LocalTaskFailure.class,runner::tick).reason);
        assertFalse(runner.active());assertFalse(keys.get("use"));assertTrue(ledger.empty());assertTrue(results.isEmpty());
        signal.run();assertTrue(results.isEmpty());assertFalse(SurvivalAuthority.inScope());
    }
    @Test void manualRevocationPreventsTheNextSupplyTickFromReplacingTheOriginalCancellation() {
        start();tickAction=()->{throw new LocalTaskFailure(LocalTaskFailure.Reason.SUPPLY_TIMEOUT);};
        control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY);assertDoesNotThrow(runner::tick);
        assertFalse(runner.active());assertFalse(keys.get("use"));assertTrue(ledger.empty());assertTrue(results.isEmpty());
        assertThrows(SurvivalAuthority.Denied.class,()->runner.effect(()->fail("revoked supply resumed")));
    }
    @Test void aDefenseDeadlineClosesTheActualRootAndInputsWithoutSignallingGoalSuccess() {
        var policy=new DefensePolicy(now.get());var scene=new DefensePolicyTest.Scene();policy.observe(now.get(),scene.facts());
        start();var oldSignal=signals.getFirst();
        tickAction=()->{var decision=policy.observe(now.get(),scene.facts());
            if(decision.mode()==DefensePolicy.Mode.FAILED)throw new LocalTaskFailure(decision.reason());};
        for(int second=1;second<6;second++) { now.addAndGet(1000);control.observe(second+1);assertDoesNotThrow(runner::tick); }
        now.addAndGet(1000);control.observe(7);assertTrue(control.allowed());
        var failure=assertThrows(LocalTaskFailure.class,runner::tick);
        assertEquals("GAME_DEFENSE_NO_PROGRESS",failure.code());assertFalse(runner.active());
        assertTrue(ledger.empty());assertFalse(keys.get("use"));assertTrue(results.isEmpty());oldSignal.run();assertTrue(results.isEmpty());
        assertEquals(List.of("stop","path","overrides","pulses","inputs"),order);
    }
    @Test void clientStallClosesTheRootBeforeASeparateDefenseDeadlineCanRun() {
        start();var original=control.permit();tickAction=()->fail("A stale client cannot execute its defense checkpoint.");
        now.addAndGet(6000);assertEquals(4000,control.remaining());assertFalse(control.allowed());
        assertEquals("GAME_CLIENT_TICK_STALLED",control.revocationReason(original));assertDoesNotThrow(runner::tick);
        assertEquals(0,ticks.get());assertFalse(runner.active());assertTrue(ledger.empty());assertTrue(results.isEmpty());
    }
    @Test void naturalGuiRestorationRunsInTheOriginalScopeBeforeRevokedCleanup() {
        beforeComplete = () -> { assertTrue(SurvivalAuthority.inScope()); SurvivalAuthority.write(() -> order.add("gui")); };
        start(); tickAction = () -> signals.getFirst().run(); runner.tick();
        assertEquals(List.of("gui", "stop", "path", "overrides", "pulses", "inputs"), order); assertEquals(1, results.size());
    }
    @Test void manualCancellationDoesNotCloseAGuiForTheOperator() {
        beforeComplete = () -> fail("revoked cleanup must not run natural GUI restoration");
        start(); control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY); runner.cancel(); assertTrue(results.isEmpty()); assertFalse(runner.active());
    }
    @Test void guiRestorationFailureStillReleasesInputsAndDoesNotRequestSuccessVerification() {
        beforeComplete = () -> { throw new IllegalStateException("cursor not empty"); };
        start(); tickAction = () -> signals.getFirst().run(); assertThrows(IllegalStateException.class, runner::tick);
        assertFalse(runner.active()); assertFalse(keys.get("use")); assertTrue(results.isEmpty());
    }
    @Test void stopFailureStillRunsEveryCleanupAndPreventsANewRootUntilRetry() {
        start(); stopAction = () -> { throw new IllegalStateException("stop"); };
        assertEquals("stop", assertThrows(IllegalStateException.class, runner::cancel).getMessage());
        assertEquals(List.of("stop", "path", "overrides", "pulses", "inputs"), order);
        assertFalse(keys.get("use")); assertTrue(runner.active()); assertThrows(IllegalStateException.class, this::start);
        stopAction = () -> {}; runner.cancel(); start(); assertTrue(runner.active());
    }
    @Test void pathFailureStillClearsOverridesPulsesAndTheNativeLedger() {
        start(); firstCleanup = () -> { throw new IllegalArgumentException("path"); };
        assertThrows(IllegalArgumentException.class, runner::cancel);
        assertTrue(order.containsAll(List.of("overrides", "pulses", "inputs"))); assertFalse(keys.get("use"));
        firstCleanup = () -> {}; runner.cancel(); assertFalse(runner.active());
    }
    @Test void nativeInputRestorationFailureRetainsTheRootForRetry() {
        start(); inputCleanup = () -> { throw new IllegalStateException("inputs"); };
        assertThrows(IllegalStateException.class, runner::cancel); assertTrue(keys.get("use")); assertTrue(runner.active());
        assertThrows(IllegalStateException.class, this::start); inputCleanup = () -> {}; runner.cancel(); assertFalse(keys.get("use"));
    }
    @Test void oldCompletionCannotFinishTheNextRootEvenWhenCalledInItsScope() {
        start(); Runnable old = signals.getFirst(); runner.cancel(); start();
        tickAction = old; runner.tick(); assertTrue(runner.active()); assertTrue(results.isEmpty());
        tickAction = () -> signals.getLast().run(); runner.tick(); assertEquals(1, results.size());
    }
    @Test void offThreadCompletionDoesNotAcquireTheClientScope() throws InterruptedException {
        start(); Thread worker = new Thread(signals.getFirst()); worker.start(); worker.join(3000); assertFalse(worker.isAlive());
        runner.tick(); assertTrue(runner.active()); assertTrue(results.isEmpty());
    }
    @Test void expiredLeaseCancelsBeforeAnotherTickAndDoesNotClaimAnEffect() {
        start(); now.addAndGet(10001); runner.tick();
        assertEquals(0, ticks.get()); assertFalse(runner.active()); assertFalse(keys.get("use")); assertTrue(results.isEmpty());
    }
    @Test void tickFailurePreservesTheOriginalErrorAndCleanupFailure() {
        start(); tickAction = () -> { throw new IllegalArgumentException("tick"); };
        firstCleanup = () -> { throw new IllegalStateException("path"); };
        var failure = assertThrows(IllegalArgumentException.class, runner::tick);
        assertEquals("tick", failure.getMessage()); assertEquals("path", failure.getSuppressed()[0].getMessage());
        assertFalse(keys.get("use")); assertTrue(results.isEmpty());
    }
    @Test void completionCallbackCanStartANewRootAndItsExceptionDoesNotCancelIt() {
        start(value -> { results.add(value); start(); throw new IllegalArgumentException("notification"); });
        tickAction = () -> signals.getFirst().run();
        assertEquals("notification", assertThrows(IllegalArgumentException.class, runner::tick).getMessage());
        assertTrue(runner.active()); assertTrue(keys.get("use")); assertEquals(1, results.size());
    }
    @Test void reentrantCancellationDoesNotRecursivelyRunCleanupOrStartANewRoot() {
        start(); firstCleanup = () -> { runner.cancel(); assertThrows(IllegalStateException.class, this::start); };
        runner.cancel(); assertEquals(1, Collections.frequency(order, "path")); assertFalse(runner.active());
    }
    @Test void preparationFailureReleasesTheRootAndDoesNotStartATask() {
        var permit = control.permit(); String id = "bad-preparation";
        var context = new SurvivalAuthority.Context(id, permit.controller(), permit.lease(), permit.world(), permit.epoch());
        assertThrows(IllegalArgumentException.class, () -> runner.start(context, boundary(id, permit),
                () -> { throw new IllegalArgumentException("prepare"); }, results::add));
        assertTrue(signals.isEmpty()); assertFalse(runner.active()); assertTrue(results.isEmpty());
        assertTrue(order.contains("inputs")); start(); assertTrue(runner.active());
    }
    @Test void actualDriverRejectsAnUnboundInputBoundaryBeforeTouchingTheGame() {
        var permit = control.permit(); String id = "unbound";
        var context = new SurvivalAuthority.Context(id, permit.controller(), permit.lease(), permit.world(), permit.epoch());
        var failure = assertThrows(IllegalArgumentException.class, () -> new ControlledAltoClefDriver().start(context,
                new ArbiterBoundary(control, permit, id), new com.google.gson.JsonObject(), null, null, results::add));
        assertEquals("GAME_EXECUTOR_INPUTS_NOT_BOUND", failure.getMessage()); assertFalse(runner.active());
    }
    @Test void workerFailureIsReportedAndCleanedEvenAfterItRevokesTheRoot() throws Exception {
        try (var worker = java.util.concurrent.Executors.newSingleThreadExecutor()) {
            start(); tickAction = () -> SurvivalAsync.execute(worker, () -> { throw new IllegalArgumentException("calculation"); });
            runner.tick(); worker.submit(() -> {}).get(3, java.util.concurrent.TimeUnit.SECONDS);
            assertEquals("GAME_SURVIVAL_ASYNC_FAILED", assertThrows(IllegalStateException.class, runner::tick).getMessage());
            assertFalse(runner.active()); assertFalse(keys.get("use")); assertTrue(order.contains("path")); assertTrue(results.isEmpty());
        }
    }
    @Test void queuedWorkerResultIsAppliedBeforeTheNextActualRuntimeTick() throws Exception {
        try (var worker = java.util.concurrent.Executors.newSingleThreadExecutor()) {
            AtomicInteger applied = new AtomicInteger(); start();
            tickAction = () -> SurvivalAsync.execute(worker, () -> SurvivalAsync.commit(applied::incrementAndGet));
            runner.tick(); worker.submit(() -> {}).get(3, java.util.concurrent.TimeUnit.SECONDS);
            assertEquals(0, applied.get()); tickAction = () -> assertEquals(1, applied.get()); runner.tick();
            assertEquals(1, applied.get()); assertTrue(runner.active());
        }
    }
    @Test void heldVanillaContinuationReentersOnlyTheActualLiveRoot() {
        start();assertFalse(SurvivalAuthority.inScope());var effects=new AtomicInteger();
        runner.effect(()->{assertTrue(SurvivalAuthority.inScope());effects.incrementAndGet();});
        assertEquals(1,effects.get());assertFalse(SurvivalAuthority.inScope());assertTrue(runner.active());
    }
    @Test void revokedHeldContinuationCannotBorrowARegrant() {
        start();control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY);control.release(control.epoch(),()->{});control.observe(2);
        control.beginAuto("controller","world",control.epoch(),true);control.grant("controller",control.lease(),control.epoch(),1,control.heartbeat(),10000);
        var effects=new AtomicInteger();assertThrows(SurvivalAuthority.Denied.class,()->runner.effect(effects::incrementAndGet));assertEquals(0,effects.get());
    }
    @Test void heldContinuationCannotWriteWhileTheRootIsClosing() {
        start();stopAction=()->assertThrows(SurvivalAuthority.Denied.class,()->runner.effect(()->fail("closing root wrote")));
        runner.cancel();assertFalse(runner.active());
    }
    @Test void aFinishedRootDoesNotStartAnotherHeldEffectBeforeCleanup() {
        start();tickAction=()->{
            signals.getFirst().run();assertThrows(SurvivalAuthority.Denied.class,()->runner.effect(()->fail("finished root wrote")));
        };
        runner.tick();assertFalse(runner.active());assertEquals(1,results.size());
    }
    @Test void heldContinuationFromAnotherThreadCannotEnterTheGameScope() throws InterruptedException {
        start();var denied=new AtomicBoolean();
        Thread worker=new Thread(()->{try {runner.effect(()->fail("worker wrote"));} catch(SurvivalAuthority.Denied e){denied.set(true);}});
        worker.start();worker.join(3000);assertFalse(worker.isAlive());assertTrue(denied.get());assertTrue(runner.active());
    }
    @Test void failingHeldEffectIsExecutedOnceAndLeavesNoAmbientScope() {
        start();var effects=new AtomicInteger();var original=new IllegalStateException("partial native write");
        assertSame(original,assertThrows(IllegalStateException.class,()->runner.effect(()->{effects.incrementAndGet();throw original;})));
        assertEquals(1,effects.get());assertFalse(SurvivalAuthority.inScope());runner.cancel();
        assertThrows(SurvivalAuthority.Denied.class,()->runner.effect(()->fail("retired root wrote")));
    }

}
