package dev.aitalkstreamer.mc.mixin;

import dev.aitalkstreamer.mc.McBridgeClient;
import net.minecraft.client.util.InputUtil;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(InputUtil.class)
public abstract class InputUtilMixin {
    @Inject(method = "setCursorParameters", at = @At("HEAD"))
    private static void mcBridgeWarp(long window, int mode, double x, double y, CallbackInfo info) {
        McBridgeClient.expectCursorWarp(window, x, y);
    }
}
