package dev.aitalkstreamer.mc.survival;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayNetworkHandler;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.player.PlayerAbilities;
import net.minecraft.world.World;
import static dev.aitalkstreamer.mc.core.Json.require;

/** Fixed survival tasks cannot issue arbitrary server commands or change the player's lifecycle. */
public final class SurvivalPolicy {
    private SurvivalPolicy() { }
    private static void unsupported() {
        SurvivalAuthority.write(() -> { throw new IllegalStateException("GAME_TASK_UNSUPPORTED"); });
    }
    public static void chatCommand(ClientPlayNetworkHandler ignored, String command) { unsupported(); }
    public static void chatMessage(ClientPlayNetworkHandler ignored, String message) { unsupported(); }
    public static void respawn(ClientPlayerEntity ignored) { unsupported(); }
    public static void disconnect(World ignored) { unsupported(); }
    public static boolean fallFlying(ClientPlayerEntity ignored) { unsupported(); return false; }
    /** Ground navigation may confirm the default value; it never toggles player flight capabilities. */
    public static void grounded(PlayerAbilities abilities, boolean requested) {
        SurvivalAuthority.write(() -> {
            MinecraftClient client = MinecraftClient.getInstance();
            require(client.isOnThread(), "GAME_WRONG_THREAD");
            require(client.player != null && client.player.isAlive() && client.world != null
                    && client.getNetworkHandler() != null && client.interactionManager != null,
                    "GAME_WORLD_UNAVAILABLE");
            require(client.isWindowFocused() && !client.isPaused(), "GAME_GUI_BLOCKED");
            require(abilities != null && abilities == client.player.getAbilities(), "GAME_ACTION_PLAYER_CHANGED");
            require(!requested && !abilities.flying, "GAME_TASK_UNSUPPORTED");
        });
    }
}
