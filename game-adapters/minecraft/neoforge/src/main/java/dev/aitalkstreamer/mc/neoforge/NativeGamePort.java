package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.*;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;
import net.minecraft.client.gui.screens.DeathScreen;
import net.minecraft.client.gui.components.Button;
import net.minecraft.network.chat.Component;
import net.minecraft.client.gui.screens.PauseScreen;
import net.minecraft.client.gui.screens.inventory.InventoryScreen;
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.item.crafting.ShapedRecipe;
import net.minecraft.world.item.crafting.ShapelessRecipe;
import java.util.*;
import java.util.function.Consumer;
import java.util.function.Supplier;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Mojmap facade over this one real player; transport, lease and ledger stay in BridgeCore. */
public final class NativeGamePort implements GamePort {
    private final Minecraft client;
    private final NativeInputOwner inputs;
    private final NativeItemUse itemUse;
    private final NativeTravel travel;
    private final NativeHunt hunting;
    private final NativeCraft craft;
    private final NativeSmelt cooking;
    private final NativeSurvival survival;
    private final NativeFoodSources foodSources = new NativeFoodSources();
    private final NativeConstruction construction = new NativeConstruction();
    private final NativeWorldFrames worldFrames = new NativeWorldFrames();
    private ExecutorTaskSession.Runtime activeRuntime;
    private NativeContext resumeOwner;
    private Runnable resumeReady;
    private Consumer<String> resumeFailed;
    private long resumeDeadline;
    private int resumeRequests, resumesConfirmed;
    private boolean respawning;
    private int respawnRequests, respawnsConfirmed;
    private final ArrayDeque<Long> respawnTimes = new ArrayDeque<>();
    private Object respawnServer;
    private String respawnWorldKey;
    private final ExecutorTaskSession itemSession;
    private final Supplier<JsonObject> observation;
    NativeGamePort(Minecraft client, PhysicalKeys physicalKeys, Supplier<JsonObject> observation) {
        this.client = client; this.observation = observation;
        inputs = new NativeInputOwner(client, physicalKeys);
        itemUse = new NativeItemUse(client, inputs, observation);
        travel = new NativeTravel(client, inputs);
        hunting = new NativeHunt(client, inputs, travel);
        craft = new NativeCraft(client, inputs, observation);
        cooking = new NativeSmelt(client, inputs, observation);
        survival = new NativeSurvival(client, inputs, itemUse, travel);
        itemSession = new ExecutorTaskSession(new ExecutorTaskSession.Runtime() {
            public void start(JsonObject task, ControlArbiter control, ControlArbiter.Permit permit,
                              InventoryTarget target, BaseTarget base, Runnable finished) {
                require(activeRuntime == null, "GAME_TASK_BUSY");
                activeRuntime = switch (str(task.getAsJsonObject("goal"), "skill")) {
                    case "use_item" -> itemUse; case "craft" -> craftRuntime(task.getAsJsonObject("goal"));
                    case "gather" -> gatherRuntime(task.getAsJsonObject("goal")); default -> travel;
                };
                survival.bind(activeRuntime);
                survival.start(task, control, permit, target, base, finished);
            }
            public void tick() { if (activeRuntime != null) survival.tick(); }
            public void cancel() { if (activeRuntime != null) { survival.cancel(); activeRuntime = null; } }
            public boolean allowsGui() { return activeRuntime != null && activeRuntime.allowsGui(); }
            public CraftReceipt craftReceipt() { return activeRuntime == craft ? craft.craftReceipt() : activeRuntime == cooking ? cooking.craftReceipt() : null; }
            public ItemUseReceipt itemUseReceipt() { return activeRuntime == itemUse ? itemUse.itemUseReceipt() : null; }
        });
    }
    private ExecutorTaskSession.Runtime craftRuntime(JsonObject goal) {
        return craft.check(goal).get("allowed").getAsBoolean() || !cooking.hasRecipe(goal) ? craft : cooking;
    }
    private ExecutorTaskSession.Runtime gatherRuntime(JsonObject goal) {
        return !NativeHuntPlan.material(str(goal, "item_id")) || travel.check(goal, null).get("allowed").getAsBoolean()
                ? travel : hunting;
    }
    private void mainThread() { require(client.isSameThread(), "GAME_WRONG_THREAD"); }
    private void world() {
        mainThread(); require(client.level != null && client.player != null && client.getConnection() != null,
                "GAME_WORLD_UNAVAILABLE");
    }
    @Override public void execute(Runnable action) { client.execute(action); }
    @Override public JsonObject capabilities(String instance) {
        var report = NativeCapabilities.report(instance, NativeHooks.ready());
        report.getAsJsonObject("features").addProperty("targeted_planting",
                NativeHooks.ready() && NativePlanting.runtimeProof().get("valid").getAsBoolean());
        return report;
    }
    @Override public void releaseInputs() {
        mainThread(); inputs.release();
    }
    @Override public void cancel(String reason) { mainThread(); itemSession.cancel(reason); finishResume("GAME_CONTROL_CONFLICT"); }
    @Override public void resumeAuto(Runnable ready, Consumer<String> failed) {
        mainThread(); world();
        var server = client.getSingleplayerServer();
        boolean dead = client.screen != null && client.screen.getClass() == DeathScreen.class && !client.player.isAlive();
        if (resumeReady != null || server == null || server.isPublished() || client.screen == null
                || !(dead || client.screen.getClass() == PauseScreen.class && client.player.isAlive()) || !client.isWindowActive()
                || client.getOverlay() != null || !client.isGameLoadFinished() || itemSession.active()
                || !inputs.allClear() || inputs.physicallyActive() || !client.player.inventoryMenu.getCarried().isEmpty()) {
            failed.accept("GAME_PRECONDITION_FAILED"); return;
        }
        Button respawnButton = null;
        if (dead) {
            long now = System.nanoTime();
            while (!respawnTimes.isEmpty() && now-respawnTimes.getFirst() >= 600_000_000_000L) respawnTimes.removeFirst();
            if (client.level.getLevelData().isHardcore() || respawnTimes.size() >= 3) { failed.accept("GAME_PRECONDITION_FAILED"); return; }
            String label = Component.translatable("deathScreen.respawn").getString();
            for (var child : client.screen.children()) if (child instanceof Button button && button.active && button.visible
                    && button.getMessage().getString().equals(label)) {
                if (respawnButton != null) { failed.accept("GAME_PRECONDITION_FAILED"); return; }
                respawnButton = button;
            }
            if (respawnButton == null) { failed.accept("GAME_PRECONDITION_FAILED"); return; }
        }
        resumeOwner = new NativeContext(client.level,client.player,client.getConnection(),client.gameMode);
        resumeReady = ready; resumeFailed = failed; resumeDeadline = System.nanoTime() + (dead ? 8_000_000_000L : 2_000_000_000L); resumeRequests++;
        respawning = dead; respawnServer = server; respawnWorldKey = worldKey();
        if (dead) {
            // Invoke the same ordinary enabled vanilla button, once. No health,
            // inventory, world-file or server-command writes are performed here.
            respawnRequests++; respawnTimes.addLast(System.nanoTime()); respawnButton.onPress(); return;
        }
        // Ordinary client UI action, no synthetic keyboard event and no world mutation.
        client.setScreen(null); client.mouseHandler.grabMouse();
    }
    private void finishResume(String error) {
        if (resumeReady == null) return;
        if (error != null && resumeOwner != null) try {
            resumeOwner.require(client.level,client.player,client.getConnection(),client.gameMode);
            if (client.screen == null && client.player.isAlive() && client.getSingleplayerServer() != null
                    && !client.getSingleplayerServer().isPublished()) client.pauseGame(false);
        } catch (RuntimeException changed) { /* Never alter another world's UI. */ }
        var ready = resumeReady; var failed = resumeFailed; resumeReady = null; resumeFailed = null; resumeOwner = null;
        if (error == null) { resumesConfirmed++; if (respawning) respawnsConfirmed++; ready.run(); } else failed.accept(error);
        respawning = false; respawnServer = null; respawnWorldKey = null;
    }
    private void tickResume() {
        if (resumeReady == null) return;
        try {
            if (respawning) {
                require(client.level == resumeOwner.world() && client.getConnection() == resumeOwner.connection()
                        && client.gameMode == resumeOwner.interactions() && client.getSingleplayerServer() == respawnServer
                        && Objects.equals(worldKey(),respawnWorldKey) && !client.getSingleplayerServer().isPublished()
                        && client.isWindowActive() && !inputs.physicallyActive(),"GAME_PRECONDITION_FAILED");
                if (client.player == resumeOwner.player() || !client.player.isAlive() || client.screen != null) {
                    if (System.nanoTime() > resumeDeadline) finishResume("GAME_RESUME_TIMEOUT");
                    return;
                }
                if ("gameplay".equals(screen()) && worldFrames.ready(client.level,client.player,client.getConnection())) finishResume(null);
                else if (System.nanoTime() > resumeDeadline) finishResume("GAME_RESUME_TIMEOUT");
                return;
            }
            resumeOwner.require(client.level,client.player,client.getConnection(),client.gameMode);
            require(client.player.isAlive() && client.isWindowActive() && !inputs.physicallyActive()
                    && client.screen == null && client.getOverlay() == null && client.getSingleplayerServer() != null
                    && !client.getSingleplayerServer().isPublished(),"GAME_PRECONDITION_FAILED");
            if ("gameplay".equals(screen()) && worldFrames.ready(client.level,client.player,client.getConnection())) finishResume(null);
            else if (System.nanoTime() > resumeDeadline) finishResume("GAME_RESUME_TIMEOUT");
        } catch (RuntimeException error) { finishResume("GAME_PRECONDITION_FAILED"); }
    }
    JsonObject resumeProof() { mainThread(); return obj("pending",resumeReady != null,"requests",resumeRequests,
            "confirmed",resumesConfirmed,"synthetic_key_events",0,"world_data_mutated",respawnRequests>0,
            "ordinary_respawn_requests",respawnRequests,"confirmed_respawns",respawnsConfirmed,"world_data_injection",false); }
    @Override public JsonObject check(JsonObject goal) {
        return check(goal, null);
    }
    @Override public JsonObject check(JsonObject goal, BaseTarget base) {
        world();
        if (!NativeHooks.ready()) return obj("allowed", false, "reason", "GAME_EXECUTOR_ADAPTER_NOT_BOUND",
                "source", "runtime_client", "unknown_fields", List.of("server_side_use_restrictions"));
        return switch (str(goal, "skill")) {
            case "use_item" -> itemUse.check(goal.deepCopy()); case "craft" -> craftRuntime(goal) == craft ? craft.check(goal.deepCopy()) : cooking.check(goal.deepCopy());
            case "gather" -> gatherRuntime(goal) == hunting ? hunting.check(goal.deepCopy()) : travel.check(goal.deepCopy(), base);
            default -> travel.check(goal.deepCopy(), base);
        };
    }
    @Override public void start(JsonObject task, ControlArbiter control, Consumer<JsonObject> completed) {
        world(); require(NativeHooks.ready(), "GAME_EXECUTOR_ADAPTER_NOT_BOUND");
        JsonObject checked = check(task.getAsJsonObject("goal"), BaseTarget.forTask(task, observation.get()));
        require(checked.get("allowed").getAsBoolean(), nullable(checked, "reason") == null
                ? "GAME_PRECONDITION_FAILED" : str(checked, "reason"));
        ControlArbiter.Permit permit = control.permit();
        itemSession.start(task.deepCopy(), observation.get(), control, result -> {
            control.release(permit.epoch(), inputs::release); completed.accept(result);
        });
    }
    void tick() { mainThread(); tickResume(); itemSession.tick(observation.get()); }
    boolean physicallyActive() { return inputs.physicallyActive(); }
    boolean allowVanillaUse() { mainThread(); return !itemSession.active() && !inputs.ownsUse(); }
    boolean allowVanillaAttack() { mainThread(); return !travel.activeGather() && !hunting.active() && !survival.ownsAttack(); }
    JsonObject inputProof() { mainThread(); return inputs.proof(); }
    JsonObject travelProof() { mainThread(); return travel.proof(); }
    JsonObject craftProof() { mainThread(); return craft.proof(); }
    JsonObject cookingProof() { mainThread(); return cooking.proof(); }
    JsonObject huntingProof() { mainThread(); return hunting.proof(); }
    JsonObject survivalProof() { mainThread(); return survival.proof(); }
    JsonObject plantingProof() { mainThread(); return NativePlanting.runtimeProof(); }
    @Override public boolean allowsGui(JsonObject acceptedTask) { mainThread(); return activeRuntime == craft && craft.allowsGui(acceptedTask)
            || activeRuntime == cooking && cooking.allowsGui(acceptedTask); }
    int clickRevision(int revision) { mainThread(); return survival.eating() ? itemUse.clickRevision(revision) : activeRuntime == craft ? craft.clickRevision(revision)
            : activeRuntime == cooking ? cooking.clickRevision(revision)
            : activeRuntime == itemUse ? itemUse.clickRevision(revision)
            : activeRuntime == travel ? travel.clickRevision(revision) : revision; }
    void inventory(net.minecraft.network.protocol.game.ClientboundContainerSetContentPacket packet) {
        mainThread(); if (itemSession.active()) itemUse.inventory(packet);
        craft.inventory(packet);
        cooking.inventory(packet);
        travel.inventory(packet);
        if (packet.getContainerId() == 0) { travel.inventoryPacket(); hunting.inventoryPacket(); }
    }
    void opened(net.minecraft.network.protocol.game.ClientboundOpenScreenPacket packet) { mainThread(); craft.opened(packet); cooking.opened(packet); }
    void inventorySlot(net.minecraft.network.protocol.game.ClientboundContainerSetSlotPacket packet) {
        cooking.slot(packet);
        mainThread(); if (packet.getContainerId() == 0 || packet.getContainerId() == -2) { travel.inventoryPacket(); hunting.inventoryPacket(); }
    }
    void health(int food) { mainThread(); if (itemSession.active()) itemUse.health(food); }
    void block(net.minecraft.core.BlockPos pos, net.minecraft.world.level.block.state.BlockState state) {
        mainThread(); if (itemSession.active()) itemUse.block(pos, state);travel.block(pos,state);
    }
    public String worldKey() {
        mainThread(); if (client.level == null || client.player == null) return null;
        var server = client.getSingleplayerServer();
        return server != null ? "local:" + server.getWorldPath(net.minecraft.world.level.storage.LevelResource.ROOT)
                .toAbsolutePath().normalize()
                : client.getCurrentServer() != null ? "server:" + client.getCurrentServer().ip : null;
    }
    public String screen() {
        mainThread(); if (client.player == null || client.level == null) return "unknown";
        if (client.screen instanceof DeathScreen || !client.player.isAlive()) return "death";
        if (client.screen instanceof InventoryScreen) return "inventory";
        if (client.screen instanceof AbstractContainerScreen<?>) return "container";
        if (client.screen != null || client.getOverlay() != null || client.noRender || !client.isGameLoadFinished()
                || client.isPaused() || !client.isWindowActive()) return "menu";
        return "gameplay";
    }
    void rendered() {
        mainThread();
        worldFrames.rendered(client.level, client.player, client.getConnection(), client.screen == null
                && client.getOverlay() == null && !client.noRender && client.isGameLoadFinished() && client.isWindowActive());
    }
    JsonObject presentationProof() {
        mainThread(); boolean ready = worldFrames.ready(client.level, client.player, client.getConnection());
        return obj("completed_game_frames", worldFrames.frames(), "required_game_frames", NativeWorldFrames.REQUIRED_FRAMES,
                "scope_generation", worldFrames.generation(), "world_frames_ready", ready,
                "desktop_presentation_verified", false, "overlay_open", client.getOverlay() != null,
                "no_render", client.noRender, "game_load_finished", client.isGameLoadFinished(), "window_active", client.isWindowActive());
    }
    SingleplayerPausePolicy.Context pauseContext(boolean bridgeTaskIdle) {
        mainThread(); var server = client.getSingleplayerServer();
        return new SingleplayerPausePolicy.Context(client.level, client.player, client.getConnection(), server,
                server != null && server.isPublished(), client.player != null && client.player.isAlive()
                        && !(client.screen instanceof DeathScreen),
                client.screen != null || client.getOverlay() != null || client.noRender || !client.isGameLoadFinished(),
                client.isPaused(), worldFrames.ready(client.level, client.player, client.getConnection()), inputs.allClear(),
                bridgeTaskIdle && !itemSession.active(), inputs.physicallyActive());
    }
    boolean openPauseMenu(SingleplayerPausePolicy.Context expected, boolean bridgeTaskIdle) {
        var current = pauseContext(bridgeTaskIdle);
        if (current.world() != expected.world() || current.player() != expected.player()
                || current.connection() != expected.connection() || current.server() != expected.server()
                || current.server() == null || current.published() || !current.alive() || current.screenOpen()
                || current.paused() || !current.inputsClear() || !current.taskIdle() || current.physicalHeld()) return false;
        client.pauseGame(false); return true;
    }
    public JsonObject sample() {
        mainThread(); if (client.level == null || client.player == null || client.getConnection() == null) return null;
        var player = client.player; var position = player.blockPosition();
        TreeMap<String,Integer> counts = new TreeMap<>(); JsonArray inventory = new JsonArray();
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) {
            var stack = player.getInventory().getItem(i);
            if (!stack.isEmpty()) counts.merge(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(), stack.getCount(), Integer::sum);
        }
        counts.forEach((item, count) -> inventory.add(obj("item_id", item, "count", count)));
        int threats = client.level.getEntitiesOfClass(Monster.class, player.getBoundingBox().inflate(16), e -> e.isAlive()).size();
        return obj("player", obj("health", player.getHealth(), "max_health", player.getMaxHealth(),
                "food", player.getFoodData().getFoodLevel(), "oxygen", Math.max(0, player.getAirSupply()),
                "position", obj("dimension", client.level.dimension().location().toString(),
                        "x", position.getX(), "y", position.getY(), "z", position.getZ())),
                "inventory", inventory, "screen", screen(),
                "environment", obj("loaded_radius_chunks", NativeTelemetry.loadedRadius(client), "nearby_threats", threats),
                "details", NativeTelemetry.sample(client, foodSources, construction, travel),
                "unknown_fields", List.of("unloaded_region", "unopened_container_contents",
                        "hostile_entities_outside_16_blocks", "server_rules"));
    }
    @Override public JsonObject recipe(JsonObject params) {
        world(); String item = str(params, "item_id"); var id = ResourceLocation.tryParse(item);
        require(id != null && BuiltInRegistries.ITEM.containsKey(id), "GAME_ITEM_UNKNOWN");
        var level = client.level; var manager = client.getConnection().getRecipeManager();
        int[] unavailable = {0};
        JsonObject result = RecipeCatalog.lookupProjected(item, Math.toIntExact(num(params, "count")), manager.getRecipes(), entry -> {
          try {
            var recipe = entry.value(); var output = recipe.getResultItem(level.registryAccess());
            var type = BuiltInRegistries.RECIPE_TYPE.getKey(recipe.getType());
            if (output == null || output.isEmpty() || type == null) { unavailable[0]++; return null; }
            var shaped = recipe instanceof ShapedRecipe value ? value : null;
            return new RecipeCatalog.Source(entry.id().toString(), type.toString(),
                    BuiltInRegistries.ITEM.getKey(output.getItem()).toString(), output.getCount(),
                    shaped != null ? "shaped" : recipe instanceof ShapelessRecipe ? "shapeless" : "other",
                    shaped == null ? 0 : shaped.getWidth(), shaped == null ? 0 : shaped.getHeight(),
                    () -> recipe.getIngredients().stream().map(ingredient -> Arrays.stream(ingredient.getItems())
                            .map(stack -> BuiltInRegistries.ITEM.getKey(stack.getItem()).toString()).toList()).toList());
          } catch (RuntimeException unsupported) {
            if (++unavailable[0] <= 3) org.slf4j.LoggerFactory.getLogger("AiTalkStreamerNeoForge").warn(
                    "Static recipe output unavailable: {} ({})", entry.id(), entry.value().getClass().getName(), unsupported);
            throw unsupported;
          }
        }, RecipeCatalog.MODDED_SCAN_LIMIT);
        if (unavailable[0] > 0) org.slf4j.LoggerFactory.getLogger("AiTalkStreamerNeoForge").info(
                "Recipe query projected received catalogue with {} unavailable static outputs; result explicitly incomplete", unavailable[0]);
        return result;
    }
    @Override public FrameEncoder.Capture captureFrame() {
        world(); var target = client.getMainRenderTarget();
        require(target.width > 0 && target.width <= 1920 && target.height > 0 && target.height <= 1080,
                "GAME_FRAME_DIMENSIONS");
        try (var image = Screenshot.takeScreenshot(target)) {
            int width = image.getWidth(), height = image.getHeight(); int[] pixels = new int[width * height];
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                int abgr = image.getPixelRGBA(x, y);
                pixels[y * width + x] = (abgr & 255) << 16 | abgr & 0xff00 | abgr >>> 16 & 255;
            }
            return new FrameEncoder.Capture(width, height, pixels);
        }
    }
}
