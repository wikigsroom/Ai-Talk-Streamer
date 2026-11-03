package dev.aitalkstreamer.mc.neoforge;

import net.minecraft.core.BlockPos;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.network.protocol.game.ClientboundContainerSetContentPacket;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** Records actual transformed client lifecycles before advertising an input capability. */
public final class NativeHooks {
    private static final Set<String> REQUIRED = Set.of("keyboard", "mouse", "cursor_warp", "use_repeat", "block_repeat", "inventory", "click_revision", "craft_menu");
    private static final Set<String> applied = ConcurrentHashMap.newKeySet();
    private static volatile NativeBridge active;
    private NativeHooks() { }
    public static void applied(String hook) { if (REQUIRED.contains(hook)) applied.add(hook); }
    public static boolean ready() { return applied.containsAll(REQUIRED); }
    public static List<String> missing() { return REQUIRED.stream().filter(value -> !applied.contains(value)).sorted().toList(); }
    static void attach(NativeBridge bridge) { active = bridge; }
    static void detach(NativeBridge bridge) { if (active == bridge) active = null; }
    public static void key(long window, int key, int scan, int action) {
        NativeBridge bridge = active; if (bridge != null) bridge.key(window, key, scan, action);
    }
    public static void button(long window, int action) {
        NativeBridge bridge = active; if (bridge != null && action == 1) bridge.mouse(window);
    }
    public static void scroll(long window, double x, double y) {
        NativeBridge bridge = active; if (bridge != null && (x != 0 || y != 0)) bridge.mouse(window);
    }
    public static void cursor(long window, double x, double y) {
        NativeBridge bridge = active; if (bridge != null) bridge.cursor(window, x, y);
    }
    public static void warp(long window, double x, double y) {
        NativeBridge bridge = active; if (bridge != null) bridge.warp(window, x, y);
    }
    public static boolean allowVanillaUse() {
        NativeBridge bridge = active; return bridge == null || bridge.allowVanillaUse();
    }
    public static boolean allowVanillaAttack() {
        NativeBridge bridge = active; return bridge == null || bridge.allowVanillaAttack();
    }
    public static int clickRevision(int revision) {
        NativeBridge bridge = active; return bridge == null ? revision : bridge.clickRevision(revision);
    }
    public static void inventory(ClientboundContainerSetContentPacket packet) {
        NativeBridge bridge = active; if (bridge != null) bridge.inventory(packet);
    }
    public static void opened(net.minecraft.network.protocol.game.ClientboundOpenScreenPacket packet) {
        NativeBridge bridge = active; if (bridge != null) bridge.opened(packet);
    }
    public static void inventorySlot(net.minecraft.network.protocol.game.ClientboundContainerSetSlotPacket packet) {
        NativeBridge bridge = active; if (bridge != null) bridge.inventorySlot(packet);
    }
    public static void health(int food) { NativeBridge bridge = active; if (bridge != null) bridge.health(food); }
    public static void block(BlockPos pos, BlockState state) {
        NativeBridge bridge = active; if (bridge != null) bridge.block(pos, state);
    }
}
