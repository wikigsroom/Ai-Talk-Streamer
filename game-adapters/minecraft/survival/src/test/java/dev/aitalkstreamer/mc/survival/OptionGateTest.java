package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.ControlArbiter;
import dev.aitalkstreamer.mc.core.ControlArbiter.Mode;
import dev.aitalkstreamer.mc.survival.audit.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.*;
import javax.tools.ToolProvider;
import java.io.*;
import java.lang.reflect.InvocationTargetException;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import static org.junit.jupiter.api.Assertions.*;

/** Actual gate, setting sink and native arbiter; client APIs are explicit non-game test doubles. */
class OptionGateTest {
    @TempDir static Path temporary;
    static Map<String, byte[]> stubs;
    ClassLoader loader;
    Class<?> authority, sessionType, contextType, boundaryType, sink, simple, optionsType, writer;
    Object client, options, autoJump, gamma, session;
    AtomicLong clock = new AtomicLong(100);
    ControlArbiter control;

    @BeforeAll static void compileClientDoubles() throws Exception {
        Map<String, String> sources = new LinkedHashMap<>();
        sources.put("net.minecraft.client.option.SimpleOption", """
            package net.minecraft.client.option;
            public class SimpleOption<T> {
                public T value; public int writes; public boolean failNext;
                public SimpleOption(T value) { this.value=value; }
                public T getValue() { return value; }
                public void setValue(T next) { value=next; writes++; if(failNext){failNext=false;throw new IllegalStateException("FIXTURE_CALLBACK");} }
            }
            """);
        sources.put("net.minecraft.client.option.GameOptions", """
            package net.minecraft.client.option;
            public class GameOptions {
                public boolean pauseOnLostFocus=true;
                private final SimpleOption<Boolean> autoJump=new SimpleOption<>(true);
                private final SimpleOption<Double> gamma=new SimpleOption<>(.4);
                public SimpleOption<Boolean> getAutoJump(){return autoJump;}
                public SimpleOption<Double> getGamma(){return gamma;}
            }
            """);
        sources.put("net.minecraft.client.world.ClientWorld", "package net.minecraft.client.world; public class ClientWorld {}");
        sources.put("net.minecraft.client.network.ClientPlayerEntity", "package net.minecraft.client.network; public class ClientPlayerEntity {}");
        sources.put("net.minecraft.client.MinecraftClient", """
            package net.minecraft.client;
            public class MinecraftClient {
                public static final MinecraftClient INSTANCE=new MinecraftClient();
                public net.minecraft.client.option.GameOptions options=new net.minecraft.client.option.GameOptions();
                public net.minecraft.client.world.ClientWorld world=new net.minecraft.client.world.ClientWorld();
                public net.minecraft.client.network.ClientPlayerEntity player=new net.minecraft.client.network.ClientPlayerEntity();
                public final Thread owner=Thread.currentThread();public boolean focused=true, paused;
                public static MinecraftClient getInstance(){return INSTANCE;}
                public boolean isOnThread(){return Thread.currentThread()==owner;}
                public boolean isWindowFocused(){return focused;}
                public boolean isPaused(){return paused;}
            }
            """);
        List<String> arguments = new ArrayList<>(List.of("-encoding", "UTF-8", "-d", temporary.toString()));
        for (var source : sources.entrySet()) {
            Path file = temporary.resolve(source.getKey().replace('.', '/') + ".java"); Files.createDirectories(file.getParent());
            Files.writeString(file, source.getValue()); arguments.add(file.toString());
        }
        assertEquals(0, ToolProvider.getSystemJavaCompiler().run(null, null, null, arguments.toArray(String[]::new)));
        stubs = new HashMap<>();
        try (var paths = Files.walk(temporary)) {
            for (Path file : paths.filter(path -> path.toString().endsWith(".class")).toList())
                stubs.put(temporary.relativize(file).toString().replace(File.separatorChar, '.').replaceAll("\\.class$", ""), Files.readAllBytes(file));
        }
    }
    static byte[] resource(String name) throws IOException {
        try (var input = OptionGateTest.class.getClassLoader().getResourceAsStream(name.replace('.', '/') + ".class")) {
            assertNotNull(input, name); return input.readAllBytes();
        }
    }
    static byte[] writer() throws Exception {
        ClassWriter bytes = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        bytes.visit(Opcodes.V21, Opcodes.ACC_PUBLIC, "fixture/OptionWriter", null, "java/lang/Object", null);
        var value = new GeneratorAdapter(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC,
                new Method("value", "(Lnet/minecraft/client/option/SimpleOption;Ljava/lang/Object;)V"), null, null, bytes);
        value.loadArgs(); value.visitMethodInsn(Opcodes.INVOKEVIRTUAL, "net/minecraft/client/option/SimpleOption", "setValue", "(Ljava/lang/Object;)V", false);
        value.returnValue(); value.endMethod();
        var pause = new GeneratorAdapter(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC,
                new Method("pause", "(Lnet/minecraft/client/option/GameOptions;Z)V"), null, null, bytes);
        pause.loadArgs(); pause.putField(Type.getObjectType("net/minecraft/client/option/GameOptions"), "pauseOnLostFocus", Type.BOOLEAN_TYPE);
        pause.returnValue(); pause.endMethod(); bytes.visitEnd();
        return BytecodeGate.transform(bytes.toByteArray(), GatePolicy.read(Path.of("gate-policy.json"))).bytes();
    }
    @BeforeEach void prepare() throws Exception {
        var definitions = new HashMap<>(stubs); definitions.put("fixture.OptionWriter", writer());
        loader = new ClassLoader(getClass().getClassLoader()) {
            @Override protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
                boolean own = definitions.containsKey(name) || List.of("SurvivalOptions", "SettingLease", "SurvivalAuthority")
                        .stream().anyMatch(base -> name.equals("dev.aitalkstreamer.mc.survival." + base) || name.startsWith("dev.aitalkstreamer.mc.survival." + base + "$"));
                if (!own) return super.loadClass(name, resolve);
                synchronized (getClassLoadingLock(name)) {
                    Class<?> found = findLoadedClass(name);
                    if (found == null) try { byte[] bytes = definitions.containsKey(name) ? definitions.get(name) : resource(name); found = defineClass(name, bytes, 0, bytes.length); }
                    catch (IOException error) { throw new ClassNotFoundException(name, error); }
                    if (resolve) resolveClass(found); return found;
                }
            }
        };
        authority = loader.loadClass("dev.aitalkstreamer.mc.survival.SurvivalAuthority");
        sessionType = loader.loadClass(authority.getName() + "$Session"); contextType = loader.loadClass(authority.getName() + "$Context"); boundaryType = loader.loadClass(authority.getName() + "$Boundary");
        sink = loader.loadClass("dev.aitalkstreamer.mc.survival.SurvivalOptions"); writer = loader.loadClass("fixture.OptionWriter");
        simple = loader.loadClass("net.minecraft.client.option.SimpleOption"); optionsType = loader.loadClass("net.minecraft.client.option.GameOptions");
        client = loader.loadClass("net.minecraft.client.MinecraftClient").getField("INSTANCE").get(null);
        options = client.getClass().getField("options").get(client); autoJump = invoke(optionsType.getMethod("getAutoJump"), options); gamma = invoke(optionsType.getMethod("getGamma"), options);
        control = new ControlArbiter(clock::get, () -> {}); control.world("world"); control.attach("controller"); control.release(control.epoch(), () -> {}); control.observe(1);
        control.beginAuto("controller", "world", control.epoch(), true); control.grant("controller", control.lease(), control.epoch(), 1, control.heartbeat(), 3000);
    }
    static Object invoke(java.lang.reflect.Method method, Object receiver, Object... arguments) {
        try { return method.invoke(receiver, arguments); }
        catch (InvocationTargetException error) {
            if (error.getCause() instanceof RuntimeException failure) throw failure;
            if (error.getCause() instanceof Error failure) throw failure;
            throw new IllegalStateException(error.getCause());
        } catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
    }
    void open() throws Exception {
        var permit = control.permit();
        Object context = contextType.getConstructor(String.class, String.class, String.class, String.class, long.class)
                .newInstance("task", permit.controller(), permit.lease(), permit.world(), permit.epoch());
        Object boundary = java.lang.reflect.Proxy.newProxyInstance(loader, new Class<?>[]{boundaryType}, (proxy, method, args) -> switch (method.getName()) {
            case "current" -> control.allowed() && control.permit().equals(permit);
            case "actuate" -> { control.actuate(permit, () -> { assertTrue(((BooleanSupplier) args[1]).getAsBoolean()); ((Runnable) args[2]).run(); }); yield null; }
            case "releaseOwnedInputs" -> null;
            default -> throw new IllegalStateException(method.getName());
        });
        session = invoke(authority.getMethod("open", contextType, boundaryType), null, context, boundary);
    }
    void run(Runnable action) throws Exception { invoke(authority.getMethod("run", sessionType, Runnable.class), null, session, action); }
    void set(Object target, Object value) { try { invoke(writer.getMethod("value", simple, Object.class), null, target, value); } catch (NoSuchMethodException error) { throw new IllegalStateException(error); } }
    void pause(boolean value) { try { invoke(writer.getMethod("pause", optionsType, boolean.class), null, options, value); } catch (NoSuchMethodException error) { throw new IllegalStateException(error); } }
    Object value(Object target) throws Exception { return invoke(simple.getMethod("getValue"), target); }
    void checkpoint() { try { invoke(sink.getMethod("checkpoint"), null); } catch (NoSuchMethodException error) { throw new IllegalStateException(error); } }
    void close(Runnable stop) throws Exception { if (session != null) invoke(sessionType.getMethod("close", Runnable.class, Runnable.class), session, stop, (Runnable) () -> {}); }
    @AfterEach void cleanup() throws Exception { close(() -> {}); }

    @Test void actualTransformedCallsReachTypedSinkAndHaveNoRawOptionWrites() throws Exception {
        var calls = new HashSet<String>();
        new ClassReader(writer()).accept(new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int a, String n, String d, String s, String[] e) {
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override public void visitMethodInsn(int op, String owner, String name, String desc, boolean itf) { calls.add(owner + ":" + name + desc); }
                    @Override public void visitFieldInsn(int op, String owner, String name, String desc) { assertNotEquals(Opcodes.PUTFIELD, op); }
                };
            }
        }, 0);
        assertTrue(calls.contains("dev/aitalkstreamer/mc/survival/SurvivalOptions:value(Lnet/minecraft/client/option/SimpleOption;Ljava/lang/Object;)V"));
        assertTrue(calls.contains("dev/aitalkstreamer/mc/survival/SurvivalOptions:pauseOnLostFocus(Lnet/minecraft/client/option/GameOptions;Z)V"));
        assertFalse(calls.stream().anyMatch(call -> call.contains("SimpleOption:setValue")));
    }
    @Test void normalNavigationPrePostValuesRestoreTheOriginalSetting() throws Exception {
        open(); run(() -> { set(autoJump, false); set(autoJump, true); set(autoJump, false); }); close(() -> {});
        assertEquals(true, value(autoJump));
    }
    @Test void startupCanRepeatAnIdenticalValueButCannotMutateOptionsWithoutATask() throws Exception {
        set(autoJump, true); pause(true); assertEquals(0, simple.getField("writes").get(autoJump));
        assertThrows(RuntimeException.class, () -> set(autoJump, false)); assertEquals(true, value(autoJump));
    }
    @Test void gammaAndPauseChangesReturnToTheObservedOriginalValuesOnCompletion() throws Exception {
        open(); run(() -> { set(gamma, .8); pause(false); }); close(() -> {});
        assertEquals(.4, value(gamma)); assertTrue(optionsType.getField("pauseOnLostFocus").getBoolean(options));
    }
    @Test void revokedStopCannotWriteAStaleInternalOptionAndRegisteredCleanupRestoresItsOwnChanges() throws Exception {
        open(); run(() -> { set(autoJump, false); set(gamma, .8); pause(false); }); control.stop(Mode.MANUAL_COMMENTARY);
        close(() -> { set(gamma, .9); pause(false); });
        assertEquals(.4, value(gamma)); assertEquals(true, value(autoJump)); assertTrue(optionsType.getField("pauseOnLostFocus").getBoolean(options));
        assertEquals(2, simple.getField("writes").get(gamma));
    }
    @Test void aNativePermitThatExpiresBeforeAWriteCannotBeReacquired() throws Exception {
        open(); Object original = session; clock.addAndGet(4000);
        assertThrows(RuntimeException.class, () -> run(() -> set(autoJump, false))); assertEquals(true, value(autoJump));
        close(() -> {}); assertSame(original, session);
    }
    @Test void anObservedManualChangeAbortsFurtherOwnershipAndIsPreservedByCleanup() throws Exception {
        open(); run(() -> set(gamma, .8)); invoke(simple.getMethod("setValue", Object.class), gamma, .6);
        assertThrows(RuntimeException.class, () -> run(this::checkpoint)); close(() -> {}); assertEquals(.6, value(gamma));
    }
    @Test void aReplacedGameOptionsObjectCannotReceiveOrBeOverwrittenByAnOldClaim() throws Exception {
        open(); run(() -> set(autoJump, false)); Object replacement = optionsType.getConstructor().newInstance();
        client.getClass().getField("options").set(client, replacement);
        assertThrows(RuntimeException.class, () -> run(() -> set(autoJump, false))); close(() -> {});
        assertEquals(true, value(invoke(optionsType.getMethod("getAutoJump"), replacement)));
    }
    @Test void onlyKnownSettingIdentitiesAndTypedFiniteValuesAreAccepted() throws Exception {
        open(); Object foreign = simple.getConstructor(Object.class).newInstance(true);
        for (Object invalid : new Object[]{Double.NaN, Double.POSITIVE_INFINITY, -.1, 1.1, "0.8"})
            assertThrows(RuntimeException.class, () -> run(() -> set(gamma, invalid)));
        assertThrows(RuntimeException.class, () -> run(() -> set(autoJump, 0)));
        assertThrows(RuntimeException.class, () -> run(() -> set(foreign, false))); assertEquals(true, value(foreign));
    }
    @Test void focusPauseAndWrongThreadChecksPreventAllSettingEffects() throws Exception {
        open(); client.getClass().getField("focused").setBoolean(client, false);
        assertThrows(RuntimeException.class, () -> run(() -> set(autoJump, false)));
        client.getClass().getField("focused").setBoolean(client, true); client.getClass().getField("paused").setBoolean(client, true);
        assertThrows(RuntimeException.class, () -> run(() -> set(autoJump, false)));
        client.getClass().getField("paused").setBoolean(client, false); var denied = new AtomicReference<Throwable>();
        Thread thread = new Thread(() -> { try { run(() -> set(autoJump, false)); } catch (Throwable error) { denied.set(error); } });
        thread.start(); thread.join(3000); assertFalse(thread.isAlive()); assertNotNull(denied.get()); assertEquals(true, value(autoJump));
    }
    @Test void aSetterCallbackFailureAfterMutationStillRestoresTheActualValue() throws Exception {
        open(); simple.getField("failNext").setBoolean(gamma, true);
        assertThrows(RuntimeException.class, () -> run(() -> set(gamma, .8))); close(() -> {}); assertEquals(.4, value(gamma));
    }
    @Test void aRestoreFailureRetainsTheOriginalRootAndCanBeRetriedWithoutAnotherSettingWrite() throws Exception {
        open(); run(() -> set(gamma, .8)); simple.getField("failNext").setBoolean(gamma, true);
        assertThrows(RuntimeException.class, () -> close(() -> {}));
        assertThrows(RuntimeException.class, this::open); close(() -> {});
        assertEquals(.4, value(gamma)); assertEquals(2, simple.getField("writes").get(gamma));
    }
    @Test void anOldClosedSessionCannotRestoreOverTheNextRootsSetting() throws Exception {
        open(); run(() -> set(gamma, .8)); Object old = session; close(() -> {}); open(); run(() -> set(gamma, .6));
        invoke(sessionType.getMethod("close", Runnable.class, Runnable.class), old, (Runnable) () -> {}, (Runnable) () -> {});
        assertEquals(.6, value(gamma)); close(() -> {}); assertEquals(.4, value(gamma));
    }
    @Test void malformedOptionPoliciesAreRejectedBeforeAnyTransformation() throws Exception {
        String valid = Files.readString(Path.of("gate-policy.json")); Path policy = temporary.resolve("bad-option-policy.json");
        Files.writeString(policy, valid.replace("\"name\": \"setValue\"", "\"name\": \"getValue\""));
        assertThrows(IllegalArgumentException.class, () -> GatePolicy.read(policy));
        Files.writeString(policy, valid.replace("\"relay\": \"option_value\"", "\"relay\": \"option_arbitrary\""));
        assertThrows(IllegalArgumentException.class, () -> GatePolicy.read(policy));
    }
    @Test void theActualDriverChecksOwnedSettingsBeforeTheUpstreamGameTick() throws Exception {
        var calls = new HeldNativeProtocolTest().calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1").get("tick()V");
        assertTrue(calls.indexOf("dev/aitalkstreamer/mc/survival/SurvivalOptions:checkpoint()V") >= 0);
        assertTrue(calls.indexOf("dev/aitalkstreamer/mc/survival/SurvivalOptions:checkpoint()V") < calls.indexOf("adris/altoclef/AltoClef:onClientTick()V"));
    }
}
