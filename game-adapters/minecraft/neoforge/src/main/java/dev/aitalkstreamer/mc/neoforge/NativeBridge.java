package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.*;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.Minecraft;
import net.neoforged.fml.loading.FMLPaths;
import java.net.URI;
import java.nio.file.*;
import java.util.Set;
import org.lwjgl.glfw.GLFW;
import org.slf4j.LoggerFactory;
import static dev.aitalkstreamer.mc.core.Json.*;

/** One bridge, journal and arbiter for the existing player's native installation. */
final class NativeBridge {
    private final Minecraft client;
    private final NativeGamePort port;
    private final PhysicalKeys physical;
    private final CursorActivity cursor;
    private final SingleplayerPausePolicy pause = new SingleplayerPausePolicy(() -> System.nanoTime() / 1_000_000);
    private volatile BridgeCore bridge;
    private boolean stopped, hooksReady;
    private JsonObject probeInput;
    NativeBridge(Minecraft client) {
        this.client = client;
        physical = new PhysicalKeys(client.getWindow().getWindow());
        cursor = new CursorActivity(client.getWindow().getWindow(), () -> System.nanoTime() / 1_000_000);
        port = new NativeGamePort(client, physical, () -> {
            BridgeCore current = bridge; return current == null ? null : current.latestObservation();
        });
        NativeHooks.attach(this);
        Thread prepare = new Thread(() -> {
            LocalJournal journal = null;
            try {
                Path root = FMLPaths.CONFIGDIR.get(), config = root.resolve("ai-talk-streamer-bridge.json");
                if (!Files.exists(config)) Files.writeString(config,
                        GSON.toJson(obj("enabled", false, "endpoint", "ws://127.0.0.1:8020/api/dsh/game/bridge")),
                        StandardOpenOption.CREATE_NEW);
                JsonObject settings = JsonParser.parseString(Files.readString(config)).getAsJsonObject();
                require(settings.keySet().equals(Set.of("enabled", "endpoint")) && settings.get("enabled").isJsonPrimitive()
                        && settings.getAsJsonPrimitive("enabled").isBoolean(), "GAME_CONFIG_INVALID");
                if (!settings.get("enabled").getAsBoolean()) return;
                journal = new LocalJournal(root.resolve("ai-talk-streamer-bridge"));
                BridgeCore created = new BridgeCore(port, journal, URI.create(str(settings, "endpoint")));
                synchronized (this) {
                    if (stopped) { created.close(); return; }
                    bridge = created; created.start();
                }
            } catch (Throwable error) {
                if (journal != null) try { journal.close(); } catch (Exception close) { error.addSuppressed(close); }
                LoggerFactory.getLogger("AiTalkStreamerNeoForge").error("Native bridge was not started", error);
            }
        }, "mc-neoforge-bridge-prepare");
        prepare.setDaemon(true); prepare.start();
    }
    void tick(Minecraft client) {
        BridgeCore current = bridge; if (current == null) return;
        try {
            boolean ready = NativeHooks.ready();
            if (ready != hooksReady) { hooksReady = ready; current.capabilitiesChanged(); }
            if (current.control.mode() == ControlArbiter.Mode.AUTO && port.physicallyActive())
                current.takeover(true, "PHYSICAL_HELD_INPUT");
            current.observe(client.level, port.worldKey(), port.sample()); port.tick();
            pause.tick(current.control, current.worldSession(), new SingleplayerPausePolicy.Port() {
                public SingleplayerPausePolicy.Context context() { return port.pauseContext(current.taskIdle()); }
                public boolean preparingAuto() { return current.preparingAuto(); }
                public boolean openPauseMenu(SingleplayerPausePolicy.Context expected) {
                    return port.openPauseMenu(expected, current.taskIdle());
                }
            });
        }
        catch (Throwable failure) {
            current.takeover(false, "GAME_SAMPLE_OR_EXECUTOR_FAILED");
            LoggerFactory.getLogger("AiTalkStreamerNeoForge").error("Native bridge sampling failed", failure);
        }
    }
    void rendered() { port.rendered(); }
    void panic() { BridgeCore current = bridge; if (current != null) current.takeover(false, "LOCAL_PANIC_KEY"); }
    private boolean window(long window) { return client.isSameThread() && window == client.getWindow().getWindow(); }
    void key(long window, int key, int scan, int action) {
        if (!window(window)) return; physical.event(window, key, scan, action);
        BridgeCore current = bridge;
        if (Boolean.getBoolean("ai.talk.streamer.integrationProbe") && action == GLFW.GLFW_PRESS && current != null
                && (current.control.mode() == ControlArbiter.Mode.AUTO || key == GLFW.GLFW_KEY_F10))
            probeInput = obj("kind", "keyboard", "key", key, "scancode", scan, "action", action,
                    "epoch_before", current.control.epoch(), "expected_f10_scancode", GLFW.glfwGetKeyScancode(GLFW.GLFW_KEY_F10));
        if (action == GLFW.GLFW_PRESS && key == GLFW.GLFW_KEY_F10) panic();
        else if (action == GLFW.GLFW_PRESS || action == GLFW.GLFW_REPEAT) manual("PHYSICAL_KEYBOARD_INPUT");
    }
    private void manual(String reason) {
        BridgeCore current = bridge;
        if (current == null) return;
        if (current.preparingAuto()) current.takeover(false, reason);
        pause.physicalActivity(current.control.epoch());
        if (current.control.mode() == ControlArbiter.Mode.AUTO) current.takeover(true, reason);
    }
    void mouse(long window) { if (window(window)) manual("PHYSICAL_MOUSE_INPUT"); }
    void cursor(long window, double x, double y) { if (window(window) && cursor.moved(window, x, y)) mouse(window); }
    void warp(long window, double x, double y) { if (window(window)) cursor.expectWarp(window, x, y); }
    boolean allowVanillaUse() { return port.allowVanillaUse(); }
    boolean allowVanillaAttack() { return port.allowVanillaAttack(); }
    int clickRevision(int revision) { return port.clickRevision(revision); }
    void inventory(net.minecraft.network.protocol.game.ClientboundContainerSetContentPacket packet) { port.inventory(packet); }
    void opened(net.minecraft.network.protocol.game.ClientboundOpenScreenPacket packet) { port.opened(packet); }
    void inventorySlot(net.minecraft.network.protocol.game.ClientboundContainerSetSlotPacket packet) { port.inventorySlot(packet); }
    void health(int food) { port.health(food); }
    void block(net.minecraft.core.BlockPos pos, net.minecraft.world.level.block.state.BlockState state) { port.block(pos, state); }
    boolean authorized() { BridgeCore current = bridge; return current != null && current.control.allowed(); }
    String mode() { BridgeCore current = bridge; return current == null ? "DISABLED" : current.control.mode().name(); }
    JsonObject controlProof() {
        BridgeCore current = bridge; if (current == null) return null;
        JsonObject latest = current.latestObservation();
        return obj("bridge_boot_id", current.boot(), "world_session_id", latest == null ? null : latest.get("world_session_id"),
                "control_epoch", current.control.epoch(), "last_stop", current.diagnostics().get("last_stop"),
                "probe_input", probeInput == null ? null : probeInput.deepCopy(),
                "native_singleplayer_stop", pause.proof(),
                "native_presentation", port.presentationProof(),
                "native_input", port.inputProof(), "native_travel", port.travelProof(), "native_craft", port.craftProof(), "native_cooking", port.cookingProof(), "native_hunting", port.huntingProof(), "native_survival", port.survivalProof(),
                "native_planting", port.plantingProof(), "native_auto_resume", port.resumeProof());
    }
    synchronized void close() {
        stopped = true; BridgeCore current = bridge; bridge = null;
        NativeHooks.detach(this);
        if (current == null) return;
        current.takeover(false, "CLIENT_STOPPING");
        // Flush the initial queued release on the client thread before its loop ends.
        current.control.release(current.control.epoch(), port::releaseInputs);
        Thread close = new Thread(current::close, "mc-neoforge-bridge-stop"); close.start();
    }
}
