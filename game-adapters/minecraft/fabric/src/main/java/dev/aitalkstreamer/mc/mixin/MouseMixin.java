package dev.aitalkstreamer.mc.mixin;
import dev.aitalkstreamer.mc.McBridgeClient;
import net.minecraft.client.Mouse;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(Mouse.class)
public abstract class MouseMixin {
    @Inject(method = "onMouseButton", at = @At("HEAD"))
    private void mcBridgeButton(long window, int button, int action, int mods, CallbackInfo info) { McBridgeClient.button(window, button, action); }
    @Inject(method = "onMouseScroll", at = @At("HEAD"))
    private void mcBridgeScroll(long window, double x, double y, CallbackInfo info) { if (x != 0 || y != 0) McBridgeClient.mouse(window); }
    @Inject(method = "onCursorPos", at = @At("HEAD"))
    private void mcBridgeCursor(long window, double x, double y, CallbackInfo info) {
        McBridgeClient.cursor(window, x, y);
    }
}
