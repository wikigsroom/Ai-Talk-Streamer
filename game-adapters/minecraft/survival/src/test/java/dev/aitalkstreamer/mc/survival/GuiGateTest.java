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

/** Verifies generated typed call sites against the compiled sink API without starting Minecraft. */
class GuiGateTest {
    @TempDir Path temporary;
    private List<GatePolicy.Rule> rules() throws Exception {
        var policy = GatePolicy.read(Path.of("gate-policy.json"));
        List<GatePolicy.Rule> rules = new ArrayList<>();
        for (var element : JsonParser.parseString(Files.readString(Path.of("gate-policy.json"))).getAsJsonObject().getAsJsonArray("rules")) {
            var row = element.getAsJsonObject(); if (!row.has("relay") || !row.get("relay").getAsString().startsWith("gui_")) continue;
            rules.add(policy.match("CALL", row.get("owner").getAsString(), row.get("name").getAsString(), row.get("descriptor").getAsString()));
        }
        assertEquals(5, rules.size()); return rules;
    }
    private Type[] args(GatePolicy.Rule rule) {
        List<Type> args = new ArrayList<>(); args.add(Type.getObjectType(rule.owner())); args.addAll(List.of(Type.getArgumentTypes(rule.descriptor())));
        return args.toArray(Type[]::new);
    }
    @Test void eachNamedRouteMatchesAnActualCompiledSinkSignature() throws Exception {
        Set<String> methods = new HashSet<>();
        try (var input = getClass().getResourceAsStream("/dev/aitalkstreamer/mc/survival/SurvivalGui.class")) {
            assertNotNull(input); new ClassReader(input).accept(new ClassVisitor(Opcodes.ASM9) {
                @Override public MethodVisitor visitMethod(int access, String name, String desc, String signature, String[] exceptions) {
                    if ((access & Opcodes.ACC_PUBLIC) != 0 && (access & Opcodes.ACC_STATIC) != 0) methods.add(name + desc); return null;
                }
            }, ClassReader.SKIP_CODE | ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
        }
        for (var rule : rules()) assertTrue(methods.contains(rule.relay().substring(4) + Type.getMethodDescriptor(Type.getReturnType(rule.descriptor()), args(rule))), rule.relay());
    }
    @Test void actualTransformPreservesGuiArgumentsAndResultsAndRemovesTheUnguardedCall() throws Exception {
        for (var rule : rules()) {
            Type result = Type.getReturnType(rule.descriptor()); String desc = Type.getMethodDescriptor(result, args(rule));
            ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
            writer.visit(Opcodes.V21, Opcodes.ACC_PUBLIC, "fixture/GuiRoute", null, "java/lang/Object", null);
            var method = new GeneratorAdapter(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC, new Method("run", desc), null, null, writer);
            method.loadArgs(); method.visitMethodInsn(Opcodes.INVOKEVIRTUAL, rule.owner(), rule.name(), rule.descriptor(), false);
            method.returnValue(); method.endMethod(); writer.visitEnd();
            var transformed = BytecodeGate.transform(writer.toByteArray(), new GatePolicy(List.of(rule)));
            assertEquals(1, transformed.sites().size()); assertEquals(rule.relay(), transformed.sites().getFirst().route());
            List<String> calls = new ArrayList<>();
            new ClassReader(transformed.bytes()).accept(new ClassVisitor(Opcodes.ASM9) {
                @Override public MethodVisitor visitMethod(int access, String name, String d, String sig, String[] exceptions) {
                    return new MethodVisitor(Opcodes.ASM9) { @Override public void visitMethodInsn(int op, String owner, String name, String descriptor, boolean itf) {
                        calls.add(owner + ":" + name + descriptor);
                    }};
                }
            }, 0);
            assertTrue(calls.contains("dev/aitalkstreamer/mc/survival/SurvivalGui:" + rule.relay().substring(4) + desc));
            assertFalse(calls.contains(rule.owner() + ":" + rule.name() + rule.descriptor()));
        }
    }
    @Test void aMislabelledGuiRouteStopsBeforeBytecodeIsEmitted() throws Exception {
        var json = JsonParser.parseString(Files.readString(Path.of("gate-policy.json"))).getAsJsonObject();
        json.getAsJsonArray("rules").get(0).getAsJsonObject().addProperty("relay", "gui_slot");
        Path invalid = temporary.resolve("invalid-policy.json"); Files.writeString(invalid, json.toString());
        assertEquals("GAME_GATE_GUI_SIGNATURE", assertThrows(IllegalArgumentException.class, () -> GatePolicy.read(invalid)).getMessage());
    }
}
