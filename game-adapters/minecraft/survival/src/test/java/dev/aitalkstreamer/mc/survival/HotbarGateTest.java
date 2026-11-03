package dev.aitalkstreamer.mc.survival;

import com.google.gson.*;
import dev.aitalkstreamer.mc.survival.audit.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.*;
import java.nio.file.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Actual compiled API and transformed fixed game symbols; no Minecraft initialization. */
class HotbarGateTest {
    private static final String INVENTORY = "net/minecraft/entity/player/PlayerInventory";
    private static final String INPUTS = "dev/aitalkstreamer/mc/survival/SurvivalInputs";
    @TempDir Path temporary;
    private GatePolicy.Rule selected(GatePolicy policy, String owner, String field) {
        var rule = policy.match("FIELD",owner,field,"I"); assertNotNull(rule); assertEquals("select",rule.relay()); return rule;
    }
    private byte[] fixture(GatePolicy.Rule rule, int opcode) {
        var writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        writer.visit(Opcodes.V21,Opcodes.ACC_PUBLIC,"fixture/HotbarWriter",null,"java/lang/Object",null);
        var args = opcode == Opcodes.PUTFIELD ? new Type[]{Type.getObjectType(rule.owner()),Type.INT_TYPE} : new Type[]{Type.INT_TYPE};
        var method = new GeneratorAdapter(Opcodes.ACC_PUBLIC|Opcodes.ACC_STATIC,new Method("run",Type.VOID_TYPE,args),null,null,writer);
        method.loadArgs(); method.visitFieldInsn(opcode,rule.owner(),rule.name(),rule.descriptor());
        method.returnValue(); method.endMethod(); writer.visitEnd(); return writer.toByteArray();
    }
    private void checkTransform(GatePolicy policy, GatePolicy.Rule rule) {
        var transformed = BytecodeGate.transform(fixture(rule,Opcodes.PUTFIELD),policy);
        assertEquals(1,transformed.sites().size()); assertEquals("select",transformed.sites().getFirst().route());
        List<String> calls = new ArrayList<>(); var rawWrites = new ArrayList<String>();
        new ClassReader(transformed.bytes()).accept(new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int access,String name,String descriptor,String signature,String[] exceptions) {
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override public void visitMethodInsn(int opcode,String owner,String name,String desc,boolean itf) { calls.add(owner+":"+name+desc); }
                    @Override public void visitFieldInsn(int opcode,String owner,String name,String desc) {
                        if (opcode==Opcodes.PUTFIELD || opcode==Opcodes.PUTSTATIC) rawWrites.add(owner+":"+name+desc);
                    }
                };
            }
        },0);
        assertTrue(rawWrites.isEmpty()); assertTrue(calls.contains(INPUTS+":select(L"+rule.owner()+";I)V"));
    }
    @Test void namedFieldWriteUsesTheSoleNativeSelectionSink() throws Exception {
        var policy = GatePolicy.read(Path.of("gate-policy.json")); checkTransform(policy,selected(policy,INVENTORY,"selectedSlot"));
    }
    @Test void intermediaryFieldWriteUsesTheSameMappedReceiverAndSink() throws Exception {
        var mapping = Path.of("../../../.setup/mc-gradle/caches/fabric-loom/1.21.1/net.fabricmc.yarn.1_21_1.1.21.1+build.3-v2/mappings-base.tiny");
        var policy = GatePolicy.read(Path.of("gate-policy.json")).intermediary(mapping);
        checkTransform(policy,selected(policy,"net/minecraft/class_1661","field_7545"));
    }
    private Set<String> methods(String name) throws Exception {
        var methods = new HashSet<String>();
        try (var stream = getClass().getResourceAsStream('/'+name+".class")) {
            assertNotNull(stream); new ClassReader(stream).accept(new ClassVisitor(Opcodes.ASM9) {
                @Override public MethodVisitor visitMethod(int access,String name,String desc,String sig,String[] exceptions) { methods.add(name+desc); return null; }
            },ClassReader.SKIP_CODE|ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);
        }
        return methods;
    }
    @Test void actualBridgeScopeBoundaryAndServerPacketHaveMatchingCompiledSignatures() throws Exception {
        String args = "(L"+INVENTORY+";ILdev/aitalkstreamer/mc/core/ControlArbiter;Ldev/aitalkstreamer/mc/core/ControlArbiter$Permit;)V";
        assertTrue(methods(INPUTS).contains("select(L"+INVENTORY+";I)V"));
        assertTrue(methods("dev/aitalkstreamer/mc/survival/ArbiterBoundary").contains("select(L"+INVENTORY+";I)V"));
        assertTrue(methods("dev/aitalkstreamer/mc/InputOwner$Scope").contains("select"+args));
        assertTrue(methods("dev/aitalkstreamer/mc/InputOwner").contains("select"+args));
        assertTrue(methods("net/minecraft/network/packet/c2s/play/UpdateSelectedSlotC2SPacket").contains("<init>(I)V"));
    }
    @Test void selectionRelayCannotBeAssignedToADifferentKindOwnerFieldOrDescriptor() throws Exception {
        for (String[] change : List.of(new String[]{"kind","CALL"},new String[]{"owner","net/minecraft/Other"},
                new String[]{"name","otherField"},new String[]{"descriptor","J"},new String[]{"declaration","net/minecraft/Other"})) {
            var json = JsonParser.parseString(Files.readString(Path.of("gate-policy.json"))).getAsJsonObject();
            for (var value : json.getAsJsonArray("rules")) {
                var row = value.getAsJsonObject(); if (row.has("relay") && row.get("relay").getAsString().equals("select")) row.addProperty(change[0],change[1]);
            }
            var path = temporary.resolve("invalid.json"); Files.writeString(path,json.toString());
            assertEquals("GAME_GATE_HOTBAR_SIGNATURE",assertThrows(IllegalArgumentException.class,()->GatePolicy.read(path)).getMessage());
        }
    }
    @Test void staticFieldCannotBeForwardedAsAnInstanceInventoryWrite() throws Exception {
        var policy = GatePolicy.read(Path.of("gate-policy.json")); var rule = selected(policy,INVENTORY,"selectedSlot");
        assertEquals("GAME_GATE_HOTBAR_SIGNATURE",assertThrows(IllegalArgumentException.class,()->BytecodeGate.transform(fixture(rule,Opcodes.PUTSTATIC),policy)).getMessage());
    }
    private byte[] handleFixture(boolean dynamic,int tag) {
        var writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        writer.visit(Opcodes.V21,Opcodes.ACC_PUBLIC,"fixture/HotbarHandle",null,"java/lang/Object",null);
        var method = new GeneratorAdapter(Opcodes.ACC_PUBLIC|Opcodes.ACC_STATIC,new Method("run","()V"),null,null,writer);
        var handle = new Handle(tag,INVENTORY,"selectedSlot","I",false);
        if (dynamic) method.visitInvokeDynamicInsn("run","()Ljava/lang/Runnable;",
                new Handle(Opcodes.H_INVOKESTATIC,"java/lang/invoke/LambdaMetafactory","metafactory",
                    "(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodHandle;Ljava/lang/invoke/MethodType;)Ljava/lang/invoke/CallSite;",false),
                Type.getMethodType("()V"),handle,Type.getMethodType("()V"));
        else method.visitLdcInsn(handle);
        method.pop(); method.returnValue(); method.endMethod(); writer.visitEnd(); return writer.toByteArray();
    }
    @Test void constantSetterHandleCannotBypassTheSelectedFieldRoute() throws Exception {
        var policy = GatePolicy.read(Path.of("gate-policy.json"));
        assertTrue(assertThrows(IllegalArgumentException.class,()->BytecodeGate.transform(handleFixture(false,Opcodes.H_PUTFIELD),policy)).getMessage().startsWith("GAME_GATE_DIRECT_FIELD_REFERENCE"));
        assertDoesNotThrow(()->BytecodeGate.transform(handleFixture(false,Opcodes.H_GETFIELD),policy));
    }
    @Test void dynamicSetterReferenceCannotBypassTheSelectedFieldRoute() throws Exception {
        var policy = GatePolicy.read(Path.of("gate-policy.json"));
        assertTrue(assertThrows(IllegalArgumentException.class,()->BytecodeGate.transform(handleFixture(true,Opcodes.H_PUTFIELD),policy)).getMessage().startsWith("GAME_GATE_DIRECT_FIELD_REFERENCE"));
    }
}
