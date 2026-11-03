package dev.aitalkstreamer.mc.neoforge.mixin;
import dev.aitalkstreamer.mc.neoforge.NativeHooks;
import net.minecraft.client.KeyboardHandler;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(value = KeyboardHandler.class, remap = false)
public abstract class KeyboardMixin {
    @Inject(method = "<init>", at = @At("RETURN"))
    private void installed(CallbackInfo callback) { NativeHooks.applied("keyboard"); }
    @Inject(method = "keyPress", at = @At("HEAD"))
    private void physical(long window, int key, int scan, int action, int modifiers, CallbackInfo callback) {
        NativeHooks.key(window, key, scan, action);
    }
}
