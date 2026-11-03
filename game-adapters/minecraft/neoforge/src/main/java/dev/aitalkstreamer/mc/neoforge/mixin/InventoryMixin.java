package dev.aitalkstreamer.mc.neoforge.mixin;
import dev.aitalkstreamer.mc.neoforge.NativeHooks;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.*;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.*;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(value = ClientPacketListener.class, remap = false)
public abstract class InventoryMixin {
    @Inject(method = "<init>", at = @At("RETURN"))
    private void installed(CallbackInfo callback) { NativeHooks.applied("inventory"); NativeHooks.applied("craft_menu"); }
    @Inject(method = "handleOpenScreen", at = @At("RETURN"))
    private void opened(ClientboundOpenScreenPacket packet, CallbackInfo callback) { NativeHooks.opened(packet); }
    @Inject(method = "handleContainerContent", at = @At("RETURN"))
    private void inventory(ClientboundContainerSetContentPacket packet, CallbackInfo callback) { NativeHooks.inventory(packet); }
    @Inject(method = "handleContainerSetSlot", at = @At("RETURN"))
    private void inventorySlot(ClientboundContainerSetSlotPacket packet, CallbackInfo callback) { NativeHooks.inventorySlot(packet); }
    @Inject(method = "handleSetHealth", at = @At("RETURN"))
    private void health(ClientboundSetHealthPacket packet, CallbackInfo callback) { NativeHooks.health(packet.getFood()); }
    @Inject(method = "handleBlockUpdate", at = @At("RETURN"))
    private void block(ClientboundBlockUpdatePacket packet, CallbackInfo callback) { NativeHooks.block(packet.getPos(), packet.getBlockState()); }
    @Inject(method = "handleChunkBlocksUpdate", at = @At("RETURN"))
    private void blocks(ClientboundSectionBlocksUpdatePacket packet, CallbackInfo callback) { packet.runUpdates(NativeHooks::block); }
}
