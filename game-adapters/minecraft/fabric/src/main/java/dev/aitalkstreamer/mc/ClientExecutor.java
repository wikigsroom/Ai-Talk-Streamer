package dev.aitalkstreamer.mc;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.ControlArbiter;
import dev.aitalkstreamer.mc.core.BaseTarget;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import java.util.List;
import java.util.function.Consumer;

/** Typed extension of the same player's port, never a second controller or player. */
public interface ClientExecutor {
    String ENTRYPOINT = "ai_talk_streamer_executor";
    String profile();
    List<String> skills();
    JsonObject check(JsonObject goal, BaseTarget base);
    void start(JsonObject task, JsonObject observation, ControlArbiter control, InputOwner inputs,
               Consumer<JsonObject> completed);
    void tick(JsonObject observation);
    /** A synchronous vanilla continuation must retain this accepted root's original permit. */
    default void nativeInput(dev.aitalkstreamer.mc.core.HeldActionRouter.Action action, Runnable effect) {
        throw new IllegalStateException("GAME_NATIVE_INPUT_NOT_BOUND");
    }
    default boolean allowsGui(JsonObject acceptedTask) { return false; }
    /** Called inside the original per-write permit before a synthetic use-key click. */
    default boolean beforeUse() { return true; }
    /** Internal use transactions issue their own one use and suppress vanilla held repeats. */
    default boolean ownsUseTransaction() { return false; }
    default void itemHealth(int food) { }
    /** Only a dedicated task-owned transaction may request a server full-state resynchronization. */
    default int clickRevision(int revision) { return revision; }
    /** Delivered on the client thread after vanilla applies the authoritative packet. No write scope. */
    default void inventorySynchronized(InventoryS2CPacket packet) { }
    default void inventorySlotSynchronized(net.minecraft.network.packet.s2c.play.ScreenHandlerSlotUpdateS2CPacket packet) { }
    void cancel(String reason);
}
