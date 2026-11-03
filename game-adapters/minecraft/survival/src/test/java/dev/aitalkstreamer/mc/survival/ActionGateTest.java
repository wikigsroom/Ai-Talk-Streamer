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

/** Real fixed game symbols, native API and bytecode routes; no client is initialized here. */
class ActionGateTest {
    static final String ACTIONS="dev/aitalkstreamer/mc/survival/SurvivalActions";
    static final Path MAPPING=Path.of("../../../.setup/mc-gradle/caches/fabric-loom/1.21.1/net.fabricmc.yarn.1_21_1.1.21.1+build.3-v2/mappings-base.tiny");
    @TempDir Path temporary;
    Set<String> methods(String name) throws Exception {
        var result=new HashSet<String>();
        try (var stream=getClass().getResourceAsStream('/'+name+".class")) {
            assertNotNull(stream,name); new ClassReader(stream).accept(new ClassVisitor(Opcodes.ASM9) {
                @Override public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e) { result.add(n+d); return null; }
            },ClassReader.SKIP_CODE|ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);
        }
        return result;
    }
    List<GatePolicy.Rule> rules(GatePolicy policy) throws Exception {
        List<GatePolicy.Rule> result=new ArrayList<>();
        for (var value:JsonParser.parseString(Files.readString(Path.of("gate-policy.json"))).getAsJsonObject().getAsJsonArray("rules")) {
            var r=value.getAsJsonObject();
            if (r.has("relay") && r.get("relay").getAsString().startsWith("action_"))
                result.add(policy.match("CALL",r.get("owner").getAsString(),r.get("name").getAsString(),r.get("descriptor").getAsString()));
        }
        assertEquals(13,result.size()); assertFalse(result.contains(null)); return result;
    }
    byte[] fixture(GatePolicy.Rule rule,int opcode,Handle handle) {
        var writer=new ClassWriter(ClassWriter.COMPUTE_MAXS); writer.visit(Opcodes.V21,Opcodes.ACC_PUBLIC,"fixture/ActionCaller",null,"java/lang/Object",null);
        var parameters=new ArrayList<Type>(); parameters.add(Type.getObjectType(rule.owner())); parameters.addAll(List.of(Type.getArgumentTypes(rule.descriptor())));
        Type result=handle==null ? Type.getReturnType(rule.descriptor()) : Type.VOID_TYPE;
        var method=new GeneratorAdapter(Opcodes.ACC_PUBLIC|Opcodes.ACC_STATIC,new Method("run",result,parameters.toArray(Type[]::new)),null,null,writer);
        if (handle!=null) { method.visitLdcInsn(handle); method.pop(); }
        else { method.loadArgs(); method.visitMethodInsn(opcode,rule.owner(),rule.name(),rule.descriptor(),false); }
        method.returnValue(); method.endMethod(); writer.visitEnd(); return writer.toByteArray();
    }
    List<String> calls(byte[] bytes) {
        List<String> result=new ArrayList<>(); new ClassReader(bytes).accept(new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e) {
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override public void visitMethodInsn(int opcode,String owner,String name,String descriptor,boolean itf) { result.add(owner+":"+name+descriptor); }
                };
            }
        },ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES); return result;
    }
    String route(GatePolicy.Rule rule) {
        List<Type> parameters=new ArrayList<>(); parameters.add(Type.getObjectType(rule.owner())); parameters.addAll(List.of(Type.getArgumentTypes(rule.descriptor())));
        return rule.relay().substring(7)+Type.getMethodDescriptor(Type.getReturnType(rule.descriptor()),parameters.toArray(Type[]::new));
    }
    @Test void allThirteenNamedCallsReachExistingTypedNativeMethodsAndContainNoRawOriginalCall() throws Exception {
        var policy=GatePolicy.read(Path.of("gate-policy.json")); var actual=methods(ACTIONS);
        for (var rule:rules(policy)) {
            var transformed=BytecodeGate.transform(fixture(rule,Opcodes.INVOKEVIRTUAL,null),policy);
            assertEquals(rule.relay(),transformed.sites().getFirst().route()); assertEquals(1,transformed.sites().size());
            assertTrue(actual.contains(route(rule)),route(rule)); var calls=calls(transformed.bytes());
            assertTrue(calls.contains(ACTIONS+":"+route(rule))); assertFalse(calls.contains(rule.owner()+":"+rule.name()+rule.descriptor()));
        }
    }
    @Test void everyPinnedIntermediaryCallUsesTheSameTypedRouteWithMappedArgumentsAndReturn() throws Exception {
        var named=GatePolicy.read(Path.of("gate-policy.json")); var mapped=named.intermediary(MAPPING);
        Map<String,String> classes=new HashMap<>();
        for (String line:Files.readAllLines(MAPPING)) if (line.startsWith("c\t")) { String[] c=line.split("\t"); classes.put(c[2],c[1]); }
        Remapper remapper=new Remapper() { @Override public String map(String n) { return classes.getOrDefault(n,n); } };
        for (var rule:rules(named)) {
            var symbol=mapped.match("CALL",remapper.mapType(rule.owner()),mappedName(rule),remapper.mapMethodDesc(rule.descriptor())); assertNotNull(symbol);
            var transformed=BytecodeGate.transform(fixture(symbol,Opcodes.INVOKEVIRTUAL,null),mapped);
            assertEquals(rule.relay(),transformed.sites().getFirst().route());
            assertTrue(calls(transformed.bytes()).contains(ACTIONS+":"+route(symbol)));
            assertEquals(rule.relay().substring(7)+remapper.mapMethodDesc(route(rule).substring(rule.relay().substring(7).length())),route(symbol));
        }
    }
    String mappedName(GatePolicy.Rule wanted) throws Exception {
        String declaration=null;
        for (String line:Files.readAllLines(MAPPING)) {
            String[] c=line.split("\t");
            if (line.startsWith("c\t")) declaration=c[2];
            else if (line.startsWith("\tm\t") && wanted.declaration().equals(declaration) && wanted.name().equals(c[4])) {
                // Each selected name has one descriptor in its declaring class.
                return c[3];
            }
        }
        throw new AssertionError(wanted);
    }
    @Test void invalidActionKindOwnerNameDescriptorAndUnknownRouteCannotEnterThePolicy() throws Exception {
        for (String[] change:List.of(new String[]{"kind","FIELD"},new String[]{"owner","net/minecraft/Other"},
                new String[]{"name","other"},new String[]{"descriptor","()V"},new String[]{"relay","action_not_a_route"})) {
            var json=JsonParser.parseString(Files.readString(Path.of("gate-policy.json"))).getAsJsonObject();
            for (var value:json.getAsJsonArray("rules")) {
                var row=value.getAsJsonObject(); if (row.has("relay") && row.get("relay").getAsString().equals("action_attackEntity")) row.addProperty(change[0],change[1]);
            }
            Path path=temporary.resolve("bad-policy.json"); Files.writeString(path,json.toString());
            assertEquals("GAME_GATE_ACTION_SIGNATURE",assertThrows(IllegalArgumentException.class,()->GatePolicy.read(path)).getMessage());
        }
    }
    @Test void anInstanceActionCannotBeReplacedWithAnUnboundStaticInvocation() throws Exception {
        var policy=GatePolicy.read(Path.of("gate-policy.json")); var rule=rules(policy).getFirst();
        assertEquals("GAME_GATE_RELAY_RULE",assertThrows(IllegalArgumentException.class,
                ()->BytecodeGate.transform(fixture(rule,Opcodes.INVOKESTATIC,null),policy)).getMessage());
    }
    @Test void directActionMethodHandlesCannotBypassTheNativeSink() throws Exception {
        var policy=GatePolicy.read(Path.of("gate-policy.json"));
        for (var rule:rules(policy)) {
            var handle=new Handle(Opcodes.H_INVOKEVIRTUAL,rule.owner(),rule.name(),rule.descriptor(),false);
            assertTrue(assertThrows(IllegalArgumentException.class,()->BytecodeGate.transform(fixture(rule,Opcodes.INVOKEVIRTUAL,handle),policy))
                    .getMessage().startsWith("GAME_GATE_DIRECT_METHOD_REFERENCE"));
        }
    }
    @Test void actualGameProvidesTheAuthoritativeReachAndBlockEntityChecksUsedByTheSink() throws Exception {
        assertTrue(methods("net/minecraft/entity/player/PlayerEntity").containsAll(Set.of(
                "canInteractWithBlockAt(Lnet/minecraft/util/math/BlockPos;D)Z","canInteractWithEntity(Lnet/minecraft/entity/Entity;D)Z")));
        assertTrue(methods("net/minecraft/entity/LivingEntity").contains("canSee(Lnet/minecraft/entity/Entity;)Z"));
        assertTrue(methods("net/minecraft/client/network/ClientPlayerInteractionManager").contains("isBreakingBlock()Z"));
        assertTrue(methods("net/minecraft/entity/Entity").contains("isAttackable()Z"));
    }
    @Test void actualInputScopePinsFourNativeIdentitiesInsideEveryCurrentCheck() throws Exception {
        List<String> calls;
        try (var stream=getClass().getResourceAsStream("/dev/aitalkstreamer/mc/InputOwner$Scope.class")) { assertNotNull(stream); calls=calls(stream.readAllBytes()); }
        assertTrue(calls.contains("dev/aitalkstreamer/mc/core/NativeContext:require(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)V"));
        assertTrue(calls.stream().anyMatch(s->s.contains("InputLeaseFence$Ticket:check")));
        assertTrue(calls.stream().anyMatch(s->s.contains("getNetworkHandler")));
        assertTrue(calls.stream().anyMatch(s->s.contains("isWindowFocused")));
    }
    @Test void actualCompletionCleansInteractionsBeforeClosingTheOwnedGui() throws Exception {
        List<String> calls;
        try (var stream=getClass().getResourceAsStream("/dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1.class")) { assertNotNull(stream); calls=calls(stream.readAllBytes()); }
        int actions=calls.indexOf(ACTIONS+":finishOwned()V"),gui=calls.indexOf("dev/aitalkstreamer/mc/survival/SurvivalGui:finishOwned()V");
        assertTrue(actions>=0 && gui>actions);
    }
}
