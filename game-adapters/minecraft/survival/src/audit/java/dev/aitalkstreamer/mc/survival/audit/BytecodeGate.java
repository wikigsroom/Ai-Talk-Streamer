package dev.aitalkstreamer.mc.survival.audit;

import com.google.gson.*;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.GeneratorAdapter;
import org.objectweb.asm.commons.Method;
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.zip.*;

/** Offline compiler: each selected invocation/field write executes inside one native permit check. */
public final class BytecodeGate {
    private static final String AUTHORITY = "dev/aitalkstreamer/mc/survival/SurvivalAuthority";
    private static final String INPUTS = "dev/aitalkstreamer/mc/survival/SurvivalInputs";
    private static final String GUI = "dev/aitalkstreamer/mc/survival/SurvivalGui";
    private static final String ACTIONS = "dev/aitalkstreamer/mc/survival/SurvivalActions";
    private static final String OPTIONS = "dev/aitalkstreamer/mc/survival/SurvivalOptions";
    private static final String POLICY = "dev/aitalkstreamer/mc/survival/SurvivalPolicy";
    private static final Handle LAMBDA = new Handle(Opcodes.H_INVOKESTATIC, "java/lang/invoke/LambdaMetafactory", "metafactory",
            "(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodHandle;Ljava/lang/invoke/MethodType;)Ljava/lang/invoke/CallSite;", false);
    private static final Type OBJECT = Type.getType(Object.class);
    private static final Type SUPPLIER = Type.getObjectType("java/util/function/Supplier");
    public record Site(String origin, String method, String kind, String owner, String member, String descriptor, String route) { }
    public record Result(byte[] bytes, List<Site> sites) { }
    private record Operation(String wrapper, int opcode, String owner, String name, String descriptor,
                             boolean itf, Type[] arguments, Type result, GatePolicy.Rule rule) { }
    private BytecodeGate() { }
    public static Result transform(byte[] input, GatePolicy policy) {
        ClassReader reader = new ClassReader(input);
        // The runtime gate and native sink must not be recursively gated.
        if (reader.getClassName().startsWith("dev/aitalkstreamer/")) return new Result(input, List.of());
        ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        List<Site> sites = new ArrayList<>();
        List<Operation> operations = new ArrayList<>();
        reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
            private String origin;
            private boolean originInterface;
            @Override public void visit(int version, int access, String name, String signature, String parent, String[] interfaces) {
                origin = name; originInterface = (access & Opcodes.ACC_INTERFACE) != 0;
                // Private static interface wrappers require Java9; the runtime contract is Java21.
                super.visit(originInterface ? Math.max(version, Opcodes.V9) : version, access, name, signature, parent, interfaces);
            }
            @Override public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
                if (name.startsWith("$ats$")) throw new IllegalArgumentException("GAME_GATE_ALREADY_TRANSFORMED");
                MethodVisitor delegate = super.visitMethod(access, name, descriptor, signature, exceptions);
                return new MethodVisitor(Opcodes.ASM9, delegate) {
                    private void rejectReference(Handle handle) {
                        boolean field = handle.getTag() == Opcodes.H_PUTFIELD || handle.getTag() == Opcodes.H_PUTSTATIC;
                        boolean call = handle.getTag() >= Opcodes.H_INVOKEVIRTUAL;
                        if ((field || call) && policy.match(field ? "FIELD" : "CALL", handle.getOwner(), handle.getName(), handle.getDesc()) != null)
                            throw new IllegalArgumentException((field ? "GAME_GATE_DIRECT_FIELD_REFERENCE:" : "GAME_GATE_DIRECT_METHOD_REFERENCE:") + origin);
                    }
                    private void replace(int opcode, String owner, String member, String desc, boolean itf, GatePolicy.Rule rule) {
                        Type result = rule.kind().equals("CALL") ? Type.getReturnType(desc) : Type.VOID_TYPE;
                        List<Type> arguments = new ArrayList<>();
                        if (opcode != Opcodes.INVOKESTATIC && opcode != Opcodes.PUTSTATIC) arguments.add(Type.getObjectType(owner));
                        arguments.addAll(Arrays.asList(rule.kind().equals("CALL") ? Type.getArgumentTypes(desc) : new Type[]{Type.getType(desc)}));
                        String wrapper = "$ats$effect$" + operations.size();
                        Type[] types = arguments.toArray(Type[]::new);
                        operations.add(new Operation(wrapper, opcode, owner, member, desc, itf, types, result, rule));
                        sites.add(new Site(origin, name + descriptor, rule.kind(), owner, member, desc, rule.relay() == null ? "PER_WRITE_EFFECT" : rule.relay()));
                        super.visitMethodInsn(Opcodes.INVOKESTATIC, origin, wrapper, Type.getMethodDescriptor(result, types), originInterface);
                    }
                    @Override public void visitMethodInsn(int opcode, String owner, String member, String desc, boolean itf) {
                        GatePolicy.Rule rule = policy.match("CALL", owner, member, desc);
                        if (rule == null) super.visitMethodInsn(opcode, owner, member, desc, itf);
                        else replace(opcode, owner, member, desc, itf, rule);
                    }
                    @Override public void visitFieldInsn(int opcode, String owner, String member, String desc) {
                        GatePolicy.Rule rule = opcode == Opcodes.PUTFIELD || opcode == Opcodes.PUTSTATIC ? policy.match("FIELD", owner, member, desc) : null;
                        if (rule == null) super.visitFieldInsn(opcode, owner, member, desc);
                        else replace(opcode, owner, member, desc, false, rule);
                    }
                    @Override public void visitInvokeDynamicInsn(String member, String desc, Handle bootstrap, Object... arguments) {
                        // A direct method reference would bypass visitMethodInsn; require an explicit lambda body instead.
                        rejectReference(bootstrap);
                        for (Object arg : arguments) if (arg instanceof Handle handle) rejectReference(handle);
                        super.visitInvokeDynamicInsn(member, desc, bootstrap, arguments);
                    }
                    @Override public void visitLdcInsn(Object value) {
                        if (value instanceof Handle handle) rejectReference(handle);
                        super.visitLdcInsn(value);
                    }
                };
            }
            @Override public void visitEnd() {
                for (Operation operation : operations) emit(writer, origin, originInterface, operation);
                super.visitEnd();
            }
        }, 0);
        return new Result(writer.toByteArray(), List.copyOf(sites));
    }
    private static GeneratorAdapter method(ClassWriter writer, String name, Type result, Type[] arguments) {
        return new GeneratorAdapter(Opcodes.ACC_PRIVATE | Opcodes.ACC_STATIC | Opcodes.ACC_SYNTHETIC,
                new Method(name, result, arguments), null, null, writer);
    }
    private static void emit(ClassWriter writer, String origin, boolean originInterface, Operation operation) {
        GeneratorAdapter wrapper = method(writer, operation.wrapper(), operation.result(), operation.arguments());
        wrapper.loadArgs();
        if (operation.rule().relay() != null) {
            String relay = operation.rule().relay();
            boolean gui = relay.startsWith("gui_"); boolean action = relay.startsWith("action_"); boolean option = relay.startsWith("option_");
            boolean motion = relay.startsWith("motion_"); boolean policy = relay.startsWith("policy_");
            String target = gui ? relay.substring(4) : action || option || motion || policy ? relay.substring(7) : relay;
            if (!(action ? Set.of("yaw", "pitch", "sprint", "swing", "attackBlock", "breakProgress", "cancelBreaking", "attackEntity", "interactEntity", "interactItem", "stopUsing").contains(target)
                    && operation.rule().kind().equals("CALL") && operation.opcode() == Opcodes.INVOKEVIRTUAL
                    : gui ? Set.of("screen", "close", "block", "slot", "recipe").contains(target)
                    : motion ? Set.of("jumping","movementForward","movementSideways","pressingBack","pressingForward","pressingLeft","pressingRight","sneaking").contains(target)
                        && operation.rule().kind().equals("FIELD") && operation.opcode() == Opcodes.PUTFIELD
                        && operation.arguments().length == 2 && operation.result() == Type.VOID_TYPE
                        && operation.arguments()[0].equals(Type.getObjectType("baritone/utils/PlayerMovementInput"))
                        && operation.arguments()[1].equals(target.startsWith("movement") ? Type.FLOAT_TYPE : Type.BOOLEAN_TYPE)
                    : policy ? (target.equals("grounded") && operation.rule().kind().equals("FIELD") && operation.opcode() == Opcodes.PUTFIELD
                        && operation.arguments().length == 2 && operation.arguments()[1].equals(Type.BOOLEAN_TYPE)
                        || Set.of("chatCommand","chatMessage","fallFlying","respawn","disconnect").contains(target)
                        && operation.rule().kind().equals("CALL") && operation.opcode() == Opcodes.INVOKEVIRTUAL)
                    : option ? operation.result() == Type.VOID_TYPE && (target.equals("value") && operation.opcode() == Opcodes.INVOKEVIRTUAL
                        || target.equals("pauseOnLostFocus") && operation.opcode() == Opcodes.PUTFIELD)
                    : Set.of("movement", "key", "select", "sneaking").contains(target) && operation.result() == Type.VOID_TYPE))
                throw new IllegalArgumentException("GAME_GATE_RELAY_RULE");
            if (target.equals("select") && !(operation.opcode() == Opcodes.PUTFIELD
                    && operation.rule().kind().equals("FIELD") && operation.arguments().length == 2
                    && operation.arguments()[1].equals(Type.INT_TYPE)))
                throw new IllegalArgumentException("GAME_GATE_HOTBAR_SIGNATURE");
            if (target.equals("sneaking") && !(operation.opcode() == Opcodes.PUTFIELD
                    && operation.rule().kind().equals("FIELD") && operation.arguments().length == 2
                    && operation.arguments()[1].equals(Type.BOOLEAN_TYPE)))
                throw new IllegalArgumentException("GAME_GATE_SNEAK_SIGNATURE");
            Type[] nativeArguments = operation.arguments().clone();
            // The native input owner depends on Minecraft Input, never on a Baritone implementation class.
            if (motion) nativeArguments[0] = Type.getObjectType(operation.rule().declaration());
            wrapper.visitMethodInsn(Opcodes.INVOKESTATIC, action ? ACTIONS : gui ? GUI : option ? OPTIONS : policy ? POLICY : INPUTS,
                    motion ? relay : target, Type.getMethodDescriptor(operation.result(), nativeArguments), false);
        } else {
            String body = operation.wrapper() + "$body";
            wrapper.visitInvokeDynamicInsn("get", Type.getMethodDescriptor(SUPPLIER, operation.arguments()), LAMBDA,
                    Type.getMethodType("()Ljava/lang/Object;"),
                    new Handle(Opcodes.H_INVOKESTATIC, origin, body, Type.getMethodDescriptor(OBJECT, operation.arguments()), originInterface),
                    Type.getMethodType("()Ljava/lang/Object;"));
            wrapper.visitMethodInsn(Opcodes.INVOKESTATIC, AUTHORITY, "effect", "(Ljava/util/function/Supplier;)Ljava/lang/Object;", false);
            if (operation.result() == Type.VOID_TYPE) wrapper.pop(); else wrapper.unbox(operation.result());
            GeneratorAdapter action = method(writer, body, OBJECT, operation.arguments());
            action.loadArgs();
            if (operation.rule().kind().equals("CALL"))
                action.visitMethodInsn(operation.opcode(), operation.owner(), operation.name(), operation.descriptor(), operation.itf());
            else action.visitFieldInsn(operation.opcode(), operation.owner(), operation.name(), operation.descriptor());
            if (operation.result() == Type.VOID_TYPE) action.push((String) null); else action.box(operation.result());
            action.returnValue(); action.endMethod();
        }
        wrapper.returnValue(); wrapper.endMethod();
    }
    public static String hash(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    public static void main(String[] args) throws IOException {
        if (args.length != 6 || !Set.of("dir", "jar").contains(args[0])) throw new IllegalArgumentException("mode policy mapping input output report");
        Path policyFile = Path.of(args[1]), mapping = Path.of(args[2]), input = Path.of(args[3]), output = Path.of(args[4]), report = Path.of(args[5]);
        if (input.toAbsolutePath().normalize().equals(output.toAbsolutePath().normalize())
                || Files.exists(output) && Files.isSameFile(input, output)) throw new IllegalArgumentException("GAME_GATE_INPUT_OUTPUT_ALIAS");
        GatePolicy policy = GatePolicy.read(policyFile);
        if (args[0].equals("jar")) policy = policy.intermediary(mapping);
        List<Site> sites = new ArrayList<>(); List<Map<String, String>> classes = new ArrayList<>();
        var callbackSymbols = args[0].equals("jar") ? BaritoneCallbacksCompiler.Symbols.intermediary(mapping) : BaritoneCallbacksCompiler.Symbols.named();
        List<BaritoneCallbacksCompiler.Site> callbackSites = new ArrayList<>();
        if (args[0].equals("dir")) {
            if (input.toAbsolutePath().normalize().equals(output.toAbsolutePath().normalize())) throw new IllegalArgumentException("GAME_GATE_INPUT_OUTPUT_ALIAS");
            Files.createDirectories(output); Set<Path> expected = new HashSet<>();
            try (var paths = Files.walk(input)) {
                for (Path file : paths.filter(Files::isRegularFile).sorted().toList()) {
                    Path target = output.resolve(input.relativize(file)).toAbsolutePath().normalize();
                    if (!target.startsWith(output.toAbsolutePath().normalize())) throw new IllegalArgumentException("GAME_GATE_OUTPUT_PATH");
                    byte[] original = Files.readAllBytes(file); Result transformed = file.toString().endsWith(".class") ? transform(original, policy) : new Result(original, List.of());
                    var callbacks = file.toString().endsWith(".class") ? BaritoneCallbacksCompiler.transform(transformed.bytes(),callbackSymbols) : new BaritoneCallbacksCompiler.Result(transformed.bytes(),List.of());
                    Files.createDirectories(target.getParent()); Files.write(target, callbacks.bytes()); expected.add(target); sites.addAll(transformed.sites()); callbackSites.addAll(callbacks.sites());
                    classes.add(Map.of("path", input.relativize(file).toString().replace(File.separatorChar, '/'), "before", hash(original), "after", hash(callbacks.bytes())));
                }
            }
            // Delete only stale generated files inside this exact output directory; never move/remove a tree.
            try (var paths = Files.walk(output)) {
                for (Path file : paths.filter(Files::isRegularFile).toList()) if (!expected.contains(file.toAbsolutePath().normalize())) {
                    if (Files.isSymbolicLink(file) || !file.toRealPath().startsWith(output.toRealPath())) throw new IllegalArgumentException("GAME_GATE_OUTPUT_PATH");
                    Files.delete(file);
                }
            }
        } else {
            Files.createDirectories(output.getParent());
            try (ZipFile archive = new ZipFile(input.toFile()); ZipOutputStream stream = new ZipOutputStream(Files.newOutputStream(output))) {
                for (ZipEntry entry : Collections.list(archive.entries()).stream().filter(item -> !item.isDirectory()).sorted(Comparator.comparing(ZipEntry::getName)).toList()) {
                    if (entry.getName().matches("(?i)META-INF/.*\\.(SF|RSA|DSA|EC)")) throw new IllegalArgumentException("GAME_GATE_SIGNED_INPUT");
                    if (entry.getSize() > 8 * 1024 * 1024) throw new IllegalArgumentException("GAME_GATE_ENTRY_SIZE");
                    byte[] original;
                    try (InputStream contents = archive.getInputStream(entry)) { original = contents.readNBytes(8 * 1024 * 1024 + 1); }
                    if (original.length > 8 * 1024 * 1024) throw new IllegalArgumentException("GAME_GATE_ENTRY_SIZE");
                    Result transformed = entry.getName().endsWith(".class") ? transform(original, policy) : new Result(original, List.of());
                    var callbacks = entry.getName().endsWith(".class") ? BaritoneCallbacksCompiler.transform(transformed.bytes(),callbackSymbols) : new BaritoneCallbacksCompiler.Result(transformed.bytes(),List.of());
                    ZipEntry next = new ZipEntry(entry.getName()); next.setTime(0); stream.putNextEntry(next); stream.write(callbacks.bytes()); stream.closeEntry();
                    sites.addAll(transformed.sites()); callbackSites.addAll(callbacks.sites());
                    if (entry.getName().endsWith(".class")) classes.add(Map.of("path", entry.getName(), "before", hash(original), "after", hash(callbacks.bytes())));
                }
            }
        }
        JsonObject receipt = new JsonObject(); Gson gson = new GsonBuilder().setPrettyPrinting().create();
        receipt.addProperty("classification", "ENGINEERING_BYTECODE_TRANSFORM_NOT_RUNTIME_ACCEPTANCE");
        receipt.addProperty("namespace", args[0].equals("jar") ? "intermediary" : "named");
        receipt.addProperty("policy_sha256", hash(Files.readAllBytes(policyFile)));
        receipt.addProperty("mapping_sha256", hash(Files.readAllBytes(mapping)));
        receipt.addProperty("input_sha256", args[0].equals("jar") ? hash(Files.readAllBytes(input)) : null);
        receipt.addProperty("output_sha256", args[0].equals("jar") ? hash(Files.readAllBytes(output)) : null);
        receipt.add("classes", gson.toJsonTree(classes)); receipt.add("sites", gson.toJsonTree(sites));
        receipt.add("callback_sites",gson.toJsonTree(callbackSites));
        receipt.addProperty("callback_compiler_revision",2);
        receipt.addProperty("automatic_input_authorized", false);
        Files.createDirectories(report.getParent()); Files.writeString(report, gson.toJson(receipt) + "\n");
        System.out.println("Compiled " + sites.size() + " explicit gate sites in " + classes.size() + " entries; runtime remains unauthorized.");
    }
}
