package dev.aitalkstreamer.mc;

import com.google.gson.*;
import dev.aitalkstreamer.mc.core.*;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientLifecycleEvents;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import org.lwjgl.glfw.GLFW;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.net.URI;
import java.nio.file.*;
import static dev.aitalkstreamer.mc.core.Json.*;

public final class McBridgeClient implements ClientModInitializer {
    private static final Logger LOG = LoggerFactory.getLogger("AiTalkStreamerMC");
    private static volatile BridgeCore bridge;
    private static KeyBinding panicKey;
    private static CursorActivity cursor;
    private static PhysicalKeys physicalKeys;
    private MinecraftPort port;
    private static MinecraftPort activePort;
    @Override public void onInitializeClient() {
        MinecraftClient client = MinecraftClient.getInstance();
        physicalKeys = new PhysicalKeys(client.getWindow().getHandle()); port = new MinecraftPort(client, physicalKeys); activePort = port;
        panicKey = KeyBindingHelper.registerKeyBinding(new KeyBinding("key.ai_talk_streamer.takeover", InputUtil.Type.KEYSYM,
                GLFW.GLFW_KEY_F10, "category.ai_talk_streamer"));
        cursor = new CursorActivity(client.getWindow().getHandle(), () -> System.nanoTime() / 1_000_000);
        ClientTickEvents.END_CLIENT_TICK.register(c -> {
            BridgeCore current = bridge; if (current == null) return;
            try {
                JsonObject sample = port.sample(); current.observe(c.world, port.worldKey(), sample); port.tick(current);
            } catch (Throwable error) { current.takeover(false, "GAME_SAMPLE_OR_EXECUTOR_FAILED"); LOG.error("MC bridge local failure", error); }
        });
        ClientLifecycleEvents.CLIENT_STOPPING.register(c -> { BridgeCore current = bridge; bridge = null;
            if (current != null) { current.takeover(false, "CLIENT_STOPPING"); new Thread(current::close, "mc-bridge-stop").start(); } });
        Thread prepare = new Thread(() -> {
            try {
                Path root = FabricLoader.getInstance().getConfigDir(); Path config = root.resolve("ai-talk-streamer-bridge.json");
                if (!Files.exists(config)) Files.writeString(config, GSON.toJson(obj("enabled", false, "endpoint", "ws://127.0.0.1:8020/api/dsh/game/bridge")), StandardOpenOption.CREATE_NEW);
                JsonObject settings = JsonParser.parseString(Files.readString(config)).getAsJsonObject();
                require(settings.keySet().equals(java.util.Set.of("enabled", "endpoint")) && settings.get("enabled").isJsonPrimitive()
                        && settings.getAsJsonPrimitive("enabled").isBoolean(), "GAME_CONFIG_INVALID");
                if (!settings.get("enabled").getAsBoolean()) { LOG.info("MC bridge disabled; configure {} to enable", config); return; }
                LocalJournal journal = new LocalJournal(root.resolve("ai-talk-streamer-bridge"));
                try { BridgeCore created = new BridgeCore(port, journal, URI.create(str(settings, "endpoint"))); bridge = created; created.start(); }
                catch (Throwable error) { journal.close(); throw error; }
            } catch (Throwable error) { LOG.error("MC bridge was not started", error); }
        }, "mc-bridge-prepare"); prepare.setDaemon(true); prepare.start();
    }
    public static void key(long window, int key, int scancode, int action) {
        if (physicalKeys != null) physicalKeys.event(window, key, scancode, action);
        BridgeCore current = bridge; if (current == null || window != MinecraftClient.getInstance().getWindow().getHandle()) return;
        if (action == GLFW.GLFW_PRESS && panicKey != null && panicKey.matchesKey(key, scancode)) current.takeover(false, "LOCAL_PANIC_KEY");
        else if ((action == GLFW.GLFW_PRESS || action == GLFW.GLFW_REPEAT) && current.control.mode() == ControlArbiter.Mode.AUTO)
            current.takeover(true, "PHYSICAL_KEYBOARD_INPUT");
    }
    public static int clickRevision(int revision) {
        return activePort == null ? revision : activePort.clickRevision(revision);
    }
    public static void inventorySynchronized(net.minecraft.network.packet.s2c.play.InventoryS2CPacket packet) {
        if (activePort != null) activePort.inventorySynchronized(packet);
    }
    public static void inventorySlotSynchronized(net.minecraft.network.packet.s2c.play.ScreenHandlerSlotUpdateS2CPacket packet) {
        if (activePort != null) activePort.inventorySlotSynchronized(packet);
    }
    public static boolean allowVanillaUse() { return activePort == null || activePort.allowVanillaUse(); }
    public static <T> T nativeInput(HeldActionRouter.Action action, java.util.function.Supplier<T> effect, T rejected) {
        MinecraftPort currentPort=activePort;
        if (currentPort == null || !currentPort.ownsNativeInput(action)) return effect.get();
        try { return currentPort.nativeInput(action,effect,rejected); }
        catch (RuntimeException | Error error) {
            BridgeCore current=bridge;
            if (current != null) current.takeover(false,"GAME_NATIVE_INPUT_FAILED");
            LOG.error("MC held-input continuation failed; it will not be replayed",error);
            if (error instanceof Error fatal) throw fatal;
            return rejected;
        }
    }
    public static void itemHealth(int food) { if (activePort != null) activePort.itemHealth(food); }
    public static void itemBlock(net.minecraft.util.math.BlockPos pos, net.minecraft.block.BlockState state) {
        if (activePort != null) activePort.itemBlock(pos, state);
    }
    public static void button(long window, int button, int action) {
        if (action != GLFW.GLFW_PRESS) return;
        BridgeCore current = bridge; if (current == null || window != MinecraftClient.getInstance().getWindow().getHandle()) return;
        if (panicKey != null && panicKey.matchesMouse(button)) current.takeover(false, "LOCAL_PANIC_KEY");
        else mouse(window);
    }
    public static void expectCursorWarp(long window, double x, double y) {
        if (cursor != null && MinecraftClient.getInstance().isOnThread()) cursor.expectWarp(window, x, y);
    }
    public static void cursor(long window, double x, double y) {
        if (cursor != null && cursor.moved(window, x, y)) mouse(window);
    }
    public static void mouse(long window) {
        BridgeCore current = bridge;
        if (current != null && window == MinecraftClient.getInstance().getWindow().getHandle() && current.control.mode() == ControlArbiter.Mode.AUTO)
            current.takeover(true, "PHYSICAL_MOUSE_INPUT");
    }
}
