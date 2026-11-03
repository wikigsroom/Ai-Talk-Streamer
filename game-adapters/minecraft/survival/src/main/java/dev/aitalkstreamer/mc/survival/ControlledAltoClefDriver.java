package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.InventoryTarget;
import dev.aitalkstreamer.mc.core.BaseTarget;
import dev.aitalkstreamer.mc.core.CraftReceipt;
import net.minecraft.client.MinecraftClient;
import java.util.function.Consumer;
import java.util.List;

/** Typed root lifecycle used by SurvivalGameExecutor; full runtime acceptance remains gated. */
public final class ControlledAltoClefDriver {
    private ControlledTaskFactory.Prepared activePrepared;
    private CraftReceipt lastReceipt;
    private final ControlledTaskRunner<ControlledTaskFactory.Prepared> runner = new ControlledTaskRunner<>(new ControlledTaskRunner.Runtime<>() {
        @Override public void start(ControlledTaskFactory.Prepared task, Runnable finished) { activePrepared = task; mod().runUserTask(task.task(), finished); }
        @Override public void tick() {
            ControlledShield.beginTick();
            SurvivalOptions.checkpoint();
            ControlledStorage.checkpoint(); ConfirmedCraftTask.checkpoint(); ControlledDefenseTask.checkpoint(); ControlledEquipment.checkpoint(); ControlledCookingTask.checkpoint();
            ControlledEatingTask.checkpoint(); ControlledSupplyTask.checkpoint(); mod().onClientTick();
            ControlledShield.endTick();
        }
        @Override public void stop() {
            if (activePrepared != null && activePrepared.task() instanceof ConfirmedCraftTask craft && (lastReceipt == null || !lastReceipt.complete())) lastReceipt = craft.receipt(false);
            mod().stopTasks();
        }
        @Override public void beforeComplete() {
            ControlledShield.finishOwned();
            SurvivalActions.finishOwned();
            SurvivalGui.finishOwned();
            if (activePrepared != null && activePrepared.task() instanceof ConfirmedCraftTask craft) lastReceipt = craft.receipt(true);
        }
        @Override public List<Runnable> cleanup() {
            return List.of(() -> mod().getClientBaritone().getPathingBehavior().forceCancel(),
                    () -> mod().getClientBaritone().getInputOverrideHandler().clearAllKeys(),
                    () -> mod().getInputControls().clearControlledQueue(),
                    () -> SurvivalCallbacks.clearRootEvents((SurvivalCallbacks.RootResettable) (Object) mod().getClientBaritone().getPathingBehavior()));
        }
    });
    private static AltoClef mod() {
        AltoClef mod = AltoClef.getInstance();
        if (mod == null || mod.getTaskRunner() == null || !MinecraftClient.getInstance().isOnThread())
            throw new IllegalStateException("GAME_EXECUTOR_NOT_READY");
        return mod;
    }
    public void start(SurvivalAuthority.Context context, SurvivalAuthority.Boundary boundary,
                      JsonObject goal, BaseTarget resolvedBase, InventoryTarget inventoryTarget, Consumer<String> completed) {
        if (!(boundary instanceof ArbiterBoundary nativeBoundary) || !nativeBoundary.inputsBound())
            throw new IllegalArgumentException("GAME_EXECUTOR_INPUTS_NOT_BOUND");
        mod();
        activePrepared = null; lastReceipt = null;
        runner.start(context, boundary, () -> {
            SurvivalCallbacks.clearRootEvents((SurvivalCallbacks.RootResettable) (Object) mod().getClientBaritone().getPathingBehavior());
            SurvivalCallbacks.bindEvents(mod().getClientBaritone().getGameEventHandler());
            mod().getInputControls().clearControlledQueue();
            return ControlledTaskFactory.prepare(goal, resolvedBase, inventoryTarget);
        }, completed);
    }
    public void nativeInput(dev.aitalkstreamer.mc.core.HeldActionRouter.Action action, Runnable effect) {
        runner.effect(()->SurvivalActions.vanilla(action,effect));
    }
    public void tick() {
        runner.tick();
    }
    public void cancel() {
        runner.cancel();
    }
    public CraftReceipt craftReceipt() {
        return lastReceipt != null ? lastReceipt : activePrepared != null && activePrepared.task() instanceof ConfirmedCraftTask craft ? craft.receipt(false) : null;
    }
}
