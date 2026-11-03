package dev.aitalkstreamer.mc.neoforge.mixin;
import dev.aitalkstreamer.mc.neoforge.NativeHooks;
import net.minecraft.client.MouseHandler;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(value = MouseHandler.class, remap = false)
public abstract class MouseMixin {
    @Inject(method = "<init>", at = @At("RETURN"))
    private void installed(CallbackInfo callback) { NativeHooks.applied("mouse"); }
    @Inject(method = "onPress", at = @At("HEAD"))
    private void button(long window, int button, int action, int mods, CallbackInfo callback) { NativeHooks.button(window, action); }
    @Inject(method = "onScroll", at = @At("HEAD"))
    private void scroll(long window, double x, double y, CallbackInfo callback) { NativeHooks.scroll(window, x, y); }
    @Inject(method = "onMove", at = @At("HEAD"))
    private void cursor(long window, double x, double y, CallbackInfo callback) { NativeHooks.cursor(window, x, y); }
}
