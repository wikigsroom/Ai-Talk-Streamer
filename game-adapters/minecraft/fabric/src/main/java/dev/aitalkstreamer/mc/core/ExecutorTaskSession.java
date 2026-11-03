package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.util.List;
import java.util.Objects;
import java.util.function.Consumer;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Connects the real driver to original-permit cancellation and a later game observation. */
public final class ExecutorTaskSession {
    public interface Runtime {
        void start(JsonObject task, ControlArbiter control, ControlArbiter.Permit permit, InventoryTarget target, BaseTarget base, Runnable finished);
        void tick();
        void cancel();
        default boolean allowsGui() { return false; }
        default CraftReceipt craftReceipt() { return null; }
        default ItemUseReceipt itemUseReceipt() { return null; }
    }
    private final Runtime runtime;
    private final Thread owner = Thread.currentThread();
    private Run active;
    private boolean closing;
    private static final class Run {
        final JsonObject task, before;
        final ControlArbiter control;
        final ControlArbiter.Permit permit;
        final Consumer<JsonObject> completed;
        final InventoryTarget target;
        final BaseTarget base;
        CraftReceipt craftReceipt;
        ItemUseReceipt itemUseReceipt;
        boolean signalled;
        long finishedAfterSeq = -1;
        long lastObservedSeq;
        Run(JsonObject task, JsonObject before, ControlArbiter control, Consumer<JsonObject> completed) {
            this.task = task.deepCopy(); this.before = before.deepCopy(); this.control = control;
            this.permit = control.permit(); this.completed = Objects.requireNonNull(completed);
            this.lastObservedSeq = num(before, "seq");
            var goal = this.task.getAsJsonObject("goal");
            this.target = List.of("gather", "craft").contains(str(goal, "skill"))
                    ? new InventoryTarget(str(goal, "item_id"), InventoryTarget.count(this.before, str(goal, "item_id")),
                        Math.toIntExact(num(goal, "count")), 1) : null;
            this.base = BaseTarget.forTask(this.task, this.before);
        }
    }
    public ExecutorTaskSession(Runtime runtime) { this.runtime = Objects.requireNonNull(runtime); }
    private void thread() { require(Thread.currentThread() == owner, "GAME_WRONG_THREAD"); }
    public boolean active() { thread(); return active != null; }
    public void start(JsonObject task, JsonObject observation, ControlArbiter control, Consumer<JsonObject> completed) {
        thread(); require(active == null && !closing, "GAME_TASK_BUSY");
        require(observation != null, "GAME_STATE_UNAVAILABLE");
        Run run = new Run(task, observation, control, completed);
        require(context(run, observation) && current(run) && str(observation, "screen").equals("gameplay"), "GAME_EXECUTOR_CONTEXT");
        String skill = str(task.getAsJsonObject("goal"), "skill");
        require(List.of("navigate", "gather", "craft", "use_item", "return_base").contains(skill), "GAME_CAPABILITY_UNAVAILABLE");
        active = run;
        try {
            runtime.start(run.task.deepCopy(), control, run.permit, run.target, run.base, () -> {
                if (Thread.currentThread() == owner && active == run && current(run) && !closing) run.signalled = true;
            });
        } catch (RuntimeException | Error error) {
            try { cleanup(run); active = null; }
            catch (RuntimeException | Error cleanup) { if (cleanup != error) error.addSuppressed(cleanup); }
            throw error;
        }
    }
    private static boolean current(Run run) {
        if (!run.control.allowed()) return false;
        try { return run.control.permit().equals(run.permit); }
        catch (Rejected error) { return false; }
    }
    private static boolean context(Run run, JsonObject observation) {
        if (observation == null) return false;
        for (String key : List.of("game_instance_id", "bridge_boot_id", "world_id", "world_session_id", "control_epoch"))
            if (!Objects.equals(observation.get(key), run.task.get(key))) return false;
        return str(run.task, "world_session_id").equals(run.permit.world()) && num(run.task, "control_epoch") == run.permit.epoch();
    }
    public void tick(JsonObject observation) {
        thread(); Run run = active; if (run == null || closing) return;
        if (!current(run) || !context(run, observation)
                || (!str(observation, "screen").equals("gameplay")
                && (!List.of("inventory", "container").contains(str(observation, "screen")) || !runtime.allowsGui()))) {
            String reason = run.control.revocationReason(run.permit);
            if (reason == null && observation != null) {
                if (!Objects.equals(observation.get("world_id"), run.task.get("world_id"))
                        || !Objects.equals(observation.get("world_session_id"), run.task.get("world_session_id"))) reason = "GAME_WORLD_CHANGED";
                else if (!str(observation, "screen").equals("gameplay")) reason = "GUI_BLOCKED";
            }
            cancel(reason == null ? "GAME_CONTROL_OR_CONTEXT_CHANGED" : reason); return;
        }
        long observedSeq = num(observation, "seq");
        if (observedSeq <= run.lastObservedSeq) return;
        run.lastObservedSeq = observedSeq;
        JsonObject ready = null;
        try {
            if (run.finishedAfterSeq >= 0) {
                if (num(observation, "seq") <= run.finishedAfterSeq) return;
                ready = verify(run, observation);
                cleanup(run);
            } else {
                runtime.tick();
                if (active == run && run.signalled) {
                // The driver has completed its own cleanup. Do not reuse the sample
                // taken before that tick as evidence of a subsequent game effect.
                    run.finishedAfterSeq = num(observation, "seq");
                    if (str(run.task.getAsJsonObject("goal"), "skill").equals("craft")) run.craftReceipt = runtime.craftReceipt();
                    if (str(run.task.getAsJsonObject("goal"), "skill").equals("use_item")) run.itemUseReceipt = runtime.itemUseReceipt();
                }
            }
        } catch (RuntimeException | Error error) {
            try {
                CraftReceipt receipt = str(run.task.getAsJsonObject("goal"), "skill").equals("craft") ? runtime.craftReceipt() : null;
                ItemUseReceipt item = str(run.task.getAsJsonObject("goal"), "skill").equals("use_item") ? runtime.itemUseReceipt() : null;
                String revoked = run.control.revocationReason(run.permit);
                String reason = revoked != null ? revoked : LocalTaskFailure.executionReason(error);
                cleanup(run);
                boolean replan = revoked == null && current(run) && context(run, observation)
                        && str(observation,"screen").equals("gameplay") && recoverableRouteFailure(run, error);
                deliver(run, stoppedResult(run, revoked == null ? "failed" : "cancelled", reason, receipt, item));
                // A known unavailable resource/route is a failed task, not a
                // sampling exception. Cleanup and terminal delivery must both
                // succeed before returning to the Agent's fresh-observation loop.
                // Unknown errors, timeouts, revocation and cleanup failures still
                // propagate to the native stop fence.
                if (replan) return;
            } catch (RuntimeException | Error cleanup) { if (cleanup != error) error.addSuppressed(cleanup); }
            throw error;
        }
        // A consumer may start the next task. Its exception must never enter this
        // old task's cleanup block and cancel that replacement.
        if (ready != null) deliver(run, ready);
    }
    private static boolean recoverableRouteFailure(Run run, Throwable error) {
        if (!(error instanceof LocalTaskFailure failure)) return false;
        String skill=str(run.task.getAsJsonObject("goal"),"skill");
        if (failure.reason==LocalTaskFailure.Reason.DEFENSE_HAZARD_INTERRUPTED)
            return List.of("gather","navigate","return_base","craft","use_item").contains(skill);
        if (List.of(LocalTaskFailure.Reason.ITEM_PLACEMENT_SITE_CHANGED,LocalTaskFailure.Reason.ITEM_PLANT_SITE_CHANGED,
                LocalTaskFailure.Reason.ITEM_BLOCK_TARGET_CHANGED).contains(failure.reason)) {
            var goal=run.task.getAsJsonObject("goal");
            return skill.equals("use_item") && str(goal,"purpose").equals("activate") && goal.has("target");
        }
        return skill.equals("gather") && (failure.reason==LocalTaskFailure.Reason.GATHER_RESOURCE_UNAVAILABLE
                || failure.reason==LocalTaskFailure.Reason.GATHER_TOOL_UNAVAILABLE
                || failure.reason==LocalTaskFailure.Reason.GATHER_NO_PROGRESS)
                || List.of("gather","navigate","return_base").contains(skill)
                && (failure.reason==LocalTaskFailure.Reason.NAVIGATION_NO_ROUTE
                || failure.reason==LocalTaskFailure.Reason.NAVIGATION_NO_PROGRESS
                || failure.reason==LocalTaskFailure.Reason.NAVIGATION_MOVEMENT_BLOCKED
                || failure.reason==LocalTaskFailure.Reason.DEFENSE_RETREAT_COMPLETE
                || failure.reason==LocalTaskFailure.Reason.DEFENSE_TIMEOUT
                || failure.reason==LocalTaskFailure.Reason.DEFENSE_NO_PROGRESS
                || failure.reason==LocalTaskFailure.Reason.DEFENSE_ESCAPE_TIMEOUT
                || failure.reason==LocalTaskFailure.Reason.DEFENSE_RANGE_LIMIT
                || failure.reason==LocalTaskFailure.Reason.SUPPLY_NO_PROGRESS
                || failure.reason==LocalTaskFailure.Reason.SUPPLY_RANGE_LIMIT);
    }
    public void cancel(String reason) {
        thread(); Run run = active; if (run == null || closing) return;
        CraftReceipt receipt = str(run.task.getAsJsonObject("goal"), "skill").equals("craft") ? runtime.craftReceipt() : null;
        ItemUseReceipt item = str(run.task.getAsJsonObject("goal"), "skill").equals("use_item") ? runtime.itemUseReceipt() : null;
        cleanup(run);
        deliver(run, stoppedResult(run, reason.equals("TASK_TIMEOUT") ? "failed" : "cancelled", reason, receipt, item));
    }
    private static boolean boundItem(Run run, ItemUseReceipt item) {
        return item != null && item.matches(run.task)
                && item.baseline() == InventoryTarget.count(run.before, str(run.task.getAsJsonObject("goal"), "item_id"));
    }
    private static JsonObject stoppedResult(Run run, String state, String reason, CraftReceipt receipt, ItemUseReceipt item) {
        JsonArray evidence = new JsonArray(); boolean partial = receipt != null && receipt.matches(run.task, run.target) && receipt.produced() > 0;
        if (partial) evidence.add(obj("world_session_id", run.task.get("world_session_id"), "seq", run.lastObservedSeq,
                "kind", "craft_result", "summary", craftSummary(receipt) + " Task stopped; cancellation does not undo these effects."));
        if (boundItem(run, item) && item.hasEffect()) {
            partial = true; evidence.add(obj("world_session_id", run.task.get("world_session_id"), "seq", run.lastObservedSeq,
                    "kind", "item_effect", "summary", item.summary() + " Task stopped; cancellation does not undo these effects."));
        }
        return result(state, reason, partial ? "partial" : "unknown", evidence);
    }
    private void cleanup(Run run) {
        if (active != run) return;
        closing = true;
        try { runtime.cancel(); }
        finally { closing = false; }
    }
    private void deliver(Run run, JsonObject result) {
        if (active != run) return;
        active = null; run.completed.accept(result.deepCopy());
    }
    private static JsonObject result(String state, String reason, String effect, JsonArray evidence) {
        return obj("state", state, "reason", reason, "effect_status", effect, "evidence", evidence);
    }
    private static JsonObject verify(Run run, JsonObject observed) {
        JsonObject goal = run.task.getAsJsonObject("goal"); String skill = str(goal, "skill");
        boolean verified = false, partial = false;
        String kind, summary;
        if (skill.equals("navigate")) {
            JsonObject position = observed.get("player") instanceof JsonObject player && player.get("position") instanceof JsonObject value ? value : null;
            JsonObject target = goal.getAsJsonObject("target");
            if (position != null && str(position, "dimension").equals(str(target, "dimension"))) {
                double distance = 0;
                for (String axis : List.of("x", "y", "z")) distance += Math.pow(position.get(axis).getAsDouble() - target.get(axis).getAsDouble(), 2);
                verified = distance <= Math.pow(goal.get("radius").getAsDouble(), 2);
            }
            kind = "position"; summary = verified ? "Observed player position is inside the requested dimension and radius."
                    : "Executor ended; the requested position has not been observed.";
        } else if (skill.equals("return_base")) {
            JsonObject position = observed.get("player") instanceof JsonObject player && player.get("position") instanceof JsonObject value ? value : null;
            verified = run.base.reached(position);
            kind = "position"; summary = "Base " + run.base.baseId() + " revision " + run.base.baseRevision()
                    + ", world revision " + run.base.worldRevision() + ": "
                    + (verified ? "observed player position is inside the registered dimension and radius " + run.base.radius() + "."
                    : "executor ended; arrival inside the registered dimension and radius has not been observed.");
        } else if (skill.equals("craft")) {
            CraftReceipt receipt = run.craftReceipt;
            boolean bound = receipt != null && receipt.matches(run.task, run.target);
            long after = InventoryTarget.count(observed, run.target.itemId());
            verified = bound && receipt.complete() && after - run.target.baseline() >= receipt.produced();
            partial = bound && receipt.produced() > 0 && !verified;
            kind = bound ? "craft_result" : "inventory"; summary = bound ? craftSummary(receipt) + " Later observed inventory total: " + after
                    + "; starting total: " + run.target.baseline() + "." : "No server-synchronized result bound to this task. Inventory alone does not prove crafting.";
        } else if (skill.equals("use_item")) {
            ItemUseReceipt item = run.itemUseReceipt; boolean bound = boundItem(run, item);
            long after = InventoryTarget.count(observed, str(goal, "item_id"));
            verified = bound && item.complete() && (item.purpose().equals("equip") || after <= item.baseline() - item.consumed());
            partial = bound && item.hasEffect() && !verified;
            kind = "item_effect"; summary = bound ? item.summary() + " Later inventory total: " + after + "."
                    : "No item-specific server result bound to this task. Client prediction or an inventory change alone is insufficient.";
        } else {
            long before = run.target.baseline(), after = InventoryTarget.count(observed, run.target.itemId());
            verified = after - before >= run.target.requestedIncrement();
            partial = after > before && !verified;
            kind = "inventory"; summary = "Observed inventory total changed from " + before + " to " + after
                    + "; observed net increase is " + (after - before) + "; requested increase is "
                    + run.target.requestedIncrement() + ". Collection source is not established by inventory alone.";
        }
        JsonArray evidence = new JsonArray();
        evidence.add(obj("world_session_id", run.task.get("world_session_id"), "seq", observed.get("seq"), "kind", kind, "summary", summary));
        return result(verified ? "succeeded" : "failed", verified ? null : "GAME_EFFECT_NOT_VERIFIED", verified ? "verified" : partial ? "partial" : "unknown", evidence);
    }
    private static String craftSummary(CraftReceipt receipt) {
        return "Recipe " + receipt.recipeId() + ": " + receipt.confirmedBatches() + "/" + receipt.batches()
                + " batches, " + receipt.produced() + " produced units; server full-state revision " + receipt.lastServerRevision()
                + "; cursor/material/result checks after controlled clicks. Clean end: " + receipt.cleanEnd() + ".";
    }
}
