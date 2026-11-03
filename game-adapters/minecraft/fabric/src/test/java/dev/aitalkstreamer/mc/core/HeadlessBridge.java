package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Files;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Explicit protocol fixture. This class is test-only and never packaged in the Fabric mod. */
public final class HeadlessBridge {
    private static final long STARTED = System.nanoTime();
    private static void bootPhase(String phase) {
        System.out.println("FIXTURE_BOOT " + phase + " " + ((System.nanoTime() - STARTED) / 1_000_000) + "ms");
        System.out.flush();
    }
    public static void main(String[] args) throws Exception {
        bootPhase("main");
        ScheduledExecutorService game = Executors.newSingleThreadScheduledExecutor(r -> new Thread(r, "fixture-game-thread"));
        Path effectFile = Path.of(args[1]).resolve("fixture-effects.txt");
        AtomicInteger effects = new AtomicInteger(Files.exists(effectFile) ? Integer.parseInt(Files.readString(effectFile)) : 0);
        AtomicInteger nextExecutionDelay = new AtomicInteger(), worldNumber = new AtomicInteger();
        AtomicBoolean delayFinalStart = new AtomicBoolean();
        AtomicBoolean inputBound = new AtomicBoolean(args.length < 3 || !args[2].equals("no-executor"));
        AtomicBoolean holdNextExecution = new AtomicBoolean(), holdFinalStart = new AtomicBoolean();
        AtomicReference<Runnable> heldExecution = new AtomicReference<>();
        AtomicReference<CountDownLatch> stalled = new AtomicReference<>();
        AtomicReference<Object> worldObject = new AtomicReference<>(new Object());
        AtomicReference<String> fixtureScreen = new AtomicReference<>("gameplay");
        AtomicReference<Object> fixtureGuiScreen = new AtomicReference<>();
        Object fixturePlayer = new Object(), fixtureInventory = new Object();
        AtomicLong guiClock = new AtomicLong(1000);
        AtomicInteger craftedStock = new AtomicInteger(3);
        AtomicBoolean omitCraftReceipt = new AtomicBoolean(), holdCraftAfterBatch = new AtomicBoolean();
        AtomicReference<String> craftFailure = new AtomicReference<>("");
        AtomicBoolean omitItemReceipt = new AtomicBoolean(), holdItemAfterEffect = new AtomicBoolean();
        AtomicInteger placedStock = new AtomicInteger(5);
        AtomicReference<JsonObject> fixturePosition = new AtomicReference<>(obj("dimension", "minecraft:overworld", "x", 0, "y", 64, "z", 0));
        class Port implements GamePort {
            BridgeCore core;
            ExecutorTaskSession baseSession;
            Consumer<JsonObject> completion;
            Runnable pending;
            TaskGuiLease gui;
            JsonObject guiTask;
            @Override public boolean allowsGui(JsonObject task) {
                return gui != null && guiTask != null && str(task, "task_id").equals(str(guiTask, "task_id"))
                        && num(task, "control_epoch") == num(guiTask, "control_epoch")
                        && fixtureScreen.get().equals("inventory")
                        && gui.permits("inventory", worldObject.get(), fixturePlayer, fixtureGuiScreen.get(), fixtureInventory, 0);
            }
            @Override public void execute(Runnable action) {
                if (holdNextExecution.getAndSet(false)) {
                    if (!heldExecution.compareAndSet(null, action)) throw new IllegalStateException("FIXTURE_ALREADY_HOLDING");
                    System.out.println("FIXTURE_HELD_ACTION_QUEUED"); System.out.flush(); return;
                }
                int delay = nextExecutionDelay.getAndSet(0);
                if (delay > 0) game.schedule(() -> {
                    System.out.println("FIXTURE_DELAYED_ACTION_RELEASED"); System.out.flush(); action.run();
                }, delay, TimeUnit.MILLISECONDS); else game.execute(action);
            }
            @Override public void releaseInputs() { }
            @Override public JsonObject capabilities(String instance) {
                return obj("protocol_version", "1.0", "game_instance_id", instance, "adapter", "minecraft.fabric", "game_version", "1.21.1",
                        "mod_version", "TEST_FIXTURE_ONLY", "execution_profile", "native_core", "skills", List.of("use_item", "return_base", "craft", "cancel"),
                        "item_uses", List.of("eat", "equip", "activate"), "features", obj("recipes", true, "screenshots", true, "raw_frames", true, "local_takeover", inputBound.get(), "cancel_all", inputBound.get(), "task_ledger", true), "rule_fingerprint", null);
            }
            @Override public JsonObject check(JsonObject goal) {
                if (delayFinalStart.getAndSet(false)) nextExecutionDelay.set(1800);
                if (holdFinalStart.getAndSet(false)) holdNextExecution.set(true);
                return obj("allowed", true, "reason", null, "source", "TEST_FIXTURE_ONLY");
            }
            @Override public JsonObject check(JsonObject goal, BaseTarget base) {
                if (str(goal, "skill").equals("return_base")) require(base != null, "GAME_BASE_TARGET_REQUIRED");
                return check(goal);
            }
            @Override public FrameEncoder.Capture captureFrame() {
                int[] pixels = new int[32 * 18]; java.util.Arrays.fill(pixels, 0x4d8059);
                return new FrameEncoder.Capture(32, 18, pixels); // Explicit synthetic fixture, never Minecraft evidence.
            }
            @Override public JsonObject recipe(JsonObject params) {
                require(Thread.currentThread().getName().equals("fixture-game-thread"),"GAME_WRONG_THREAD");
                var recipe=new RecipeCatalog.Source("test:planks","minecraft:crafting","minecraft:oak_planks",4,"shapeless",0,0,
                        ()->List.of(List.of("minecraft:oak_log")));
                var result=RecipeCatalog.lookup(str(params,"item_id"),Math.toIntExact(num(params,"count")),List.of(recipe));
                result.addProperty("source","TEST_FIXTURE_ONLY");return result;
            }
            @Override public void start(JsonObject task, ControlArbiter control, Consumer<JsonObject> completed) {
                guiTask = task.deepCopy();
                if (str(task.getAsJsonObject("goal"), "skill").equals("use_item")) {
                    boolean omit = omitItemReceipt.getAndSet(false), hold = holdItemAfterEffect.getAndSet(false);
                    baseSession = new ExecutorTaskSession(new ExecutorTaskSession.Runtime() {
                        ControlArbiter.Permit permit; Runnable finished; ItemUseReceipt receipt; int baseline; boolean ran;
                        public void start(JsonObject accepted, ControlArbiter actual, ControlArbiter.Permit original, InventoryTarget inventory, BaseTarget base, Runnable done) {
                            permit = original; finished = done; baseline = InventoryTarget.count(core.latestObservation(), str(task.getAsJsonObject("goal"), "item_id"));
                            pending = () -> {
                                if (ran) return; ran = true;
                                String purpose = str(task.getAsJsonObject("goal"), "purpose");
                                control.actuate(permit, () -> { effects.incrementAndGet(); if (purpose.equals("activate")) placedStock.decrementAndGet(); });
                                try { Files.writeString(effectFile, Integer.toString(effects.get())); } catch (IOException error) { throw new UncheckedIOException(error); }
                                if (!omit) receipt = new ItemUseReceipt(str(task, "task_id"), str(task, "world_session_id"), permit.epoch(),
                                        str(task.getAsJsonObject("goal"), "item_id"), purpose, baseline, purpose.equals("equip") ? 0 : 1,
                                        "TEST_FIXTURE_ONLY:synthetic_item_effect", 8, true, true, !hold);
                                pending = null; System.out.println("FIXTURE_SYNTHETIC_ITEM_EFFECT"); System.out.flush();
                                if (!hold) { control.release(permit.epoch(), () -> {}); finished.run(); }
                            };
                        }
                        public void tick() { }
                        public void cancel() { pending = null; control.release(permit.epoch(), () -> {}); }
                        public ItemUseReceipt itemUseReceipt() { return receipt; }
                        public boolean allowsGui() { return Port.this.allowsGui(task); }
                    });
                    baseSession.start(task, core.latestObservation(), control, completed);
                    System.out.println("FIXTURE_PORT_STARTED " + str(task, "task_id")); System.out.flush(); return;
                }
                if (str(task.getAsJsonObject("goal"), "skill").equals("craft")) {
                    boolean omit = omitCraftReceipt.getAndSet(false), hold = holdCraftAfterBatch.getAndSet(false);
                    String failure = craftFailure.getAndSet("");
                    baseSession = new ExecutorTaskSession(new ExecutorTaskSession.Runtime() {
                        InventoryTarget target; ControlArbiter.Permit permit; Runnable finished; CraftReceipt receipt; boolean ran;
                        public void start(JsonObject accepted, ControlArbiter actual, ControlArbiter.Permit original, InventoryTarget inventory, BaseTarget base, Runnable done) {
                            permit = original; target = new InventoryTarget(inventory.itemId(), inventory.baseline(), inventory.requestedIncrement(), 4); finished = done;
                            if (failure.equals("startup")) throw new LocalTaskFailure(LocalTaskFailure.Reason.MATERIAL_RESERVATION_LIMIT);
                        }
                        public void tick() {
                            if (ran) return; ran = true;
                            if (failure.equals("missing")) throw new Json.Rejected("GAME_RESOURCE_MATERIAL_UNAVAILABLE");
                            if (failure.equals("cycle")) throw new Json.Rejected("GAME_RESOURCE_MATERIAL_CYCLE");
                            if (failure.equals("smelting")) throw new Json.Rejected("GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE");
                            if (failure.equals("unknown")) throw new IllegalStateException("PRIVATE_FIXTURE_MESSAGE GAME_CRAFT_SERVER_TIMEOUT");
                            int batches = hold || failure.equals("partial") ? 1 : target.batches();
                            control.actuate(permit, () -> { craftedStock.addAndGet(batches * 4); effects.incrementAndGet(); });
                            try { Files.writeString(effectFile, Integer.toString(effects.get())); } catch (IOException error) { throw new UncheckedIOException(error); }
                            if (!omit) receipt = new CraftReceipt(str(task, "task_id"), str(task, "world_session_id"), permit.epoch(),
                                    "test:fixture_recipe", target.itemId(), target.baseline(), target.requestedIncrement(), 4, target.batches(), batches, 7, !hold && failure.isEmpty());
                            System.out.println("FIXTURE_SYNTHETIC_CRAFT_BATCHES " + batches); System.out.flush();
                            if (failure.equals("partial")) throw new Json.Rejected("GAME_CRAFT_SERVER_DIVERGED");
                            if (!hold) { control.release(permit.epoch(), () -> {}); finished.run(); }
                        }
                        public void cancel() { control.release(permit.epoch(), () -> {}); }
                        public CraftReceipt craftReceipt() { return receipt; }
                    });
                    baseSession.start(task, core.latestObservation(), control, completed); return;
                }
                if (str(task.getAsJsonObject("goal"), "skill").equals("return_base")) {
                    baseSession = new ExecutorTaskSession(new ExecutorTaskSession.Runtime() {
                        ControlArbiter.Permit permit; BaseTarget base; Runnable finished;
                        public void start(JsonObject accepted, ControlArbiter actual, ControlArbiter.Permit original, InventoryTarget inventory, BaseTarget target, Runnable done) {
                            permit = original; base = target; finished = done;
                        }
                        public void tick() {
                            // Synthetic movement only: exercises the real core/session, never Minecraft pathfinding.
                            control.actuate(permit, () -> { fixturePosition.set(base.json().getAsJsonObject("position")); effects.incrementAndGet(); });
                            try { Files.writeString(effectFile, Integer.toString(effects.get())); } catch (IOException error) { throw new UncheckedIOException(error); }
                            control.release(permit.epoch(), () -> {}); finished.run();
                        }
                        public void cancel() { control.release(permit.epoch(), () -> {}); }
                    });
                    baseSession.start(task, core.latestObservation(), control, completed); return;
                }
                var permit = control.permit(); require(permit.epoch() == num(task, "control_epoch"), "GAME_CONTROL_CONFLICT");
                control.actuate(permit, () -> {}); completion = completed;
                pending = () -> {
                    try { control.actuate(permit, effects::incrementAndGet); }
                    catch (Json.Rejected old) { cancel("LEASE_LOST"); return; }
                    try { Files.writeString(effectFile, Integer.toString(effects.get())); } catch (IOException error) { throw new UncheckedIOException(error); }
                    control.release(permit.epoch(), () -> {}); completion = null; pending = null;
                    completed.accept(obj("state", "succeeded", "reason", null, "effect_status", "verified", "evidence", List.of(obj(
                            "world_session_id", task.get("world_session_id"), "seq", 1, "kind", "item_effect", "summary", "TEST_FIXTURE_ONLY: effect counter changed"))));
                };
                System.out.println("FIXTURE_PORT_STARTED " + str(task, "task_id")); System.out.flush();
            }
            @Override public void cancel(String reason) {
                if (gui != null) gui.clear(); guiTask = null;
                if (baseSession != null) baseSession.cancel(reason);
                pending = null;
                if (completion != null) { var callback = completion; completion = null;
                    callback.accept(obj("state", "cancelled", "reason", reason, "effect_status", "unknown", "evidence", new JsonArray())); }
            }
        }
        Port port = new Port();
        bootPhase("journal-opening");
        LocalJournal journal = new LocalJournal(Path.of(args[1]));
        bootPhase("journal-opened");
        BridgeCore core = new BridgeCore(port, journal, URI.create(args[0]));
        port.core = core;
        bootPhase("core-created");
        core.start();
        bootPhase("core-started");
        var sampling = game.scheduleWithFixedDelay(() -> { core.observe(worldObject.get(), "TEST_FIXTURE_WORLD:" + worldNumber.get(), obj(
                "player", obj("health", 18, "max_health", 20, "food", 16 + effects.get(), "oxygen", 300,
                        "position", fixturePosition.get()),
                "inventory", List.of(obj("item_id", "minecraft:bread", "count", 10 - effects.get()), obj("item_id", "minecraft:oak_planks", "count", craftedStock.get()),
                        obj("item_id", "minecraft:iron_helmet", "count", 1), obj("item_id", "minecraft:cobblestone", "count", placedStock.get())), "screen", fixtureScreen.get(),
                "environment", obj("loaded_radius_chunks", null, "nearby_threats", 0), "unknown_fields", List.of("TEST_FIXTURE_ONLY")));
            if (port.baseSession != null) {
                try { port.baseSession.tick(core.latestObservation()); }
                catch (RuntimeException error) { System.out.println("FIXTURE_TASK_ERROR " + error.getClass().getSimpleName()); System.out.flush(); }
            }
        }, 0, 50, TimeUnit.MILLISECONDS);
        try (BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            System.out.println("FIXTURE_READY"); System.out.flush(); String line;
            while ((line = input.readLine()) != null) {
                if (line.equals("quit")) break;
                if (line.equals("takeover")) core.takeover(true, "FIXTURE_PHYSICAL_INPUT");
                if (line.equals("bind-executor") || line.equals("unbind-executor")) {
                    inputBound.set(line.equals("bind-executor")); core.capabilitiesChanged();
                    System.out.println("FIXTURE_CAPABILITIES_INPUT_BOUND " + inputBound.get()); System.out.flush();
                }
                if (line.equals("next-world")) game.execute(() -> { worldNumber.incrementAndGet(); worldObject.set(new Object()); });
                if (line.equals("move-fixture-player")) game.execute(() -> fixturePosition.set(obj("dimension", "minecraft:overworld", "x", 12, "y", 64, "z", 0)));
                if (line.equals("open-owned-inventory")) game.execute(() -> {
                    require(port.guiTask != null, "FIXTURE_NO_ACTIVE_TASK"); var permit = core.control.permit();
                    port.gui = new TaskGuiLease(guiClock::get, () -> {
                        try { return core.control.permit().equals(permit); } catch (Json.Rejected revoked) { return false; }
                    });
                    port.gui.expect("inventory", worldObject.get(), fixturePlayer, fixtureInventory, 0);
                    fixtureGuiScreen.set(new Object()); fixtureScreen.set("inventory");
                });
                if (line.equals("replace-unowned-inventory")) game.execute(() -> { fixtureGuiScreen.set(new Object()); fixtureScreen.set("inventory"); });
                if (line.equals("expire-owned-gui")) game.execute(() -> guiClock.addAndGet(TaskGuiLease.IDLE_MS));
                if (line.equals("close-fixture-gui")) game.execute(() -> { fixtureScreen.set("gameplay"); fixtureGuiScreen.set(null); if (port.gui != null) port.gui.clear(); });
                if (line.equals("omit-craft-receipt")) { omitCraftReceipt.set(true); System.out.println("FIXTURE_OMIT_CRAFT_RECEIPT"); System.out.flush(); }
                if (line.equals("hold-craft-after-batch")) { holdCraftAfterBatch.set(true); System.out.println("FIXTURE_HOLD_CRAFT_AFTER_BATCH"); System.out.flush(); }
                if (line.startsWith("craft-failure ")) {
                    String mode = line.substring("craft-failure ".length());
                    if (List.of("missing", "partial", "startup", "unknown", "cycle", "smelting").contains(mode)) {
                        craftFailure.set(mode);System.out.println("FIXTURE_CRAFT_FAILURE " + mode);System.out.flush();
                    }
                }
                if (line.equals("omit-item-receipt")) { omitItemReceipt.set(true); System.out.println("FIXTURE_OMIT_ITEM_RECEIPT"); System.out.flush(); }
                if (line.equals("hold-item-after-effect")) { holdItemAfterEffect.set(true); System.out.println("FIXTURE_HOLD_ITEM_AFTER_EFFECT"); System.out.flush(); }
                if (line.equals("delay-next-execution")) { nextExecutionDelay.set(1800);
                    System.out.println("FIXTURE_EXECUTION_DELAY_SET"); System.out.flush(); }
                if (line.equals("delay-final-start")) { delayFinalStart.set(true);
                    System.out.println("FIXTURE_FINAL_START_DELAY_SET"); System.out.flush(); }
                if (line.equals("hold-next-execution")) { holdNextExecution.set(true);
                    System.out.println("FIXTURE_EXECUTION_HOLD_SET"); System.out.flush(); }
                if (line.equals("hold-final-start")) { holdFinalStart.set(true);
                    System.out.println("FIXTURE_FINAL_START_HOLD_SET"); System.out.flush(); }
                if (line.equals("release-held-execution")) { Runnable held = heldExecution.getAndSet(null);
                    if (held != null) game.execute(() -> { System.out.println("FIXTURE_HELD_ACTION_RELEASED"); System.out.flush(); held.run(); }); }
                if (line.equals("stall-game-thread")) {
                    CountDownLatch resume = new CountDownLatch(1); stalled.set(resume);
                    game.execute(() -> {
                        System.out.println("FIXTURE_GAME_THREAD_STALLED"); System.out.flush();
                        try { resume.await(5, TimeUnit.SECONDS); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                        System.out.println("FIXTURE_GAME_THREAD_RESUMED"); System.out.flush();
                    });
                }
                if (line.equals("resume-game-thread")) { CountDownLatch resume = stalled.getAndSet(null); if (resume != null) resume.countDown(); }
                if (line.equals("complete")) game.execute(() -> { if (port.pending != null) port.pending.run(); });
                if (line.equals("stats")) game.execute(() -> { System.out.println(GSON.toJson(obj("effects", effects.get(), "mode", core.control.mode().name(),
                        "epoch", core.control.epoch(), "inputs_released", core.control.released(), "active_fixture_effect", port.pending != null,
                        "screen", fixtureScreen.get(),
                        "fault", core.fault(), "fault_detail", core.faultDetail(), "diagnostics", core.diagnostics()))); System.out.flush(); });
            }
        } finally {
            CountDownLatch resume = stalled.getAndSet(null); if (resume != null) resume.countDown();
            sampling.cancel(false); core.close(); game.shutdown(); game.awaitTermination(5, TimeUnit.SECONDS); game.shutdownNow();
        }
    }
}
