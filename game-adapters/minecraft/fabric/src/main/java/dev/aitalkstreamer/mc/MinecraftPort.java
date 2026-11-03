package dev.aitalkstreamer.mc;

import com.google.gson.*;
import dev.aitalkstreamer.mc.core.*;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.util.ScreenshotRecorder;
import net.minecraft.client.gui.screen.DeathScreen;
import net.minecraft.client.gui.screen.ingame.InventoryScreen;
import net.minecraft.client.gui.screen.ingame.HandledScreen;
import net.minecraft.entity.mob.HostileEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.recipe.ShapedRecipe;
import net.minecraft.recipe.ShapelessRecipe;
import net.minecraft.util.Identifier;
import net.minecraft.util.WorldSavePath;
import java.util.*;
import java.util.function.Consumer;
import static dev.aitalkstreamer.mc.core.Json.*;

public final class MinecraftPort implements GamePort {
    private final MinecraftClient client;
    private final InputOwner inputs;
    private final ClientExecutor executor;
    private final NativeItemUse itemUse;
    private final ExecutorTaskSession itemSession;
    private final HeldActionRouter heldActions;
    private JsonObject observation;
    private JsonObject active;
    private ControlArbiter control;
    private ControlArbiter.Permit permit;
    private Consumer<JsonObject> completed;
    public MinecraftPort(MinecraftClient client, PhysicalKeys physicalKeys) {
        this.client = client;
        var providers = FabricLoader.getInstance().getEntrypointContainers(ClientExecutor.ENTRYPOINT, ClientExecutor.class);
        require(providers.size() <= 1, "GAME_EXECUTOR_MULTIPLE_PROVIDERS");
        if (providers.isEmpty()) executor = null;
        else {
            var provider = providers.getFirst();
            require(provider.getProvider().getMetadata().getId().equals("altoclef")
                    && provider.getProvider().getMetadata().getVersion().getFriendlyString().equals("1.21.1-0.19+ats.1"), "GAME_EXECUTOR_PROVIDER_INVALID");
            executor = provider.getEntrypoint();
            require(executor.profile().equals("altoclef_trial") && executor.skills().equals(List.of("navigate", "gather", "craft", "return_base")), "GAME_EXECUTOR_PROFILE_INVALID");
        }
        inputs = new InputOwner(client, physicalKeys);
        itemUse = new NativeItemUse(client, inputs, () -> observation);
        itemSession = new ExecutorTaskSession(itemUse);
        heldActions = new HeldActionRouter(new HeldActionRouter.Boundary() {
            @Override public boolean owns(HeldActionRouter.Action action) { return inputs.owns(action); }
            @Override public void run(HeldActionRouter.Action action, Runnable effect) {
                require(active != null && executor != null && permit != null && !itemSession.active(), "GAME_NATIVE_INPUT_NO_TASK");
                executor.nativeInput(action,effect);
            }
        });
    }
    @Override public void execute(Runnable action) { client.execute(action); }
    @Override public void releaseInputs() { inputs.release(); }
    @Override public boolean allowsGui(JsonObject task) {
        mainThread(); return executor != null && active != null && permit != null && control.allowed()
                && num(task, "control_epoch") == permit.epoch() && str(task, "task_id").equals(str(active, "task_id"))
                && client.player != null && client.player.isAlive() && client.isWindowFocused() && !client.isPaused()
                && executor.allowsGui(task);
    }
    public int clickRevision(int revision) {
        mainThread();
        if (active == null || permit == null || !control.allowed() || control.epoch() != permit.epoch()) return revision;
        return itemSession.active() ? itemUse.clickRevision(revision) : executor != null ? executor.clickRevision(revision) : revision;
    }
    public void inventorySynchronized(net.minecraft.network.packet.s2c.play.InventoryS2CPacket packet) {
        mainThread(); if (active == null) return;
        if (itemSession.active()) itemUse.inventory(packet);
        else if (executor != null) executor.inventorySynchronized(packet);
    }
    public void inventorySlotSynchronized(net.minecraft.network.packet.s2c.play.ScreenHandlerSlotUpdateS2CPacket packet) {
        mainThread(); if (active != null && !itemSession.active() && executor != null) executor.inventorySlotSynchronized(packet);
    }
    public boolean allowVanillaUse() {
        mainThread();
        if (active == null || permit == null || !control.allowed() || control.epoch() != permit.epoch()) return true;
        return !itemSession.active() && (executor == null || !executor.ownsUseTransaction());
    }
    public boolean ownsNativeInput(HeldActionRouter.Action action) { mainThread();return inputs.owns(action); }
    public <T> T nativeInput(HeldActionRouter.Action action, java.util.function.Supplier<T> effect, T rejected) {
        mainThread();
        // The dedicated native item transaction owns its one direct interaction; held vanilla repeats add none.
        if (action == HeldActionRouter.Action.USE && (itemSession.active() || executor != null && executor.ownsUseTransaction()) && inputs.owns(action)) return rejected;
        return heldActions.route(action,effect,rejected);
    }
    public void itemHealth(int food) { mainThread(); if (itemSession.active()) itemUse.health(food); else if (active != null && executor != null) executor.itemHealth(food); }
    public void itemBlock(net.minecraft.util.math.BlockPos pos, net.minecraft.block.BlockState state) {
        mainThread(); if (itemSession.active()) itemUse.block(pos, state);
    }
    private boolean hasUnboundExecutor() {
        var loader = FabricLoader.getInstance();
        if (executor == null) return loader.isModLoaded("baritone") || loader.isModLoaded("altoclef");
        return loader.getModContainer("baritone").map(mod -> mod.getContainingMod()
                .map(parent -> !parent.getMetadata().getId().equals("altoclef")).orElse(true)).orElse(false);
    }
    @Override public JsonObject capabilities(String instance) {
        boolean isolated = !hasUnboundExecutor();
        List<String> skills = new ArrayList<>();
        if (isolated) { if (executor != null) skills.addAll(executor.skills()); skills.addAll(List.of("use_item", "cancel")); }
        return obj("protocol_version", "1.0", "game_instance_id", instance, "adapter", "minecraft.fabric", "game_version", "1.21.1",
                "mod_version", "0.1.0", "execution_profile", executor == null ? "native_core" : executor.profile(), "skills", skills, "item_uses", isolated ? List.of("eat", "equip", "activate") : List.of(),
                "features", obj("recipes", true, "screenshots", true, "raw_frames", true, "local_takeover", isolated, "cancel_all", isolated,
                        "basic_pve", false, "survival_rules", false, "resource_chains", false, "task_ledger", true), "rule_fingerprint", null);
    }
    private void mainThread() { require(client.isOnThread(), "GAME_WRONG_THREAD"); }
    @Override public JsonObject recipe(JsonObject params) {
        mainThread(); require(client.world != null && client.player != null && client.getNetworkHandler() != null, "GAME_WORLD_UNAVAILABLE");
        String item = str(params, "item_id"); Identifier id = Identifier.tryParse(item);
        require(id != null && Registries.ITEM.containsId(id), "GAME_ITEM_UNKNOWN");
        // Capture this world's manager once; do not retain it across queries or world changes.
        var world = client.world; var manager = client.getNetworkHandler().getRecipeManager();
        Iterable<RecipeCatalog.Source> sources = () -> manager.values().stream().map(entry -> {
            var recipe = entry.value(); var output = recipe.getResult(world.getRegistryManager());
            var shaped = recipe instanceof ShapedRecipe value ? value : null;
            return new RecipeCatalog.Source(entry.id().toString(), Registries.RECIPE_TYPE.getId(recipe.getType()).toString(),
                    Registries.ITEM.getId(output.getItem()).toString(), output.getCount(),
                    shaped != null ? "shaped" : recipe instanceof ShapelessRecipe ? "shapeless" : "other",
                    shaped == null ? 0 : shaped.getWidth(), shaped == null ? 0 : shaped.getHeight(),
                    () -> recipe.getIngredients().stream().map(ingredient -> Arrays.stream(ingredient.getMatchingStacks())
                            .map(stack -> Registries.ITEM.getId(stack.getItem()).toString()).toList()).toList());
        }).iterator();
        return RecipeCatalog.lookup(item, Math.toIntExact(num(params, "count")), sources);
    }
    @Override public FrameEncoder.Capture captureFrame() {
        mainThread(); require(client.world != null && client.player != null, "GAME_WORLD_UNAVAILABLE");
        var framebuffer = client.getFramebuffer();
        require(framebuffer.textureWidth > 0 && framebuffer.textureWidth <= 1920 && framebuffer.textureHeight > 0
                && framebuffer.textureHeight <= 1080, "GAME_FRAME_DIMENSIONS");
        try (var image = ScreenshotRecorder.takeScreenshot(framebuffer)) {
            int width = image.getWidth(), height = image.getHeight(); int[] pixels = new int[width * height];
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                int abgr = image.getColor(x, y); pixels[y * width + x] = (abgr & 255) << 16 | abgr & 0xff00 | abgr >>> 16 & 255;
            }
            return new FrameEncoder.Capture(width, height, pixels);
        }
    }
    public String worldKey() {
        mainThread(); if (client.world == null || client.player == null) return null;
        return client.getServer() != null ? "local:" + client.getServer().getSavePath(WorldSavePath.ROOT).toAbsolutePath().normalize()
                : client.getCurrentServerEntry() != null ? "server:" + client.getCurrentServerEntry().address : null;
    }
    public String screen() {
        if (client.player == null || client.world == null) return "unknown";
        if (client.currentScreen instanceof DeathScreen || !client.player.isAlive()) return "death";
        if (client.currentScreen instanceof InventoryScreen) return "inventory";
        if (client.currentScreen instanceof HandledScreen<?>) return "container";
        if (client.currentScreen != null || client.isPaused() || !client.isWindowFocused()) return "menu";
        return "gameplay";
    }
    public JsonObject sample() {
        mainThread(); if (client.world == null || client.player == null) return null;
        var player = client.player; var position = player.getBlockPos(); JsonArray inventory = new JsonArray();
        TreeMap<String, Integer> counts = new TreeMap<>();
        for (int i = 0; i < player.getInventory().size(); i++) {
            ItemStack stack = player.getInventory().getStack(i); if (!stack.isEmpty()) counts.merge(Registries.ITEM.getId(stack.getItem()).toString(), stack.getCount(), Integer::sum);
        }
        counts.forEach((item, count) -> inventory.add(obj("item_id", item, "count", count)));
        int threats = client.world.getEntitiesByClass(HostileEntity.class, player.getBoundingBox().expand(16), e -> e.isAlive()).size();
        return obj("player", obj("health", player.getHealth(), "max_health", player.getMaxHealth(), "food", player.getHungerManager().getFoodLevel(),
                        "oxygen", Math.max(0, player.getAir()), "position", obj("dimension", client.world.getRegistryKey().getValue().toString(),
                                "x", position.getX(), "y", position.getY(), "z", position.getZ())),
                "inventory", inventory, "screen", screen(), "environment", obj("loaded_radius_chunks", null, "nearby_threats", threats),
                "unknown_fields", List.of("loaded_radius_chunks", "unloaded_region", "unopened_container_contents", "hostile_entities_outside_16_blocks", "server_rules"));
    }
    @Override public JsonObject check(JsonObject goal) {
        return check(goal, null);
    }
    @Override public JsonObject check(JsonObject goal, BaseTarget base) {
        mainThread(); String reason = null;
        if (!screen().equals("gameplay")) reason = "GAME_GUI_BLOCKED";
        else if (hasUnboundExecutor()) reason = "GAME_EXECUTOR_ADAPTER_NOT_BOUND";
        else if (str(goal, "skill").equals("return_base") && base == null) reason = "GAME_BASE_TARGET_REQUIRED";
        else if (executor != null && executor.skills().contains(str(goal, "skill"))) return executor.check(goal.deepCopy(), base);
        else if (!str(goal, "skill").equals("use_item")) reason = "GAME_CAPABILITY_UNAVAILABLE";
        else return itemUse.check(goal.deepCopy());
        return obj("allowed", reason == null, "reason", reason, "source", "runtime_client", "unknown_fields", List.of("server_side_use_restrictions"));
    }
    @Override public void start(JsonObject task, ControlArbiter control, Consumer<JsonObject> completed) {
        mainThread(); require(active == null && control.allowed(), "GAME_TASK_BUSY_OR_CONTROL_REVOKED");
        JsonObject check = check(task.getAsJsonObject("goal"), BaseTarget.forTask(task, observation)); require(check.get("allowed").getAsBoolean(), nullable(check, "reason") == null ? "GAME_PRECONDITION_FAILED" : str(check, "reason"));
        ControlArbiter.Permit accepted = control.permit(); require(accepted.epoch() == num(task, "control_epoch"), "GAME_CONTROL_CONFLICT");
        this.active = task.deepCopy(); this.control = control; this.completed = completed; permit = accepted;
        if (!str(task.getAsJsonObject("goal"), "skill").equals("use_item")) {
            try { executor.start(task.deepCopy(), observation, control, inputs, this::finish); }
            catch (RuntimeException | Error error) {
                try { executor.cancel("GAME_EXECUTOR_START_FAILED"); active = null; this.completed = null; permit = null; }
                catch (RuntimeException | Error cleanup) { if (cleanup != error) error.addSuppressed(cleanup); }
                throw error;
            }
            return;
        }
        try { itemSession.start(task.deepCopy(), observation, control, this::finish); }
        catch (RuntimeException | Error error) {
            try { itemSession.cancel("GAME_EXECUTOR_START_FAILED"); active = null; this.completed = null; permit = null; }
            catch (RuntimeException | Error cleanup) { if (cleanup != error) error.addSuppressed(cleanup); }
            throw error;
        }
    }
    public void tick(BridgeCore bridge) {
        mainThread();
        observation = bridge.latestObservation();
        if (active == null) return;
        if (!str(active.getAsJsonObject("goal"), "skill").equals("use_item")) { executor.tick(observation); return; }
        itemSession.tick(observation);
    }
    @Override public void cancel(String reason) {
        mainThread(); if (active == null) { inputs.release(); return; }
        if (!str(active.getAsJsonObject("goal"), "skill").equals("use_item")) { executor.cancel(reason); return; }
        itemSession.cancel(reason);
    }
    private void finish(JsonObject result) {
        control.release(permit.epoch(), inputs::release); active = null; permit = null;
        Consumer<JsonObject> callback = completed; completed = null; callback.accept(result);
    }
}
