package dev.aitalkstreamer.mc.mixin;

import dev.aitalkstreamer.mc.McBridgeClient;
import net.minecraft.client.network.ClientPlayerInteractionManager;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.ModifyArg;

@Mixin(ClientPlayerInteractionManager.class)
public abstract class CraftClickMixin {
    @ModifyArg(method = "clickSlot", at = @At(value = "INVOKE", target = "Lnet/minecraft/network/packet/c2s/play/ClickSlotC2SPacket;<init>(IIIILnet/minecraft/screen/slot/SlotActionType;Lnet/minecraft/item/ItemStack;Lit/unimi/dsi/fastutil/ints/Int2ObjectMap;)V"), index = 1)
    private int mcBridgeCraftRevision(int revision) { return McBridgeClient.clickRevision(revision); }
}
