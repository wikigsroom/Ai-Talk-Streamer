package dev.aitalkstreamer.mc.mixin;

import com.llamalad7.mixinextras.injector.wrapmethod.WrapMethod;
import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import dev.aitalkstreamer.mc.McBridgeClient;
import dev.aitalkstreamer.mc.core.HeldActionRouter.Action;
import net.minecraft.client.MinecraftClient;
import org.spongepowered.asm.mixin.Mixin;

/** Wrap the full vanilla continuation, including its internal client/network effects. */
@Mixin(MinecraftClient.class)
public abstract class HeldInputMixin {
    @WrapMethod(method="doAttack")
    private boolean mcBridgeHeldAttack(Operation<Boolean> original) {
        return McBridgeClient.nativeInput(Action.ATTACK,()->original.call(),false);
    }
    @WrapMethod(method="handleBlockBreaking")
    private void mcBridgeHeldBreaking(boolean breaking, Operation<Void> original) {
        McBridgeClient.nativeInput(Action.BREAK,()->{ original.call(breaking);return null; },null);
    }
    @WrapMethod(method="doItemUse")
    private void mcBridgeHeldUse(Operation<Void> original) {
        McBridgeClient.nativeInput(Action.USE,()->{ original.call();return null; },null);
    }
}
