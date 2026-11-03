package dev.aitalkstreamer.mc.neoforge.mixin;
import com.mojang.blaze3d.platform.InputConstants;
import dev.aitalkstreamer.mc.neoforge.NativeHooks;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(value = InputConstants.class, remap = false)
public abstract class CursorWarpMixin {
    // Binding is established when the transformed class initializes. A cold
    // death-screen reload may never grab the cursor before Agent respawn.
    @Inject(method = "<clinit>", at = @At("RETURN"))
    private static void installed(CallbackInfo callback) { NativeHooks.applied("cursor_warp"); }
    @Inject(method = "grabOrReleaseMouse", at = @At("HEAD"))
    private static void warp(long window, int mode, double x, double y, CallbackInfo callback) { NativeHooks.warp(window, x, y); }
}
