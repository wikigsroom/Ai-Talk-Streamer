package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.survival.audit.*;
import dev.aitalkstreamer.mc.core.ControlArbiter;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.*;
import java.lang.reflect.InvocationTargetException;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

/** Actual transformed bytecode and native arbiter, using explicit non-game effects. */
class BytecodeGateTest {
    public static final class Target {
        public static final AtomicInteger effects = new AtomicInteger();
        public static Runnable after = () -> {};
        public int value;
        public static int global;
        public static int change(int value) { effects.incrementAndGet(); after.run(); return value + 1; }
        public static long wide(long n, double d, boolean flag) { effects.incrementAndGet(); return n + (long) d + (flag ? 1 : 0); }
        public String text(String value) { effects.incrementAndGet(); return value + "!"; }
        public static void hit() { effects.incrementAndGet(); }
        public static void failEffect() { effects.incrementAndGet(); throw new IllegalArgumentException("fixture effect"); }
    }
    private static final String TARGET = Type.getInternalName(Target.class);
    private static final String FIXTURE = "fixture/ControlledEffects";
    private SurvivalAuthority.Session session;
    private ControlArbiter control;
    private final AtomicLong now = new AtomicLong(10000);
    @TempDir Path temporary;
    @BeforeEach void setup() {
        Target.effects.set(0); Target.after = () -> {}; Target.global = 0;
        control = new ControlArbiter(now::get, () -> {});
        control.world("world-fixture"); control.attach("controller-fixture"); control.release(control.epoch(), () -> {});
        control.observe(1); control.beginAuto("controller-fixture", "world-fixture", control.epoch(), true);
        control.grant("controller-fixture", control.lease(), control.epoch(), 1, control.heartbeat(), 10000);
        var permit = control.permit(); String id = "task-fixture";
        session = SurvivalAuthority.open(new SurvivalAuthority.Context(id, permit.controller(), permit.lease(), permit.world(), permit.epoch()),
                new ArbiterBoundary(control, permit, id));
    }
    @AfterEach void cleanup() { session.close(() -> {}, () -> {}); }
    private GatePolicy policy(String kind, String name, String descriptor) {
        return new GatePolicy(List.of(new GatePolicy.Rule(kind, TARGET, name, descriptor, TARGET, null)));
    }
    private byte[] fixture(String methodDescriptor, java.util.function.Consumer<GeneratorAdapter> code, boolean itf) {
        ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        writer.visit(itf ? Opcodes.V1_8 : Opcodes.V21, Opcodes.ACC_PUBLIC | (itf ? Opcodes.ACC_INTERFACE | Opcodes.ACC_ABSTRACT : 0),
                FIXTURE, null, "java/lang/Object", null);
        GeneratorAdapter method = new GeneratorAdapter(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC,
                new Method("run", methodDescriptor), null, null, writer);
        code.accept(method); method.returnValue(); method.endMethod(); writer.visitEnd(); return writer.toByteArray();
    }
    private Class<?> load(byte[] bytes) {
        return new ClassLoader(getClass().getClassLoader()) { Class<?> define() { return defineClass(null, bytes, 0, bytes.length); } }.define();
    }
    private Object invoke(Class<?> type, Class<?>[] parameters, Object... args) {
        try { return type.getMethod("run", parameters).invoke(null, args); }
        catch (InvocationTargetException error) {
            if (error.getCause() instanceof RuntimeException failure) throw failure;
            if (error.getCause() instanceof Error failure) throw failure;
            throw new AssertionError(error.getCause());
        } catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private byte[] integerCall() {
        return fixture("(I)I", method -> { method.loadArg(0); method.invokeStatic(Type.getType(Target.class), new Method("change", "(I)I")); }, false);
    }
    @Test void staticPrimitiveCallCannotRunWithoutScope() {
        Class<?> type = load(BytecodeGate.transform(integerCall(), policy("CALL", "change", "(I)I")).bytes());
        assertThrows(SurvivalAuthority.Denied.class, () -> invoke(type, new Class[]{int.class}, 4)); assertEquals(0, Target.effects.get());
    }
    @Test void authorizedCallPreservesArgumentsReturnAndSingleEffect() {
        Class<?> type = load(BytecodeGate.transform(integerCall(), policy("CALL", "change", "(I)I")).bytes());
        SurvivalAuthority.run(session, () -> assertEquals(5, invoke(type, new Class[]{int.class}, 4))); assertEquals(1, Target.effects.get());
    }
    @Test void widePrimitiveCapturesKeepTheirStackSlotsAndTypes() {
        byte[] original = fixture("(JDZ)J", method -> { method.loadArgs(); method.invokeStatic(Type.getType(Target.class), new Method("wide", "(JDZ)J")); }, false);
        Class<?> type = load(BytecodeGate.transform(original, policy("CALL", "wide", "(JDZ)J")).bytes());
        SurvivalAuthority.run(session, () -> assertEquals(13L, invoke(type, new Class[]{long.class, double.class, boolean.class}, 10L, 2.5, true)));
    }
    @Test void instanceReceiverAndReferenceResultArePreserved() {
        String desc = "(L" + TARGET + ";Ljava/lang/String;)Ljava/lang/String;";
        byte[] original = fixture(desc, method -> { method.loadArgs(); method.invokeVirtual(Type.getType(Target.class), new Method("text", "(Ljava/lang/String;)Ljava/lang/String;")); }, false);
        Class<?> type = load(BytecodeGate.transform(original, policy("CALL", "text", "(Ljava/lang/String;)Ljava/lang/String;")).bytes());
        SurvivalAuthority.run(session, () -> assertEquals("hello!", invoke(type, new Class[]{Target.class, String.class}, new Target(), "hello")));
    }
    @Test void voidActionsDoNotLeaveAValueOnTheStack() {
        byte[] original = fixture("()V", method -> method.invokeStatic(Type.getType(Target.class), new Method("hit", "()V")), false);
        Class<?> type = load(BytecodeGate.transform(original, policy("CALL", "hit", "()V")).bytes());
        SurvivalAuthority.run(session, () -> assertNull(invoke(type, new Class[]{}))); assertEquals(1, Target.effects.get());
    }
    @Test void fieldStoreIsRefusedBeforeMutationAndWorksInOriginalScope() {
        byte[] original = fixture("(L" + TARGET + ";I)I", method -> {
            method.loadArgs(); method.putField(Type.getType(Target.class), "value", Type.INT_TYPE);
            method.loadArg(0); method.getField(Type.getType(Target.class), "value", Type.INT_TYPE);
        }, false);
        Class<?> type = load(BytecodeGate.transform(original, policy("FIELD", "value", "I")).bytes()); var target = new Target();
        assertThrows(SurvivalAuthority.Denied.class, () -> invoke(type, new Class[]{Target.class, int.class}, target, 8)); assertEquals(0, target.value);
        SurvivalAuthority.run(session, () -> assertEquals(8, invoke(type, new Class[]{Target.class, int.class}, target, 8)));
    }
    @Test void staticFieldStoreUsesTheSameGate() {
        byte[] original = fixture("(I)V", method -> { method.loadArg(0); method.putStatic(Type.getType(Target.class), "global", Type.INT_TYPE); }, false);
        Class<?> type = load(BytecodeGate.transform(original, policy("FIELD", "global", "I")).bytes());
        assertThrows(SurvivalAuthority.Denied.class, () -> invoke(type, new Class[]{int.class}, 9)); assertEquals(0, Target.global);
        SurvivalAuthority.run(session, () -> invoke(type, new Class[]{int.class}, 9)); assertEquals(9, Target.global);
    }
    @Test void revocationBetweenTwoCallsRefusesTheSecondEffect() {
        byte[] original = fixture("()I", method -> {
            method.push(1); method.invokeStatic(Type.getType(Target.class), new Method("change", "(I)I")); method.pop();
            method.push(2); method.invokeStatic(Type.getType(Target.class), new Method("change", "(I)I"));
        }, false);
        Class<?> type = load(BytecodeGate.transform(original, policy("CALL", "change", "(I)I")).bytes());
        Target.after = () -> control.stop(ControlArbiter.Mode.PAUSED);
        assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.run(session, () -> invoke(type, new Class[]{})));
        assertEquals(1, Target.effects.get());
    }
    @Test void realEffectExceptionIsNotConvertedIntoSuccess() {
        byte[] original = fixture("()V", method -> method.invokeStatic(Type.getType(Target.class), new Method("failEffect", "()V")), false);
        Class<?> type = load(BytecodeGate.transform(original, policy("CALL", "failEffect", "()V")).bytes());
        assertEquals("fixture effect", assertThrows(IllegalArgumentException.class, () -> SurvivalAuthority.run(session, () -> invoke(type, new Class[]{}))).getMessage());
        assertEquals(1, Target.effects.get());
    }
    @Test void javaEightInterfaceCanContainAControlledStaticAction() {
        byte[] original = fixture("(I)I", method -> { method.loadArgs(); method.invokeStatic(Type.getType(Target.class), new Method("change", "(I)I")); }, true);
        Class<?> type = load(BytecodeGate.transform(original, policy("CALL", "change", "(I)I")).bytes());
        SurvivalAuthority.run(session, () -> assertEquals(3, invoke(type, new Class[]{int.class}, 2)));
    }
    @Test void alreadyTransformedClassesAreRefusedRatherThanNestedAgain() {
        var policy = policy("CALL", "change", "(I)I");
        byte[] once = BytecodeGate.transform(integerCall(), policy).bytes();
        assertThrows(IllegalArgumentException.class, () -> BytecodeGate.transform(once, policy));
    }
    @Test void directMutationMethodReferenceRequiresExplicitAdaptation() {
        byte[] original = fixture("()Ljava/lang/Runnable;", method -> method.visitInvokeDynamicInsn("run", "()Ljava/lang/Runnable;",
                new Handle(Opcodes.H_INVOKESTATIC, "java/lang/invoke/LambdaMetafactory", "metafactory",
                        "(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodHandle;Ljava/lang/invoke/MethodType;)Ljava/lang/invoke/CallSite;", false),
                Type.getMethodType("()V"), new Handle(Opcodes.H_INVOKESTATIC, TARGET, "hit", "()V", false), Type.getMethodType("()V")), false);
        assertThrows(IllegalArgumentException.class, () -> BytecodeGate.transform(original, policy("CALL", "hit", "()V")));
    }
    @Test void unselectedReadIsNotTreatedAsAnInputMutation() {
        byte[] original = fixture("(L" + TARGET + ";)I", method -> { method.loadArg(0); method.getField(Type.getType(Target.class), "value", Type.INT_TYPE); }, false);
        var result = BytecodeGate.transform(original, policy("FIELD", "value", "I")); assertTrue(result.sites().isEmpty());
        var target = new Target(); target.value = 4; assertEquals(4, invoke(load(result.bytes()), new Class[]{Target.class}, target));
    }
    @Test void pinnedTinyMappingResolvesDeclaredAndInheritedNames() throws Exception {
        Path tiny = temporary.resolve("mapping.tiny");
        Files.writeString(tiny, "tiny\t2\t0\tintermediary\tnamed\nc\tnet/minecraft/class_1\tnet/minecraft/Fake\n\tm\t(I)I\tmethod_1\tchange\n\tf\tI\tfield_1\tvalue\n");
        var named = new GatePolicy(List.of(new GatePolicy.Rule("CALL", "net/minecraft/Fake", "change", "(I)I", "net/minecraft/Fake", null)));
        assertNotNull(named.intermediary(tiny).match("CALL", "net/minecraft/class_1", "method_1", "(I)I"));
    }
    @Test void ambiguousOrUnexpectedMappingsStopTheBuild() throws Exception {
        Path tiny = temporary.resolve("mapping.tiny");
        Files.writeString(tiny, "tiny\t2\t0\tintermediary\tnamed\nc\ta\tFirst\n\tm\t(I)I\tone\tchange\nc\tb\tSecond\n\tm\t(I)I\ttwo\tchange\n");
        var named = new GatePolicy(List.of(new GatePolicy.Rule("CALL", "Child", "change", "(I)I", "Child", null)));
        assertThrows(IllegalArgumentException.class, () -> named.intermediary(tiny));
        Files.writeString(tiny, "tiny\t2\t0\tofficial\tnamed\n");
        assertThrows(IllegalArgumentException.class, () -> named.intermediary(tiny));
    }
}
