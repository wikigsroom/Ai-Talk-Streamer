package dev.aitalkstreamer.mc.survival;

import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.input.Input;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.player.PlayerInventory;
import dev.aitalkstreamer.mc.InputOwner.MovementAxis;
import dev.aitalkstreamer.mc.InputOwner.MovementKey;

/** Routes accepted synthetic inputs into the existing bridge's sole input ledger. */
public final class SurvivalInputs {
    private SurvivalInputs() { }
    private static ArbiterBoundary nativeBoundary() {
        if (!(SurvivalAuthority.boundary() instanceof ArbiterBoundary boundary)) throw new SurvivalAuthority.Denied();
        return boundary;
    }
    public static void key(KeyBinding key, boolean down) { nativeBoundary().key(key, down); }
    public static void click(KeyBinding key) { nativeBoundary().click(key); }
    public static void movement(ClientPlayerEntity player, Input replacement) { nativeBoundary().movement(player, replacement); }
    public static void select(PlayerInventory inventory, int slot) { nativeBoundary().select(inventory, slot); }
    public static void sneaking(Input input, boolean down) { nativeBoundary().sneaking(input, down); }
    public static void motion_movementForward(Input input, float value) { nativeBoundary().movementAxis(input, MovementAxis.FORWARD, value); }
    public static void motion_movementSideways(Input input, float value) { nativeBoundary().movementAxis(input, MovementAxis.SIDEWAYS, value); }
    public static void motion_pressingForward(Input input, boolean value) { nativeBoundary().movementKey(input, MovementKey.FORWARD, value); }
    public static void motion_pressingBack(Input input, boolean value) { nativeBoundary().movementKey(input, MovementKey.BACK, value); }
    public static void motion_pressingLeft(Input input, boolean value) { nativeBoundary().movementKey(input, MovementKey.LEFT, value); }
    public static void motion_pressingRight(Input input, boolean value) { nativeBoundary().movementKey(input, MovementKey.RIGHT, value); }
    public static void motion_jumping(Input input, boolean value) { nativeBoundary().movementKey(input, MovementKey.JUMP, value); }
    public static void motion_sneaking(Input input, boolean value) { nativeBoundary().movementKey(input, MovementKey.SNEAK, value); }
}
