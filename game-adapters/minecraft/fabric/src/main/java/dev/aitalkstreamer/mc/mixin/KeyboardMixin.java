package dev.aitalkstreamer.mc.mixin;
import dev.aitalkstreamer.mc.McBridgeClient;
import net.minecraft.client.Keyboard;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(Keyboard.class)
public abstract class KeyboardMixin {
    @Inject(method = "onKey", at = @At("HEAD"))
    private void mcBridgePhysicalKey(long window, int key, int scancode, int action, int modifiers, CallbackInfo info) { McBridgeClient.key(window, key, scancode, action); }
}
