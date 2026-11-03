package dev.aitalkstreamer.mc.survival;

import java.util.*;
import org.junit.jupiter.api.Test;
import org.objectweb.asm.*;
import static org.junit.jupiter.api.Assertions.*;

/** Reads the actual pinned game and native dev JAR without initializing Minecraft. */
class VanillaItemUseProtocolTest {
    Set<String> methods(String name) throws Exception {
        Set<String> methods = new HashSet<>();
        try (var stream = getClass().getResourceAsStream('/' + name + ".class")) {
            assertNotNull(stream); new ClassReader(stream).accept(new ClassVisitor(Opcodes.ASM9) {
                @Override public MethodVisitor visitMethod(int access, String name, String desc, String sig, String[] exceptions) {
                    methods.add(name + desc); return null;
                }
            }, ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
        }
        return methods;
    }
    @Test void actualHandlerHasAllItemEffectPacketHooksAndTheSingleUseEntry() throws Exception {
        var handler = methods("net/minecraft/client/network/ClientPlayNetworkHandler");
        for (String pair : List.of("onHealthUpdate:HealthUpdateS2CPacket", "onBlockUpdate:BlockUpdateS2CPacket", "onChunkDeltaUpdate:ChunkDeltaUpdateS2CPacket")) {
            String[] parts = pair.split(":"); assertTrue(handler.contains(parts[0] + "(Lnet/minecraft/network/packet/s2c/play/" + parts[1] + ";)V"));
        }
        assertTrue(methods("net/minecraft/client/MinecraftClient").contains("doItemUse()V"));
    }
    @Test void actualPacketsExposeAuthoritativeFoodAndBothBlockUpdateForms() throws Exception {
        assertTrue(methods("net/minecraft/network/packet/s2c/play/HealthUpdateS2CPacket").contains("getFood()I"));
        assertTrue(methods("net/minecraft/network/packet/s2c/play/BlockUpdateS2CPacket").containsAll(Set.of(
                "getPos()Lnet/minecraft/util/math/BlockPos;", "getState()Lnet/minecraft/block/BlockState;")));
        assertTrue(methods("net/minecraft/network/packet/s2c/play/ChunkDeltaUpdateS2CPacket").contains("visitUpdates(Ljava/util/function/BiConsumer;)V"));
    }
    @Test void nativePortAndDriverCarryTheNewReceiptAndPacketPathsInTheBuiltApi() throws Exception {
        assertTrue(methods("dev/aitalkstreamer/mc/NativeItemUse").containsAll(Set.of(
                "itemUseReceipt()Ldev/aitalkstreamer/mc/core/ItemUseReceipt;", "clickRevision(I)I", "cancel()V")));
        assertTrue(methods("dev/aitalkstreamer/mc/MinecraftPort").contains("allowVanillaUse()Z"));
        assertTrue(methods("dev/aitalkstreamer/mc/core/ExecutorTaskSession$Runtime").contains("itemUseReceipt()Ldev/aitalkstreamer/mc/core/ItemUseReceipt;"));
    }
}
