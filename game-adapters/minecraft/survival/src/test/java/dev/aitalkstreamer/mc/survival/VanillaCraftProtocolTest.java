package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import org.objectweb.asm.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Checks assumptions against the pinned, actual Minecraft classes without initializing the game. */
class VanillaCraftProtocolTest {
    private void read(String name, ClassVisitor visitor) throws Exception {
        try (var stream = getClass().getResourceAsStream("/net/minecraft/" + name + ".class")) {
            assertNotNull(stream); new ClassReader(stream).accept(visitor, ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
        }
    }
    @Test void actualVanillaClickPreservesThePacketConstructorHookAndFullSyncOnRevisionMismatch() throws Exception {
        List<String> client = new ArrayList<>(), server = new ArrayList<>();
        read("client/network/ClientPlayerInteractionManager", new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int access, String name, String desc, String sig, String[] exceptions) {
                if (!name.equals("clickSlot")) return null;
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override public void visitMethodInsn(int op, String owner, String name, String descriptor, boolean itf) { client.add(owner + ":" + name + descriptor); }
                };
            }
        });
        String constructor = "network/packet/c2s/play/ClickSlotC2SPacket:<init>(IIIILnet/minecraft/screen/slot/SlotActionType;Lnet/minecraft/item/ItemStack;Lit/unimi/dsi/fastutil/ints/Int2ObjectMap;)V";
        assertEquals(1, client.stream().filter(s -> s.equals("net/minecraft/" + constructor)).count());
        read("server/network/ServerPlayNetworkHandler", new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int access, String name, String desc, String sig, String[] exceptions) {
                if (!name.equals("onClickSlot")) return null;
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override public void visitMethodInsn(int op, String owner, String name, String descriptor, boolean itf) { server.add(owner + ":" + name); }
                    @Override public void visitJumpInsn(int op, Label label) { if (op == Opcodes.IF_ICMPEQ) server.add("REVISION_COMPARE"); }
                };
            }
        });
        int revisionRead = server.indexOf("net/minecraft/network/packet/c2s/play/ClickSlotC2SPacket:getRevision");
        int compared = java.util.stream.IntStream.range(revisionRead + 1, server.size())
                .filter(i -> server.get(i).equals("REVISION_COMPARE")).findFirst().orElse(-1);
        int applied = server.indexOf("net/minecraft/screen/ScreenHandler:onSlotClick"),
                full = server.indexOf("net/minecraft/screen/ScreenHandler:updateToClient");
        assertTrue(revisionRead >= 0 && compared > revisionRead);
        assertTrue(applied > compared && full > applied);
        assertTrue(server.indexOf("net/minecraft/screen/ScreenHandler:sendContentUpdates") > full);
    }
    @Test void actualHandlerRevisionIsNonnegativeAndInventoryPacketHasCompleteCursorAndSlotAccessors() throws Exception {
        List<Integer> constants = new ArrayList<>(); boolean[] mask = {false};
        read("screen/ScreenHandler", new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int access, String name, String desc, String sig, String[] exceptions) {
                if (!name.equals("nextRevision")) return null;
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override public void visitLdcInsn(Object value) { if (value instanceof Integer number) constants.add(number); }
                    @Override public void visitIntInsn(int op, int value) { constants.add(value); }
                    @Override public void visitInsn(int op) { if (op == Opcodes.IAND) mask[0] = true; }
                };
            }
        });
        assertTrue(mask[0]); assertTrue(constants.contains(32767));
        Set<String> methods = new HashSet<>();
        read("network/packet/s2c/play/InventoryS2CPacket", new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int access, String name, String desc, String sig, String[] exceptions) { methods.add(name + desc); return null; }
        });
        assertTrue(methods.containsAll(Set.of("getContents()Ljava/util/List;", "getCursorStack()Lnet/minecraft/item/ItemStack;", "getRevision()I", "getSyncId()I")));
    }
}
