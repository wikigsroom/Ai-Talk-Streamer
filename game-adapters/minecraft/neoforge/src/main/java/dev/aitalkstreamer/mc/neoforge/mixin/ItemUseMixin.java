package dev.aitalkstreamer.mc.neoforge.mixin;
import dev.aitalkstreamer.mc.neoforge.NativeHooks;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
@Mixin(value = Minecraft.class, remap = false)
public abstract class ItemUseMixin {
    @Inject(method = "<init>", at = @At("RETURN"))
    private void installed(CallbackInfo callback) { NativeHooks.applied("use_repeat"); NativeHooks.applied("block_repeat"); }
    @Inject(method = "startUseItem", at = @At("HEAD"), cancellable = true)
    private void once(CallbackInfo callback) { if (!NativeHooks.allowVanillaUse()) callback.cancel(); }
    @Inject(method = "continueAttack", at = @At("HEAD"), cancellable = true)
    private void heldAttack(boolean down, CallbackInfo callback) { if (!NativeHooks.allowVanillaAttack()) callback.cancel(); }
    @Inject(method = "startAttack", at = @At("HEAD"), cancellable = true)
    private void attack(CallbackInfoReturnable<Boolean> callback) { if (!NativeHooks.allowVanillaAttack()) callback.setReturnValue(false); }
}
