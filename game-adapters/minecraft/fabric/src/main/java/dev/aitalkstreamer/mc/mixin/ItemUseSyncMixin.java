package dev.aitalkstreamer.mc.mixin;

import dev.aitalkstreamer.mc.McBridgeClient;
import net.minecraft.client.network.ClientPlayNetworkHandler;
import net.minecraft.network.packet.s2c.play.*;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPlayNetworkHandler.class)
public abstract class ItemUseSyncMixin {
    @Inject(method = "onHealthUpdate", at = @At("RETURN"))
    private void mcBridgeItemHealth(HealthUpdateS2CPacket packet, CallbackInfo callback) { McBridgeClient.itemHealth(packet.getFood()); }
    @Inject(method = "onBlockUpdate", at = @At("RETURN"))
    private void mcBridgeItemBlock(BlockUpdateS2CPacket packet, CallbackInfo callback) { McBridgeClient.itemBlock(packet.getPos(), packet.getState()); }
    @Inject(method = "onChunkDeltaUpdate", at = @At("RETURN"))
    private void mcBridgeItemChunk(ChunkDeltaUpdateS2CPacket packet, CallbackInfo callback) { packet.visitUpdates(McBridgeClient::itemBlock); }
}
