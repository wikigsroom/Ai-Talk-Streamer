package dev.aitalkstreamer.mc.mixin;

import dev.aitalkstreamer.mc.McBridgeClient;
import net.minecraft.client.network.ClientPlayNetworkHandler;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPlayNetworkHandler.class)
public abstract class InventorySyncMixin {
    @Inject(method = "onInventory", at = @At("RETURN"))
    private void mcBridgeInventorySync(InventoryS2CPacket packet, CallbackInfo callback) {
        McBridgeClient.inventorySynchronized(packet);
    }
    @Inject(method = "onScreenHandlerSlotUpdate", at = @At("RETURN"))
    private void mcBridgeSlotSync(net.minecraft.network.packet.s2c.play.ScreenHandlerSlotUpdateS2CPacket packet, CallbackInfo callback) {
        McBridgeClient.inventorySlotSynchronized(packet);
    }
}
