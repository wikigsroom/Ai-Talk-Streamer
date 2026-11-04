package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import static dev.aitalkstreamer.mc.core.Json.*;
import static org.junit.jupiter.api.Assertions.*;

/** Actual task session and arbiter; inventory/positions and the game driver are fixtures. */
class ExecutorTaskSessionTest {
    final AtomicLong now = new AtomicLong(10000);
    final ControlArbiter control = new ControlArbiter(now::get, () -> {});
    final List<Runnable> signals = new ArrayList<>();
    final List<JsonObject> results = new ArrayList<>();
    int starts, ticks, cancels;
    boolean guiAllowed;
    CraftReceipt craftReceipt;
    ItemUseReceipt itemUseReceipt;
    Runnable tick = () -> {}, stop = () -> {}, onStart = () -> {};
    JsonObject task, before;
    InventoryTarget receivedTarget;
    BaseTarget receivedBase;
    JsonObject receivedTask;
    final ExecutorTaskSession session = new ExecutorTaskSession(new ExecutorTaskSession.Runtime() {
        public void start(JsonObject task, ControlArbiter actual, ControlArbiter.Permit permit, InventoryTarget target, BaseTarget base, Runnable done) {
            starts++; receivedTask = task; receivedTarget = target; receivedBase = base;
            assertSame(control, actual); assertEquals(control.permit(), permit); signals.add(done); onStart.run();
        }
        public void tick() { ticks++; tick.run(); }
        public void cancel() { cancels++; stop.run(); }
        public boolean allowsGui() { return guiAllowed; }
        public CraftReceipt craftReceipt() { return craftReceipt; }
        public ItemUseReceipt itemUseReceipt() { return itemUseReceipt; }
    });
    @BeforeEach void setup() {
        control.world("session-1"); control.attach("controller-1"); control.release(control.epoch(), () -> {}); control.observe(1);
        control.beginAuto("controller-1", "session-1", control.epoch(), true);
        control.grant("controller-1", control.lease(), control.epoch(), 1, control.heartbeat(), 10000);
        task = obj("task_id", "task-1", "game_instance_id", "instance-1", "bridge_boot_id", "boot-1", "world_id", "world-1",
                "world_session_id", "session-1", "control_epoch", control.epoch(), "goal", obj("skill", "navigate", "target", position(10), "radius", 1.0));
        before = observation(1, 0, 0);
    }
    private JsonObject position(int x) { return obj("dimension", "minecraft:overworld", "x", x, "y", 64, "z", 0); }
    private JsonObject observation(long seq, int x, int count) {
        return obj("game_instance_id", "instance-1", "bridge_boot_id", "boot-1", "world_id", "world-1", "world_session_id", "session-1",
                "control_epoch", control.epoch(), "seq", seq, "screen", "gameplay", "player", obj("position", position(x)),
                "inventory", List.of(obj("item_id", "minecraft:oak_log", "count", count)));
    }
    private void start() { session.start(task, before, control, results::add); }
    private void finished() { tick = () -> signals.getLast().run(); session.tick(observation(2, 10, 0)); }
    private void item(String purpose) {
        task.add("goal", obj("skill", "use_item", "item_id", "minecraft:oak_log", "purpose", purpose)); before = observation(1, 0, 3);
    }
    private ItemUseReceipt itemReceipt(String purpose, boolean inventory, boolean effect, boolean clean) {
        return new ItemUseReceipt("task-1", "session-1", control.epoch(), "minecraft:oak_log", purpose, 3,
                inventory && !purpose.equals("equip") ? 1 : 0, "TEST_FIXTURE_ONLY", inventory ? 9 : -1, inventory, effect, clean);
    }
    @Test void itemConsumptionWaitsForTheBoundReceiptAndANewerObservation() {
        item("eat"); start(); itemUseReceipt = itemReceipt("eat", true, true, true); finished(); assertTrue(results.isEmpty());
        session.tick(observation(3, 0, 2)); assertEquals("verified", str(results.getFirst(), "effect_status"));
        assertEquals("item_effect", str(results.getFirst().getAsJsonArray("evidence").get(0).getAsJsonObject(), "kind"));
    }
    @Test void anInventoryDecreaseWithoutAnItemSpecificReceiptCannotSucceed() {
        item("eat"); start(); finished(); session.tick(observation(3, 0, 2));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void aConsumedItemWithoutItsFoodEffectRemainsPartial() {
        item("eat"); start(); itemUseReceipt = itemReceipt("eat", true, false, true); finished(); session.tick(observation(3, 0, 2));
        assertEquals("partial", str(results.getFirst(), "effect_status"));
    }
    @Test void placementRequiresItsBlockEffectAndACompatibleLaterCount() {
        item("activate"); start(); itemUseReceipt = itemReceipt("activate", true, true, true); finished(); session.tick(observation(3, 0, 3));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("partial", str(results.getFirst(), "effect_status"));
    }
    @Test void equipmentCanBeVerifiedWithoutFabricatingInventoryConsumption() {
        item("equip"); start(); itemUseReceipt = itemReceipt("equip", true, true, true); finished(); session.tick(observation(3, 0, 3));
        assertEquals("succeeded", str(results.getFirst(), "state"));
    }
    @Test void aReceiptFromAnotherPurposeOrTaskCannotVerifyThisUse() {
        item("eat"); start(); itemUseReceipt = itemReceipt("activate", true, true, true); finished(); session.tick(observation(3, 0, 2));
        assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void aDifferentStartingQuantityCannotBorrowTheReceipt() {
        item("eat"); before = observation(1, 0, 4); start(); itemUseReceipt = itemReceipt("eat", true, true, true); finished(); session.tick(observation(3, 0, 2));
        assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void cancellationRetainsAConfirmedPartialPlacement() {
        item("activate"); start(); itemUseReceipt = itemReceipt("activate", false, true, false); session.cancel("OPERATOR");
        assertEquals("cancelled", str(results.getFirst(), "state")); assertEquals("partial", str(results.getFirst(), "effect_status")); assertEquals(1, cancels);
    }
    @Test void queuedTakeoverRetainsItsFirstReasonAndAcknowledgedEquipmentWithoutTickingOrReviving() {
        item("equip"); start(); Runnable old = signals.getFirst(); itemUseReceipt = itemReceipt("equip", true, false, false);
        control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY, "PHYSICAL_INPUT"); control.stop(ControlArbiter.Mode.PAUSED, "DISCONNECTED");
        session.tick(observation(2, 0, 3));
        assertEquals(0, ticks); assertEquals(1, cancels); assertFalse(session.active());
        assertEquals("PHYSICAL_INPUT", str(results.getFirst(), "reason")); assertEquals("partial", str(results.getFirst(), "effect_status"));
        control.release(control.epoch(), () -> {}); control.observe(3);
        control.beginAuto("controller-1", "session-1", control.epoch(), true);
        control.grant("controller-1", control.lease(), control.epoch(), 1, control.heartbeat(), 10000);
        task.addProperty("task_id", "task-2"); task.addProperty("control_epoch", control.epoch()); before = observation(3, 0, 3); start();
        tick = old; session.tick(observation(4, 0, 3)); session.tick(observation(5, 0, 3));
        assertEquals(1, results.size()); assertTrue(session.active()); session.cancel("TEST_CLEANUP"); assertEquals(2, cancels);
    }
    @Test void itemFailureStillReleasesAndPreservesConfirmedConsumption() {
        item("eat"); start(); itemUseReceipt = itemReceipt("eat", true, false, false); tick = () -> { throw new IllegalStateException("fixture"); };
        assertThrows(IllegalStateException.class, () -> session.tick(observation(2, 0, 2)));
        assertEquals(1, cancels); assertFalse(session.active()); assertEquals("partial", str(results.getFirst(), "effect_status"));
    }
    @Test void itemCompletionCapturesAnImmutableReceiptBeforeLaterRuntimeChanges() {
        item("eat"); start(); itemUseReceipt = itemReceipt("eat", true, true, true); finished(); itemUseReceipt = null;
        session.tick(observation(3, 0, 2)); assertEquals("verified", str(results.getFirst(), "effect_status"));
    }
    @Test void aTaskOwnedInventoryMayContinueButNewAdmissionStillRequiresGameplay() {
        var inventory = observation(1, 0, 0); inventory.addProperty("screen", "inventory"); guiAllowed = true;
        assertThrows(Rejected.class, () -> session.start(task, inventory, control, results::add));
        start(); inventory.addProperty("seq", 2); session.tick(inventory); assertEquals(1, ticks); assertTrue(session.active());
    }
    @Test void losingGuiOwnershipCancelsBeforeAnotherRuntimeTick() {
        start(); var gui = observation(2, 0, 0); gui.addProperty("screen", "container"); guiAllowed = true; session.tick(gui);
        assertEquals(1, ticks); guiAllowed = false; gui.addProperty("seq", 3); session.tick(gui);
        assertEquals(1, ticks); assertFalse(session.active()); assertEquals("cancelled", str(results.getFirst(), "state"));
        assertEquals("GUI_BLOCKED", str(results.getFirst(), "reason"));
    }
    @Test void aGuiHookCannotAuthorizeDeathOrAnArbitraryMenu() {
        start(); guiAllowed = true; var menu = observation(2, 0, 0); menu.addProperty("screen", "menu"); session.tick(menu);
        assertEquals(0, ticks); assertFalse(session.active()); assertEquals("cancelled", str(results.getFirst(), "state"));
    }
    @Test void completionWaitsForANewerObservationAndVerifiesTheRequestedRadius() {
        start(); finished(); assertTrue(results.isEmpty()); assertTrue(session.active());
        session.tick(observation(3, 11, 0)); assertEquals("succeeded", str(results.getFirst(), "state"));
        assertEquals("verified", str(results.getFirst(), "effect_status")); assertFalse(session.active()); assertEquals(1, cancels);
        assertEquals(3, num(results.getFirst().getAsJsonArray("evidence").get(0).getAsJsonObject(), "seq"));
    }
    @Test void upstreamFinishedWithoutPositionEffectCannotSucceed() {
        start(); finished(); session.tick(observation(3, 0, 0));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void matchingCoordinatesInAnotherDimensionAreNotArrival() {
        start(); finished(); var other = observation(3, 10, 0); other.getAsJsonObject("player").getAsJsonObject("position").addProperty("dimension", "minecraft:the_nether");
        session.tick(other); assertEquals("failed", str(results.getFirst(), "state"));
    }
    @Test void missingPlayerDoesNotBecomeAnExceptionOrSuccess() {
        start(); finished(); var absent = observation(3, 10, 0); absent.add("player", JsonNull.INSTANCE);
        session.tick(absent); assertEquals("failed", str(results.getFirst(), "state"));
    }
    @Test void inventoryMustIncreaseByTheFullRequestedIncrementAcrossStacks() {
        task.add("goal", obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4)); before = observation(1, 0, 1);
        start(); finished(); var after = observation(3, 0, 2); after.getAsJsonArray("inventory").add(obj("item_id", "minecraft:oak_log", "count", 3));
        after.getAsJsonArray("inventory").add(obj("item_id", "minecraft:stone", "count", 64)); session.tick(after);
        assertEquals("succeeded", str(results.getFirst(), "state")); assertEquals("verified", str(results.getFirst(), "effect_status"));
        assertEquals(5, receivedTarget.targetTotal()); assertEquals(4, num(receivedTask.getAsJsonObject("goal"), "count"));
    }
    @Test void threeExistingLogsAndOneNewLogDoNotSatisfyARequestForFourMore() {
        task.add("goal", obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4)); before = observation(1, 0, 3);
        start(); assertEquals(7, receivedTarget.targetTotal()); finished(); session.tick(observation(3, 0, 4));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("partial", str(results.getFirst(), "effect_status"));
    }
    @Test void existingStockAboveTheRequestedIncrementStillRequiresNewCollection() {
        task.add("goal", obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4)); before = observation(1, 0, 10);
        start(); assertEquals(14, receivedTarget.targetTotal()); finished(); session.tick(observation(3, 0, 14));
        assertEquals("succeeded", str(results.getFirst(), "state"));
        assertTrue(str(results.getFirst().getAsJsonArray("evidence").get(0).getAsJsonObject(), "summary").contains("net increase is 4"));
    }
    @Test void inventoryLossDoesNotBecomeNewCollection() {
        task.add("goal", obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4)); before = observation(1, 0, 10);
        start(); finished(); session.tick(observation(3, 0, 9)); assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void impossibleInventoryTargetIsRejectedBeforeStartingTheDriver() {
        task.add("goal", obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4)); before = observation(1, 0, Integer.MAX_VALUE);
        assertThrows(Rejected.class, this::start); assertEquals(0, starts); assertFalse(session.active());
    }
    @Test void preexistingInventoryIsNotProofOfNewCollection() {
        task.add("goal", obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4)); before = observation(1, 0, 4);
        start(); finished(); session.tick(observation(3, 0, 4)); assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void insufficientObservedCollectionRemainsPartial() {
        task.add("goal", obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4)); before = observation(1, 0, 1);
        start(); finished(); session.tick(observation(3, 0, 3)); assertEquals("partial", str(results.getFirst(), "effect_status"));
        assertEquals("failed", str(results.getFirst(), "state"));
    }
    @Test void repeatedOldSequenceDoesNotRetickOrInventAResult() {
        start(); finished(); session.tick(observation(2, 10, 0)); session.tick(observation(1, 10, 0));
        assertEquals(1, ticks); assertTrue(results.isEmpty()); session.tick(observation(3, 10, 0)); assertEquals(1, results.size());
    }
    @Test void changedWorldCancelsBeforeTheDriverCanTick() {
        start(); var changed = observation(2, 10, 0); changed.addProperty("world_session_id", "session-2"); session.tick(changed);
        assertEquals(0, ticks); assertEquals("cancelled", str(results.getFirst(), "state")); assertEquals(1, cancels);
        assertEquals("GAME_WORLD_CHANGED", str(results.getFirst(), "reason"));
    }
    @Test void expiredLeaseCancelsInsteadOfVerifyingAnOldCompletion() {
        start(); finished(); now.addAndGet(10001); session.tick(observation(3, 10, 0));
        assertEquals("cancelled", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
        assertEquals("LEASE_EXPIRED", str(results.getFirst(), "reason"));
    }
    @Test void cancellationWhileWaitingForEvidenceDoesNotPublishSuccess() {
        start(); finished(); session.cancel("OPERATOR_CANCELLED"); session.tick(observation(3, 10, 0));
        assertEquals(1, results.size()); assertEquals("cancelled", str(results.getFirst(), "state"));
    }
    @Test void lateOldCompletionCannotCompleteTheReplacement() {
        start(); Runnable old = signals.getFirst(); session.cancel("cancel"); task.addProperty("task_id", "task-2"); start();
        tick = old; session.tick(observation(2, 10, 0)); session.tick(observation(3, 10, 0)); assertEquals(1, results.size()); assertTrue(session.active());
    }
    @Test void workerThreadCompletionCannotBorrowTheClientPermission() throws InterruptedException {
        start(); Thread worker = new Thread(signals.getFirst()); worker.start(); worker.join(3000); assertFalse(worker.isAlive());
        session.tick(observation(2, 10, 0)); session.tick(observation(3, 10, 0)); assertTrue(results.isEmpty());
    }
    @Test void driverExceptionCleansUpAndPublishesOnlyUnknownFailure() {
        start(); tick = () -> { throw new IllegalStateException("driver"); };
        assertThrows(IllegalStateException.class, () -> session.tick(observation(2, 10, 0)));
        assertEquals(1, cancels); assertEquals("failed", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void aKnownDefenseFailureKeepsItsFixedReasonAndReleasesTheRoot() {
        start(); tick=()->{throw new LocalTaskFailure(LocalTaskFailure.Reason.DEFENSE_NO_PROGRESS);};
        assertDoesNotThrow(()->session.tick(observation(2,0,0)));
        assertEquals(1,cancels);assertFalse(session.active());
        assertEquals("GAME_DEFENSE_NO_PROGRESS",str(results.getFirst(),"reason"));
        assertEquals("failed",str(results.getFirst(),"state"));assertEquals("unknown",str(results.getFirst(),"effect_status"));
    }
    @Test void anArbitraryExceptionMessageIsNeverPublishedAsAFailureCode() {
        start();tick=()->{throw new IllegalStateException("private arbitrary text");};
        assertThrows(IllegalStateException.class,()->session.tick(observation(2,0,0)));
        assertEquals("GAME_EXECUTOR_FAILED",str(results.getFirst(),"reason"));assertFalse(results.getFirst().toString().contains("private"));
    }
    @Test void materialShortageStopsTheOriginalRootAndPreservesItsReason() {
        start(); tick=()->{throw new Rejected("GAME_RESOURCE_MATERIAL_UNAVAILABLE");};
        assertThrows(Rejected.class,()->session.tick(observation(2,0,0)));
        assertEquals("GAME_RESOURCE_MATERIAL_UNAVAILABLE",str(results.getFirst(),"reason"));
        assertEquals("failed",str(results.getFirst(),"state"));assertEquals(1,cancels);assertFalse(session.active());
    }
    @Test void aMaterialCycleStopsTheOriginalSessionAndKeepsItsReason() {
        start();tick=()->{throw new Rejected("GAME_RESOURCE_MATERIAL_CYCLE");};
        assertThrows(Rejected.class,()->session.tick(observation(2,0,0)));
        assertEquals("GAME_RESOURCE_MATERIAL_CYCLE",str(results.getFirst(),"reason"));
        assertEquals("unknown",str(results.getFirst(),"effect_status"));assertEquals(1,cancels);assertFalse(session.active());
    }
    @Test void unknownRejectionTextStaysPrivateInTheTaskResult() {
        start();tick=()->{throw new Rejected("private material path");};
        assertThrows(Rejected.class,()->session.tick(observation(2,0,0)));
        assertEquals("GAME_EXECUTOR_FAILED",str(results.getFirst(),"reason"));assertFalse(results.getFirst().toString().contains("private"));
    }
    @Test void aMaterialFailureAfterPhysicalTakeoverKeepsTheCancellationReason() {
        start();tick=()->{control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY,"PHYSICAL_INPUT");throw new Rejected("GAME_MATERIAL_ALLOCATION_LIMIT");};
        assertThrows(Rejected.class,()->session.tick(observation(2,0,0)));
        assertEquals("cancelled",str(results.getFirst(),"state"));assertEquals("PHYSICAL_INPUT",str(results.getFirst(),"reason"));assertEquals(1,cancels);
    }
    @Test void classifiedCraftFailureRetainsConfirmedBatchesWithoutCallingThemComplete() {
        craft();craftReceipt=receipt("task-1",control.epoch(),1,false);tick=()->{throw new Rejected("GAME_CRAFT_SERVER_DIVERGED");};
        assertThrows(Rejected.class,()->session.tick(observation(2,0,7)));
        var result=results.getFirst();assertEquals("GAME_CRAFT_SERVER_DIVERGED",str(result,"reason"));
        assertEquals("partial",str(result,"effect_status"));assertEquals("craft_result",str(result.getAsJsonArray("evidence").get(0).getAsJsonObject(),"kind"));
        assertEquals(1,cancels);assertFalse(session.active());
    }
    @Test void materialCleanupFailureStillBlocksAReplacementUntilCleanupSucceeds() {
        start();tick=()->{throw new Rejected("GAME_RESOURCE_MATERIAL_NO_PROGRESS");};stop=()->{throw new IllegalStateException("cleanup");};
        assertThrows(Rejected.class,()->session.tick(observation(2,0,0)));assertTrue(session.active());assertTrue(results.isEmpty());
        assertThrows(Rejected.class,this::start);stop=()->{};session.cancel("RETRY_STOP");assertFalse(session.active());
    }
    @Test void aClassifiedStartupFailureCleansUpAndLeavesTheBridgeToPublishItsTerminal() {
        onStart=()->{throw new LocalTaskFailure(LocalTaskFailure.Reason.MATERIAL_RESERVATION_LIMIT);};
        assertThrows(LocalTaskFailure.class,this::start);assertFalse(session.active());assertEquals(1,cancels);assertTrue(results.isEmpty());
    }
    @Test void physicalRevocationDuringAFailingTickKeepsItsOriginalCancellationReason() {
        start();tick=()->{control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY,"PHYSICAL_INPUT");
            throw new LocalTaskFailure(LocalTaskFailure.Reason.DEFENSE_TIMEOUT);};
        assertThrows(LocalTaskFailure.class,()->session.tick(observation(2,0,0)));
        assertEquals("cancelled",str(results.getFirst(),"state"));assertEquals("PHYSICAL_INPUT",str(results.getFirst(),"reason"));assertEquals(1,cancels);
    }
    @Test void failedCleanupRetainsTheDefenseTaskUntilAnExplicitRetrySucceeds() {
        start();tick=()->{throw new LocalTaskFailure(LocalTaskFailure.Reason.DEFENSE_ESCAPE_TIMEOUT);};
        stop=()->{throw new IllegalStateException("cleanup");};
        assertThrows(LocalTaskFailure.class,()->session.tick(observation(2,0,0)));assertTrue(session.active());assertTrue(results.isEmpty());
        stop=()->{};session.cancel("RETRY_STOP");assertFalse(session.active());assertEquals("RETRY_STOP",str(results.getFirst(),"reason"));
    }
    @Test void cleanupFailureRetainsTheTaskAndBlocksReplacementUntilRetry() {
        start(); stop = () -> { throw new IllegalStateException("cleanup"); };
        assertThrows(IllegalStateException.class, () -> session.cancel("cancel")); assertTrue(session.active()); assertTrue(results.isEmpty());
        assertThrows(Rejected.class, this::start); stop = () -> {}; session.cancel("retry"); assertFalse(session.active());
    }
    @Test void startFailureCleansUpWithoutInventingATerminalCallback() {
        onStart = () -> { throw new IllegalStateException("start"); }; assertThrows(IllegalStateException.class, this::start);
        assertEquals(1, cancels); assertTrue(results.isEmpty()); assertFalse(session.active());
    }
    @Test void consumerStartingTheNextTaskThenThrowingCannotCancelTheReplacement() {
        session.start(task, before, control, result -> { results.add(result); task.addProperty("task_id", "task-2"); start(); throw new IllegalStateException("consumer"); });
        finished(); assertThrows(IllegalStateException.class, () -> session.tick(observation(3, 10, 0)));
        assertTrue(session.active()); assertEquals(2, starts); assertEquals(1, cancels);
    }
    @Test void callerMutationCannotChangeTheAcceptedTarget() {
        start(); task.getAsJsonObject("goal").getAsJsonObject("target").addProperty("x", 100); before.addProperty("world_session_id", "changed");
        finished(); session.tick(observation(3, 10, 0)); assertEquals("succeeded", str(results.getFirst(), "state"));
    }
    @Test void craftingCannotBorrowInventoryEvidenceToClaimACraftResult() {
        task.add("goal", obj("skill", "craft", "item_id", "minecraft:oak_log", "count", 4));
        start(); finished(); session.tick(observation(3, 0, 64));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
        assertEquals("inventory", str(results.getFirst().getAsJsonArray("evidence").get(0).getAsJsonObject(), "kind"));
    }
    private void craft() {
        task.add("goal", obj("skill", "craft", "item_id", "minecraft:oak_log", "count", 5)); before = observation(1, 0, 3); start();
    }
    private CraftReceipt receipt(String taskId, long epoch, int batches, boolean clean) {
        return new CraftReceipt(taskId, "session-1", epoch, "minecraft:fixture_recipe", "minecraft:oak_log", 3, 5, 4, 2, batches, 7, clean);
    }
    @Test void craftingRequiresBoundServerBatchesCleanEndAndANewerInventoryObservation() {
        craft(); craftReceipt = receipt("task-1", control.epoch(), 2, true); finished(); assertTrue(results.isEmpty());
        session.tick(observation(3, 0, 11)); assertEquals("succeeded", str(results.getFirst(), "state"));
        assertEquals("craft_result", str(results.getFirst().getAsJsonArray("evidence").get(0).getAsJsonObject(), "kind"));
    }
    @Test void roundedCraftBatchesCannotUseOnlyTheRequestedLowerInventoryIncrease() {
        craft(); craftReceipt = receipt("task-1", control.epoch(), 2, true); finished(); session.tick(observation(3, 0, 8));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("partial", str(results.getFirst(), "effect_status"));
    }
    @Test void anotherTaskCannotDonateItsCraftReceipt() {
        craft(); craftReceipt = receipt("old-task", control.epoch(), 2, true); finished(); session.tick(observation(3, 0, 11));
        assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void anotherEpochCannotDonateItsCraftReceipt() {
        craft(); craftReceipt = receipt("task-1", control.epoch() - 1, 2, true); finished(); session.tick(observation(3, 0, 11));
        assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void aServerConfirmedOutputWithoutCleanCursorAndGridCannotSucceed() {
        craft(); craftReceipt = receipt("task-1", control.epoch(), 2, false); finished(); session.tick(observation(3, 0, 11));
        assertEquals("partial", str(results.getFirst(), "effect_status")); assertEquals("failed", str(results.getFirst(), "state"));
    }
    @Test void cancellationRetainsOnlyTheOriginalTasksConfirmedCraftEffects() {
        craft(); craftReceipt = receipt("task-1", control.epoch(), 1, false); session.cancel("OPERATOR_CANCELLED");
        assertEquals("cancelled", str(results.getFirst(), "state")); assertEquals("partial", str(results.getFirst(), "effect_status"));
        assertTrue(str(results.getFirst().getAsJsonArray("evidence").get(0).getAsJsonObject(), "summary").contains("4 produced units"));
    }
    @Test void executorFailurePreservesAlreadyConfirmedBatches() {
        craft(); craftReceipt = receipt("task-1", control.epoch(), 1, false); tick = () -> { throw new IllegalStateException("fixture failure"); };
        assertThrows(IllegalStateException.class, () -> session.tick(observation(2, 0, 7)));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("partial", str(results.getFirst(), "effect_status"));
    }
    @Test void receiptIsCapturedBeforeLaterObservationsAndCannotBeReplacedByAnotherTask() {
        craft(); craftReceipt = receipt("task-1", control.epoch(), 2, true); finished(); craftReceipt = receipt("other", control.epoch(), 0, false);
        session.tick(observation(3, 0, 11)); assertEquals("succeeded", str(results.getFirst(), "state"));
    }
    @Test void initialContextMismatchIsRejectedBeforeAnyDriverEffect() {
        before.addProperty("bridge_boot_id", "another-boot"); assertThrows(Rejected.class, this::start); assertEquals(0, starts);
    }
    @Test void absentInitialObservationFailsBeforeTheDriverInsteadOfDereferencingNull() {
        before = null; assertThrows(Rejected.class, this::start); assertEquals(0, starts); assertFalse(session.active());
    }
    private void returnBase() {
        task.add("goal", obj("skill", "return_base", "base_id", "base-1")); task.add("base_target", BaseTargetTest.snapshot());
    }
    @Test void returnBaseNeedsALaterArrivalSampleAndRetainsItsRegistryReference() {
        returnBase(); start(); assertEquals(10, receivedBase.x()); assertNull(receivedTarget);
        signals.getLast().run(); session.tick(observation(2, 10, 0)); assertTrue(results.isEmpty());
        session.tick(observation(3, 10, 0)); assertEquals("succeeded", str(results.getFirst(), "state"));
        assertTrue(str(results.getFirst().getAsJsonArray("evidence").get(0).getAsJsonObject(), "summary").contains("world revision 4"));
    }
    @Test void returnBaseDoesNotTurnAnEndedDriverIntoVerifiedArrival() {
        returnBase(); start(); finished(); session.tick(observation(3, 0, 0));
        assertEquals("failed", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void baseMutationAfterAcceptanceCannotChangeTheArrivalPosition() {
        returnBase(); start(); task.getAsJsonObject("base_target").getAsJsonObject("position").addProperty("x", 100);
        receivedBase.json().addProperty("radius", 128); finished(); session.tick(observation(3, 10, 0));
        assertEquals("succeeded", str(results.getFirst(), "state"));
    }
    @Test void anUnboundOrWrongWorldBaseCannotStartTheDriver() {
        returnBase(); var target = task.remove("base_target"); assertThrows(Rejected.class, this::start); assertEquals(0, starts);
        task.add("base_target", target); task.getAsJsonObject("base_target").addProperty("world_id", "world-other");
        assertThrows(Rejected.class, this::start); assertEquals(0, starts); assertFalse(session.active());
    }
    @Test void returnBaseCompletionAfterRevocationCannotReportArrival() {
        returnBase(); start(); finished(); control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY); session.tick(observation(3, 10, 0));
        assertEquals("cancelled", str(results.getFirst(), "state")); assertEquals("unknown", str(results.getFirst(), "effect_status"));
    }
    @Test void returnBaseInAnotherDimensionCannotClaimSuccessAtMatchingCoordinates() {
        returnBase(); start(); finished(); var changed = observation(3, 10, 0);
        changed.getAsJsonObject("player").getAsJsonObject("position").addProperty("dimension", "minecraft:the_nether");
        session.tick(changed); assertEquals("failed", str(results.getFirst(), "state"));
    }
    @Test void staleOrDuplicateObservationCannotRepeatAnExecutingDriverTick() {
        start(); session.tick(observation(1, 0, 0)); assertEquals(0, ticks);
        session.tick(observation(2, 0, 0)); session.tick(observation(2, 0, 0)); session.tick(observation(1, 0, 0));
        assertEquals(1, ticks); assertTrue(results.isEmpty()); assertTrue(session.active());
    }
}
