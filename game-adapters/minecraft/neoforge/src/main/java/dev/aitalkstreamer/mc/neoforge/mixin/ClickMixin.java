package dev.aitalkstreamer.mc.neoforge.mixin;
import dev.aitalkstreamer.mc.neoforge.NativeHooks;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(value = MultiPlayerGameMode.class, remap = false)
public abstract class ClickMixin {
    @Inject(method = "<init>", at = @At("RETURN"))
    private void installed(CallbackInfo callback) { NativeHooks.applied("click_revision"); }
    @ModifyArg(method = "handleInventoryMouseClick", at = @At(value = "INVOKE", target = "Lnet/minecraft/network/protocol/game/ServerboundContainerClickPacket;<init>(IIIILnet/minecraft/world/inventory/ClickType;Lnet/minecraft/world/item/ItemStack;Lit/unimi/dsi/fastutil/ints/Int2ObjectMap;)V"), index = 1)
    private int revision(int revision) { return NativeHooks.clickRevision(revision); }
}
