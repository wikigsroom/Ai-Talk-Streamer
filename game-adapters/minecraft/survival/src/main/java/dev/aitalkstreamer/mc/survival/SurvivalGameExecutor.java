package dev.aitalkstreamer.mc.survival;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.ClientExecutor;
import dev.aitalkstreamer.mc.InputOwner;
import dev.aitalkstreamer.mc.core.ControlArbiter;
import dev.aitalkstreamer.mc.core.ExecutorTaskSession;
import dev.aitalkstreamer.mc.core.InventoryTarget;
import dev.aitalkstreamer.mc.core.BaseTarget;
import dev.aitalkstreamer.mc.core.CraftReceipt;
import net.minecraft.client.MinecraftClient;
import net.minecraft.registry.Registries;
import net.minecraft.util.Identifier;
import adris.altoclef.TaskCatalogue;
import java.util.List;
import java.util.function.Consumer;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Actual same-player binding; the package's unconditional pre-launch gate still applies. */
public final class SurvivalGameExecutor implements ClientExecutor {
    private final ControlledAltoClefDriver driver = new ControlledAltoClefDriver();
    private ExecutorTaskSession session;
    @Override public String profile() { return "altoclef_trial"; }
    @Override public List<String> skills() { return List.of("navigate", "gather", "craft", "return_base"); }
    @Override public JsonObject check(JsonObject goal, BaseTarget base) {
        MinecraftClient client = MinecraftClient.getInstance(); String reason = null;
        require(client.isOnThread(), "GAME_WRONG_THREAD");
        if (client.player == null || client.world == null || client.getNetworkHandler() == null) reason = "GAME_WORLD_UNAVAILABLE";
        else if (client.currentScreen != null || !client.isWindowFocused() || client.isPaused()) reason = "GAME_GUI_BLOCKED";
        else if (!skills().contains(str(goal, "skill"))) reason = "GAME_CAPABILITY_UNAVAILABLE";
        else if (str(goal, "skill").equals("navigate")) {
            if (!client.world.getRegistryKey().getValue().toString().equals(str(goal.getAsJsonObject("target"), "dimension"))) reason = "GAME_DIMENSION_CHANGED";
        } else if (str(goal, "skill").equals("return_base")) {
            if (base == null || !str(goal, "base_id").equals(base.baseId())) reason = "GAME_BASE_TARGET_REQUIRED";
            else if (!client.world.getRegistryKey().getValue().toString().equals(base.dimension())) reason = "GAME_BASE_DIMENSION_CHANGED";
        } else if (str(goal, "skill").equals("craft")) {
            try { CraftSpec.capture(goal, null); }
            catch (Rejected denied) { reason = denied.code; }
        } else {
            Identifier item = Identifier.tryParse(str(goal, "item_id"));
            if (item == null || !Registries.ITEM.containsId(item)) reason = "GAME_ITEM_UNKNOWN";
            else if (!TaskCatalogue.taskExists(Registries.ITEM.get(item))) reason = "GAME_RESOURCE_NOT_CATALOGUED";
            else {
                long total = 0;
                for (int i = 0; i < client.player.getInventory().size(); i++) {
                    var stack = client.player.getInventory().getStack(i);
                    if (stack.isOf(Registries.ITEM.get(item))) total += stack.getCount();
                }
                try { new InventoryTarget(str(goal, "item_id"), Math.toIntExact(total), Math.toIntExact(num(goal, "count")), 1); }
                catch (Rejected denied) { reason = denied.code; }
            }
        }
        return obj("allowed", reason == null, "reason", reason, "source", "runtime_client",
                "unknown_fields", List.of("server_side_resource_restrictions", "unloaded_route", "resource_chain_gui_support"));
    }
    @Override public void start(JsonObject task, JsonObject observation, ControlArbiter control, InputOwner inputs, Consumer<JsonObject> completed) {
        require(session == null || !session.active(), "GAME_TASK_BUSY");
        session = new ExecutorTaskSession(new ExecutorTaskSession.Runtime() {
            @Override public void start(JsonObject accepted, ControlArbiter actual, ControlArbiter.Permit permit, InventoryTarget target, BaseTarget base, Runnable finished) {
                var context = new SurvivalAuthority.Context(str(accepted, "task_id"), permit.controller(), permit.lease(), permit.world(), permit.epoch());
                driver.start(context, new ArbiterBoundary(actual, permit, context.task(), inputs), accepted.getAsJsonObject("goal"), base, target,
                        signal -> finished.run());
            }
            @Override public void tick() { driver.tick(); }
            @Override public void cancel() { driver.cancel(); }
            @Override public boolean allowsGui() { return SurvivalGui.allows(task); }
            @Override public CraftReceipt craftReceipt() { return driver.craftReceipt(); }
        });
        session.start(task, observation, control, completed);
    }
    @Override public void nativeInput(dev.aitalkstreamer.mc.core.HeldActionRouter.Action action, Runnable effect) {
        require(session != null && session.active(), "GAME_NATIVE_INPUT_NO_TASK");driver.nativeInput(action,effect);
    }
    @Override public void tick(JsonObject observation) { if (session != null) session.tick(observation); }
    @Override public boolean allowsGui(JsonObject task) { return session != null && session.active() && SurvivalGui.allows(task); }
    @Override public boolean beforeUse() { require(session != null && session.active(), "GAME_GUI_NO_TASK"); return SurvivalGui.beforeUse(); }
    @Override public boolean ownsUseTransaction() { return session != null && session.active() && (ControlledEatingTask.blocksRepeatedUse() || ControlledEquipment.busy() || ControlledShield.busy() || ControlledStorage.blocksInventory()); }
    @Override public void itemHealth(int food) { ControlledEatingTask.health(food); }
    @Override public int clickRevision(int revision) { return ControlledStorage.clickRevision(ControlledEquipment.clickRevision(ControlledEatingTask.clickRevision(ControlledCookingTask.clickRevision(ConfirmedCraftTask.clickRevision(revision))))); }
    @Override public void inventorySynchronized(net.minecraft.network.packet.s2c.play.InventoryS2CPacket packet) {
        SurvivalGui.synchronizedInventory(packet); ConfirmedCraftTask.synchronizedInventory(packet); ControlledCookingTask.synchronizedInventory(packet); ControlledEatingTask.inventory(packet); ControlledEquipment.inventory(packet); ControlledStorage.inventory(packet);
    }
    @Override public void inventorySlotSynchronized(net.minecraft.network.packet.s2c.play.ScreenHandlerSlotUpdateS2CPacket packet) { ControlledCookingTask.synchronizedSlot(packet); }
    @Override public void cancel(String reason) { if (session != null) session.cancel(reason); }
}
