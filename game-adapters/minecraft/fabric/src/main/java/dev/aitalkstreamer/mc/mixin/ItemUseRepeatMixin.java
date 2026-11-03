package dev.aitalkstreamer.mc.mixin;

import dev.aitalkstreamer.mc.McBridgeClient;
import net.minecraft.client.MinecraftClient;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(MinecraftClient.class)
public abstract class ItemUseRepeatMixin {
    @Inject(method = "doItemUse", at = @At("HEAD"), cancellable = true)
    private void mcBridgeSingleItemUse(CallbackInfo callback) { if (!McBridgeClient.allowVanillaUse()) callback.cancel(); }
}
