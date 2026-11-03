package dev.aitalkstreamer.mc.survival.audit;

import org.objectweb.asm.*;
import org.objectweb.asm.commons.*;
import org.objectweb.asm.tree.*;
import java.io.IOException;
import java.nio.file.*;
import java.util.*;

/** Pinned Baritone-only lifecycle compiler. No client classes are loaded during compilation. */
public final class BaritoneCallbacksCompiler {
    private static final String HOOKS = "dev/aitalkstreamer/mc/survival/SurvivalCallbacks";
    private static final String ASYNC = "dev/aitalkstreamer/mc/survival/SurvivalAsync";
    private static final String BINDING = HOOKS + "$Binding";
    private static final String PREFIX = "$ats$callback$";
    private static final String INPUT = "baritone/utils/PlayerMovementInput";
    private static final String EVENTS = "baritone/event/GameEventHandler";
    private static final String PATH = "baritone/behavior/PathingBehavior";
    private static final String SEARCH = "baritone/pathing/calc/AbstractNodeCostSearch";
    private static final String RESULT = "baritone/api/utils/PathCalculationResult";
    private static final Handle LAMBDA = new Handle(Opcodes.H_INVOKESTATIC, "java/lang/invoke/LambdaMetafactory", "metafactory",
            "(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodHandle;Ljava/lang/invoke/MethodType;)Ljava/lang/invoke/CallSite;", false);
    public record Site(String origin, String method, String route) { }
    public record Result(byte[] bytes, List<Site> sites) { }
    public record Symbols(String mcInput, String blockPos, String tick, Map<String,String> fields) {
        public static Symbols named() {
            Map<String,String> fields = new LinkedHashMap<>();
            for (String n : List.of("movementSideways","movementForward","pressingForward","pressingBack","pressingLeft","pressingRight","jumping","sneaking")) fields.put(n,n);
            return new Symbols("net/minecraft/client/input/Input", "net/minecraft/util/math/BlockPos", "tick", Map.copyOf(fields));
        }
        public static Symbols intermediary(Path mapping) throws IOException {
            String owner = null, input = null, pos = null, tick = null; Map<String,String> fields = new HashMap<>();
            for (String line : Files.readAllLines(mapping)) {
                String[] c = line.split("\t", -1);
                if (line.startsWith("c\t")) {
                    owner = c[2];
                    if (owner.equals("net/minecraft/client/input/Input")) input = c[1];
                    if (owner.equals("net/minecraft/util/math/BlockPos")) pos = c[1];
                } else if ("net/minecraft/client/input/Input".equals(owner)) {
                    if (line.startsWith("\tf\t")) fields.put(c[4],c[3]);
                    if (line.startsWith("\tm\t") && c[4].equals("tick") && c[2].equals("(ZF)V")) tick = c[3];
                }
            }
            if (input == null || pos == null || tick == null || !fields.keySet().containsAll(named().fields.keySet())) throw new IllegalArgumentException("GAME_CALLBACK_MAPPING");
            return new Symbols(input,pos,tick,Map.copyOf(fields));
        }
    }
    private BaritoneCallbacksCompiler() { }
    private static IllegalArgumentException shape(String detail) { return new IllegalArgumentException("GAME_CALLBACK_PINNED_SHAPE:" + detail); }
    private static MethodNode exact(ClassNode node, String name, String desc) {
        var matches = node.methods.stream().filter(m -> m.name.equals(name) && m.desc.equals(desc)).toList();
        if (matches.size() != 1) throw shape(node.name + ":" + name + desc);
        return matches.getFirst();
    }
    private static GeneratorAdapter code(MethodNode node) { return new GeneratorAdapter(node,node.access,node.name,node.desc); }
    private static MethodNode add(ClassNode node, int access, String name, String desc) {
        MethodNode method = new MethodNode(Opcodes.ASM9,access,name,desc,null,null); node.methods.add(method); return method;
    }
    private static void erase(MethodNode method) {
        method.instructions = new InsnList(); method.tryCatchBlocks = new ArrayList<>(); method.localVariables = null;
    }
    private static void closure(GeneratorAdapter g, String owner, String name, String descriptor) {
        Type[] args = Type.getArgumentTypes(descriptor);
        g.loadThis(); g.loadArgs();
        Type[] captured = new Type[args.length+1]; captured[0]=Type.getObjectType(owner); System.arraycopy(args,0,captured,1,args.length);
        g.invokeDynamic("run",Type.getMethodDescriptor(Type.getType(Runnable.class),captured),LAMBDA,Type.getMethodType("()V"),
                new Handle(Opcodes.H_INVOKESPECIAL,owner,name,descriptor,false),Type.getMethodType("()V"));
    }
    private static void wrap(ClassNode node, MethodNode original, String route, String hook, boolean subject, List<Site> sites) {
        int access=original.access; String name=original.name;
        original.name=PREFIX+name; original.access=(access & ~(Opcodes.ACC_PUBLIC|Opcodes.ACC_PROTECTED))|Opcodes.ACC_PRIVATE|Opcodes.ACC_SYNTHETIC;
        MethodNode wrapper=add(node,access,name,original.desc); GeneratorAdapter g=code(wrapper);
        if (subject) g.loadThis(); closure(g,node.name,original.name,original.desc);
        g.invokeStatic(Type.getObjectType(HOOKS),new Method(hook,subject?"(Ljava/lang/Object;Ljava/lang/Runnable;)V":"(Ljava/lang/Runnable;)V"));
        g.returnValue(); g.endMethod(); sites.add(new Site(node.name,name+original.desc,route));
    }
    public static Result transform(byte[] bytes, Symbols symbols) {
        ClassReader reader = new ClassReader(bytes);
        if (!Set.of(INPUT,EVENTS,PATH).contains(reader.getClassName())) return new Result(bytes,List.of());
        ClassNode node = new ClassNode(); reader.accept(node,ClassReader.EXPAND_FRAMES);
        if (node.methods.stream().anyMatch(m -> m.name.startsWith(PREFIX)) || node.fields.stream().anyMatch(f -> f.name.equals(PREFIX+"binding"))) throw shape("ALREADY_COMPILED");
        List<Site> sites = new ArrayList<>();
        switch(node.name) {
            case EVENTS -> events(node,sites);
            case INPUT -> input(node,symbols,sites);
            case PATH -> path(node,symbols,sites);
            default -> throw new AssertionError();
        }
        ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS); node.accept(writer);
        return new Result(writer.toByteArray(),List.copyOf(sites));
    }
    private static void events(ClassNode node,List<Site> sites) {
        Set<String> active=Set.of("onTick","onPostTick","onPlayerUpdate","onPlayerRotationMove","onPlayerSprintState","onPathEvent","onBlockInteract","onPlayerDeath","onSendPacket","onReceivePacket");
        Set<String> passive=Set.of("onChunkEvent","onBlockChange","onWorldEvent","onRenderPass");
        Set<String> disabled=Set.of("onSendChatMessage","onPreTabComplete");
        Set<String> seen=new HashSet<>();
        for (MethodNode method:new ArrayList<>(node.methods)) {
            if (!active.contains(method.name) && !passive.contains(method.name) && !disabled.contains(method.name)) continue;
            if (!seen.add(method.name) || Type.getReturnType(method.desc)!=Type.VOID_TYPE || (method.access&Opcodes.ACC_STATIC)!=0) throw shape("EVENT_METHOD");
            if (disabled.contains(method.name)) {
                erase(method); GeneratorAdapter g=code(method); g.returnValue(); g.endMethod();
                sites.add(new Site(node.name,method.name+method.desc,"DISABLED_RAW_COMMAND"));
            } else wrap(node,method,active.contains(method.name)?"BOUND_CLIENT_EVENT":"OBSERVATION_WITHOUT_TASK_SCOPE",active.contains(method.name)?"event":"observe",active.contains(method.name),sites);
        }
        if (seen.size()!=16) throw shape("EVENT_SET");
        MethodNode register=exact(node,"registerEventListener","(Lbaritone/api/event/listener/IGameEventListener;)V");
        erase(register); GeneratorAdapter g=code(register); g.loadThis(); g.getField(Type.getObjectType(node.name),"listeners",Type.getType(List.class)); g.loadArg(0);
        g.invokeStatic(Type.getObjectType(HOOKS),new Method("register","(Ljava/util/List;Lbaritone/api/event/listener/IGameEventListener;)V")); g.returnValue();g.endMethod();
        sites.add(new Site(node.name,register.name+register.desc,"TASK_LISTENER_RETIREMENT"));
    }
    private static void input(ClassNode node,Symbols symbols,List<Site> sites) {
        if (!node.superName.equals(symbols.mcInput)) throw shape("INPUT_PARENT");
        MethodNode constructor=exact(node,"<init>","(Lbaritone/utils/InputOverrideHandler;)V");
        node.fields.add(new FieldNode(Opcodes.ACC_PRIVATE|Opcodes.ACC_FINAL|Opcodes.ACC_SYNTHETIC,PREFIX+"binding","L"+BINDING+";",null,null));
        int returns=0;
        for (AbstractInsnNode insn:constructor.instructions.toArray()) if (insn.getOpcode()==Opcodes.RETURN) {
            InsnList set=new InsnList(); set.add(new VarInsnNode(Opcodes.ALOAD,0));set.add(new VarInsnNode(Opcodes.ALOAD,0));
            set.add(new MethodInsnNode(Opcodes.INVOKESTATIC,HOOKS,"capture","(Ljava/lang/Object;)L"+BINDING+";",false));
            set.add(new FieldInsnNode(Opcodes.PUTFIELD,node.name,PREFIX+"binding","L"+BINDING+";")); constructor.instructions.insertBefore(insn,set);returns++;
        }
        if(returns!=1) throw shape("INPUT_CONSTRUCTOR");
        sites.add(new Site(node.name,constructor.name+constructor.desc,"IMMUTABLE_INPUT_BINDING"));
        MethodNode tick=exact(node,symbols.tick,"(ZF)V");int access=tick.access;tick.name=PREFIX+"inputTick";tick.access=Opcodes.ACC_PRIVATE|Opcodes.ACC_SYNTHETIC;
        MethodNode zero=add(node,Opcodes.ACC_PRIVATE|Opcodes.ACC_SYNTHETIC,PREFIX+"zero","()V");GeneratorAdapter z=code(zero);
        for(var field:new TreeMap<>(symbols.fields).entrySet()) {
            z.loadThis();boolean floating=field.getKey().startsWith("movement"); if(floating)z.push(0F);else z.push(false);
            z.putField(Type.getObjectType(symbols.mcInput),field.getValue(),floating?Type.FLOAT_TYPE:Type.BOOLEAN_TYPE);
        }
        z.returnValue();z.endMethod();
        MethodNode wrapper=add(node,access,symbols.tick,"(ZF)V");GeneratorAdapter g=code(wrapper);
        g.loadThis();g.loadThis();g.getField(Type.getObjectType(node.name),PREFIX+"binding",Type.getObjectType(BINDING));closure(g,node.name,tick.name,tick.desc);
        g.loadThis();g.invokeDynamic("run","(L"+node.name+";)Ljava/lang/Runnable;",LAMBDA,Type.getMethodType("()V"),new Handle(Opcodes.H_INVOKESPECIAL,node.name,zero.name,zero.desc,false),Type.getMethodType("()V"));
        g.invokeStatic(Type.getObjectType(HOOKS),new Method("input","(Ljava/lang/Object;L"+BINDING+";Ljava/lang/Runnable;Ljava/lang/Runnable;)V"));g.returnValue();g.endMethod();
        sites.add(new Site(node.name,symbols.tick+"(ZF)V","ORIGINAL_INPUT_TICK"));
        sites.add(new Site(node.name,zero.name+zero.desc,"ORIGINAL_OBJECT_NEUTRALIZATION_8_FIELDS"));
    }
    private static void path(ClassNode node,Symbols symbols,List<Site> sites) {
        String descriptor="(ZL"+symbols.blockPos+";Lbaritone/api/pathing/goals/Goal;L"+SEARCH+";JJ)V";
        MethodNode worker=exact(node,"lambda$findPathInNewThread$2",descriptor);
        MethodNode submit=exact(node,"findPathInNewThread","(L"+symbols.blockPos+";ZLbaritone/pathing/movement/CalculationContext;)V");
        int submissions=0;
        for(AbstractInsnNode insn:submit.instructions.toArray()) if(insn instanceof MethodInsnNode call && call.owner.equals("java/util/concurrent/Executor") && call.name.equals("execute") && call.desc.equals("(Ljava/lang/Runnable;)V")) {
            submit.instructions.set(call,new MethodInsnNode(Opcodes.INVOKESTATIC,ASYNC,"execute","(Ljava/util/concurrent/Executor;Ljava/lang/Runnable;)V",false));submissions++;
        }
        if(submissions!=1) throw shape("PATH_SUBMISSION");
        sites.add(new Site(node.name,submit.name+submit.desc,"CAPTURE_CALCULATION_ROOT"));
        MethodInsnNode calculate=null;
        for(AbstractInsnNode insn:worker.instructions.toArray()) if(insn instanceof MethodInsnNode call && call.owner.equals(SEARCH) && call.name.equals("calculate") && call.desc.equals("(JJ)L"+RESULT+";")) {
            if(calculate!=null)throw shape("CALCULATE_COUNT");calculate=call;
        }
        if(calculate==null || !(calculate.getNext() instanceof VarInsnNode store) || store.getOpcode()!=Opcodes.ASTORE || store.var!=9) throw shape("RESULT_LOCAL");
        AbstractInsnNode after=calculate.getNext().getNext();
        Set<AbstractInsnNode> tailNodes=Collections.newSetFromMap(new IdentityHashMap<>());
        for(AbstractInsnNode insn=after;insn!=null;insn=insn.getNext())tailNodes.add(insn);
        for(TryCatchBlockNode block:worker.tryCatchBlocks) if(!tailNodes.containsAll(List.of(block.start,block.end,block.handler)))throw shape("CROSS_BOUNDARY_HANDLER");
        String commitDesc=descriptor.substring(0,descriptor.length()-2)+"L"+RESULT+";)V";
        MethodNode commit=add(node,Opcodes.ACC_PRIVATE|Opcodes.ACC_SYNTHETIC,PREFIX+"pathCommit",commitDesc);
        while(worker.instructions.getFirst()!=after)worker.instructions.remove(worker.instructions.getFirst());
        commit.instructions=worker.instructions;commit.tryCatchBlocks=worker.tryCatchBlocks;commit.maxLocals=worker.maxLocals;commit.maxStack=worker.maxStack;
        erase(worker);
        // Same-root replans also require the identical search object before applying a result.
        InsnList guard=new InsnList();LabelNode accepted=new LabelNode();
        guard.add(new VarInsnNode(Opcodes.ALOAD,0));guard.add(new FieldInsnNode(Opcodes.GETFIELD,node.name,"inProgress","L"+SEARCH+";"));guard.add(new VarInsnNode(Opcodes.ALOAD,4));
        guard.add(new JumpInsnNode(Opcodes.IF_ACMPEQ,accepted));guard.add(new InsnNode(Opcodes.RETURN));guard.add(accepted);
        guard.add(new FrameNode(Opcodes.F_NEW,8,new Object[]{node.name,Opcodes.INTEGER,symbols.blockPos,"baritone/api/pathing/goals/Goal",SEARCH,Opcodes.LONG,Opcodes.LONG,RESULT},0,new Object[]{}));
        commit.instructions.insert(guard);
        GeneratorAdapter g=code(worker);g.loadThis();g.loadArgs();g.loadArg(3);g.loadArg(4);g.loadArg(5);
        g.invokeVirtual(Type.getObjectType(SEARCH),new Method("calculate","(JJ)L"+RESULT+";"));
        Type[] captured=Type.getArgumentTypes("(L"+node.name+";"+commitDesc.substring(1));
        g.invokeDynamic("run",Type.getMethodDescriptor(Type.getType(Runnable.class),captured),LAMBDA,Type.getMethodType("()V"),new Handle(Opcodes.H_INVOKESPECIAL,node.name,commit.name,commitDesc,false),Type.getMethodType("()V"));
        g.invokeStatic(Type.getObjectType(ASYNC),new Method("commit","(Ljava/lang/Runnable;)V"));g.returnValue();g.endMethod();
        sites.add(new Site(node.name,worker.name+worker.desc,"WORKER_CALCULATE_CLIENT_COMMIT_SAME_SEARCH"));
        if(node.interfaces.contains(HOOKS+"$RootResettable") || node.methods.stream().anyMatch(m->m.name.equals("atsClearRootEvents")))throw shape("RESET_INTERFACE");
        node.interfaces.add(HOOKS+"$RootResettable");MethodNode reset=add(node,Opcodes.ACC_PUBLIC|Opcodes.ACC_SYNTHETIC,"atsClearRootEvents","()V");GeneratorAdapter r=code(reset);
        r.invokeStatic(Type.getObjectType("dev/aitalkstreamer/mc/survival/SurvivalAuthority"),new Method("requireOwnerScope","()V"));
        r.loadThis();r.getField(Type.getObjectType(node.name),"toDispatch",Type.getObjectType("java/util/concurrent/LinkedBlockingQueue"));r.invokeVirtual(Type.getObjectType("java/util/concurrent/LinkedBlockingQueue"),new Method("clear","()V"));r.returnValue();r.endMethod();
        sites.add(new Site(node.name,reset.name+reset.desc,"ORIGINAL_ROOT_EVENT_QUEUE_RESET"));
    }
}
