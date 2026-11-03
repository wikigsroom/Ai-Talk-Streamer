package dev.aitalkstreamer.mc.survival.audit;

import org.objectweb.asm.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/** Static instruction inventory, not an assertion that any listed call is safe. Never loads game classes. */
public final class WriteSiteInventory {
    private static final SortedSet<String> ROWS = new TreeSet<>();
    private static int classes;
    private static boolean external(String owner) {
        return owner.startsWith("net/minecraft/") || owner.startsWith("org/lwjgl/glfw/")
                || owner.startsWith("baritone/api/") || owner.startsWith("java/util/concurrent/")
                || owner.startsWith("java/net/") || owner.equals("java/lang/Thread");
    }
    private static void scan(String artifact, byte[] bytes) {
        if (bytes.length > 8 * 1024 * 1024) throw new IllegalArgumentException("Class size limit");
        classes++;
        new ClassReader(bytes).accept(new ClassVisitor(Opcodes.ASM9) {
            private String className;
            @Override public void visit(int version, int access, String name, String signature, String parent, String[] interfaces) { className = name; }
            @Override public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
                return new MethodVisitor(Opcodes.ASM9) {
                    private int line = -1, ordinal;
                    @Override public void visitLineNumber(int number, Label start) { line = number; }
                    private void row(String kind, String owner, String member, String type) {
                        ROWS.add(String.join("\t", artifact, className, name + descriptor, Integer.toString(line),
                                Integer.toString(++ordinal), kind, owner, member, type, "UNREVIEWED"));
                    }
                    @Override public void visitMethodInsn(int opcode, String owner, String member, String type, boolean itf) {
                        if (external(owner)) row("CALL_" + opcode, owner, member, type);
                    }
                    @Override public void visitFieldInsn(int opcode, String owner, String member, String type) {
                        if (opcode == Opcodes.PUTFIELD || opcode == Opcodes.PUTSTATIC) row("WRITE_" + opcode, owner, member, type);
                    }
                    @Override public void visitInvokeDynamicInsn(String member, String type, Handle bootstrap, Object... arguments) {
                        for (Object arg : arguments) if (arg instanceof Handle handle && external(handle.getOwner()))
                            row("DYNAMIC_HANDLE_" + handle.getTag(), handle.getOwner(), handle.getName(), handle.getDesc());
                    }
                };
            }
        }, ClassReader.SKIP_FRAMES);
    }
    public static void main(String[] args) throws IOException {
        if (args.length < 3) throw new IllegalArgumentException("output.tsv source-classes baritone.jar");
        for (int i = 1; i < args.length; i++) {
            Path path = Path.of(args[i]);
            String artifact = i == 1 ? "controlled-altoclef" : "pinned-baritone";
            if (Files.isDirectory(path)) {
                try (var paths = Files.walk(path)) {
                    for (Path file : paths.filter(p -> p.toString().endsWith(".class")).sorted().toList()) scan(artifact, Files.readAllBytes(file));
                }
            } else {
                try (var zip = new ZipFile(path.toFile())) {
                    for (ZipEntry entry : Collections.list(zip.entries()).stream().filter(e -> e.getName().endsWith(".class")).sorted(Comparator.comparing(ZipEntry::getName)).toList()) {
                        if (entry.getSize() > 8 * 1024 * 1024) throw new IllegalArgumentException("Class size limit");
                        try (InputStream stream = zip.getInputStream(entry)) { scan(artifact, stream.readNBytes(8 * 1024 * 1024 + 1)); }
                    }
                }
            }
        }
        Path output = Path.of(args[0]); Files.createDirectories(output.getParent());
        List<String> lines = new ArrayList<>();
        lines.add("artifact\tclass\tmethod\tline\tordinal\tkind\towner\tmember\tdescriptor\tstatus"); lines.addAll(ROWS);
        Files.write(output, lines, StandardCharsets.UTF_8);
        System.out.println("Static inventory: " + classes + " classes; " + ROWS.size() + " unreviewed sites. No runtime authorization.");
    }
}
