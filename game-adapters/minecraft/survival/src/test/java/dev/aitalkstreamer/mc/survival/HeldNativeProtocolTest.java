package dev.aitalkstreamer.mc.survival;
import org.junit.jupiter.api.Test;
import org.objectweb.asm.*;
import com.google.gson.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Checks the fixed MC bytecode and real bridge wiring; it does not apply Mixins in a game. */
class HeldNativeProtocolTest {
    byte[] bytes(String name) throws Exception {
        try(var stream=getClass().getResourceAsStream('/'+name+".class")){assertNotNull(stream,name);return stream.readAllBytes();}
    }
    Map<String,List<String>> calls(String name) throws Exception {
        Map<String,List<String>> result=new HashMap<>();new ClassReader(bytes(name)).accept(new ClassVisitor(Opcodes.ASM9){
            public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e){
                var list=new ArrayList<String>();result.put(n+d,list);return new MethodVisitor(Opcodes.ASM9){
                    public void visitMethodInsn(int o,String owner,String n,String d,boolean i){list.add(owner+":"+n+d);}
                };
            }
        },ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);return result;
    }
    @Test void allThreeWrappedMethodsExistWithThePinnedVanillaDescriptors() throws Exception {
        var actual=calls("net/minecraft/client/MinecraftClient");
        assertTrue(actual.keySet().containsAll(Set.of("doAttack()Z","handleBlockBreaking(Z)V","doItemUse()V")));
        Set<String> selected=new HashSet<>();new ClassReader(bytes("dev/aitalkstreamer/mc/mixin/HeldInputMixin")).accept(new ClassVisitor(Opcodes.ASM9){
            public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e){return new MethodVisitor(Opcodes.ASM9){
                public AnnotationVisitor visitAnnotation(String descriptor,boolean visible){
                    if(!descriptor.endsWith("/WrapMethod;"))return null;
                    return new AnnotationVisitor(Opcodes.ASM9){public AnnotationVisitor visitArray(String name){
                        assertEquals("method",name);return new AnnotationVisitor(Opcodes.ASM9){public void visit(String n,Object value){selected.add(value.toString());}};
                    }};
                }
            };}
        },ClassReader.SKIP_CODE|ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);
        assertEquals(Set.of("doAttack","handleBlockBreaking","doItemUse"),selected);
    }
    @Test void theRealBridgeRegistersTheWrapperAndEveryWrapperUsesTheSolePort() throws Exception {
        try(var stream=getClass().getResourceAsStream("/mc-bridge.mixins.json")){
            assertNotNull(stream);var mixins=JsonParser.parseString(new String(stream.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8)).getAsJsonObject();
            assertEquals(1,mixins.getAsJsonArray("client").asList().stream().filter(v->v.getAsString().equals("HeldInputMixin")).count());
        }
        var wrapper=calls("dev/aitalkstreamer/mc/mixin/HeldInputMixin");
        assertEquals(3,wrapper.values().stream().filter(v->v.stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/McBridgeClient:nativeInput"))).count());
        assertTrue(calls("dev/aitalkstreamer/mc/McBridgeClient").values().stream().flatMap(List::stream).anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/MinecraftPort:nativeInput")));
    }
    @Test void actualDriverConnectsVanillaToTheOriginalRunnerAndTypedActions() throws Exception {
        var driver=calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver");
        assertTrue(driver.values().stream().flatMap(List::stream).anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/ControlledTaskRunner:effect")));
        assertTrue(driver.values().stream().flatMap(List::stream).anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/SurvivalActions:vanilla")));
        var port=calls("dev/aitalkstreamer/mc/MinecraftPort");
        assertTrue(port.values().stream().flatMap(List::stream).anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/core/HeldActionRouter:route")));
    }
    @Test void heldUsePreflightIsNotDuplicatedByTheOldClickPredicate() throws Exception {
        var port=calls("dev/aitalkstreamer/mc/MinecraftPort");
        assertFalse(port.values().stream().flatMap(List::stream).anyMatch(c->c.contains("ClientExecutor:beforeUse")));
        var actions=calls("dev/aitalkstreamer/mc/survival/SurvivalActions");
        assertTrue(actions.values().stream().flatMap(List::stream).anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/SurvivalGui:beforeUse")));
    }
}
