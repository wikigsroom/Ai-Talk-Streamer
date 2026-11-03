package dev.aitalkstreamer.mc.mixin;

import net.minecraft.client.MinecraftClient;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Invoker;

/** Direct single-click actions avoid adding synthetic counts to the physical key event queue. */
@Mixin(MinecraftClient.class)
public interface MinecraftInputInvoker {
    @Invoker("doAttack") boolean mcBridgeAttack();
    @Invoker("doItemUse") void mcBridgeUse();
}
