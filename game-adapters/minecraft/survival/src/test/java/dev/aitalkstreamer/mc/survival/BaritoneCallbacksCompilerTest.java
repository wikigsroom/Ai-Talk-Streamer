package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.ControlArbiter;
import dev.aitalkstreamer.mc.survival.audit.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import javax.tools.ToolProvider;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

/** Real pinned bytes are verified without initialization; executable path fixtures contain no game. */
public class BaritoneCallbacksCompilerTest {
    private static final String PATH="baritone/behavior/PathingBehavior",INPUT="baritone/utils/PlayerMovementInput",EVENTS="baritone/event/GameEventHandler";
    private static final BaritoneCallbacksCompiler.Symbols NAMED=BaritoneCallbacksCompiler.Symbols.named();
    @TempDir static Path temporary;
    private static Map<String,byte[]> fixtureClasses;
    private SurvivalAuthority.Session session;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private static byte[] resource(String name) throws IOException {
        try(var stream=BaritoneCallbacksCompilerTest.class.getClassLoader().getResourceAsStream(name+".class")){assertNotNull(stream,name);return stream.readAllBytes();}
    }
    private static ClassNode node(byte[] bytes) {var node=new ClassNode();new ClassReader(bytes).accept(node,ClassReader.EXPAND_FRAMES);return node;}
    @BeforeAll static void prepareExecutableFixture() throws IOException {
        // Deliberately fake API types. No Minecraft classes or client are used by this compilation.
        Map<String,String> sources=new LinkedHashMap<>();
        sources.put("net/minecraft/util/math/BlockPos","package net.minecraft.util.math; public class BlockPos {}");
        sources.put("baritone/api/pathing/goals/Goal","package baritone.api.pathing.goals; public interface Goal {}");
        sources.put("baritone/pathing/movement/CalculationContext","package baritone.pathing.movement; public class CalculationContext {}");
        sources.put("baritone/api/utils/PathCalculationResult","package baritone.api.utils; public class PathCalculationResult {}");
        sources.put("baritone/pathing/calc/AbstractNodeCostSearch","""
            package baritone.pathing.calc;
            public class AbstractNodeCostSearch {
                public int calculations; public Thread calculationThread;
                public baritone.api.utils.PathCalculationResult calculate(long first,long second) {
                    calculations++;calculationThread=Thread.currentThread();return new baritone.api.utils.PathCalculationResult();
                }
            }
            """);
        sources.put(PATH,"""
            package baritone.behavior;
            import java.util.concurrent.*;
            import baritone.pathing.calc.AbstractNodeCostSearch;
            import baritone.pathing.movement.CalculationContext;
            import baritone.api.pathing.goals.Goal;
            import net.minecraft.util.math.BlockPos;
            public class PathingBehavior {
                public AbstractNodeCostSearch inProgress;
                public final LinkedBlockingQueue<Object> toDispatch=new LinkedBlockingQueue<>();
                private final Object pathPlanLock=new Object();
                public final Executor executor; public int applied;public Thread applyThread;
                public PathingBehavior(Executor executor){this.executor=executor;}
                public void findPathInNewThread(BlockPos start,boolean log,CalculationContext context) {
                    AbstractNodeCostSearch original=inProgress;
                    executor.execute(()->lambda$findPathInNewThread$2(log,start,null,original,10L,20L));
                }
                private void lambda$findPathInNewThread$2(boolean log,BlockPos start,Goal goal,AbstractNodeCostSearch search,long first,long second) {
                    var result=search.calculate(first,second);
                    synchronized(pathPlanLock) {
                        if(result!=null){applied++;applyThread=Thread.currentThread();inProgress=null;}
                    }
                }
            }
            """);
        List<String> args=new ArrayList<>(List.of("--release","21","-encoding","UTF-8","-classpath","","-g","-d",temporary.resolve("classes").toString()));
        for(var source:sources.entrySet()){Path file=temporary.resolve("src/"+source.getKey()+".java");Files.createDirectories(file.getParent());Files.writeString(file,source.getValue());args.add(file.toString());}
        var errors=new ByteArrayOutputStream();assertEquals(0,ToolProvider.getSystemJavaCompiler().run(null,errors,errors,args.toArray(String[]::new)),errors.toString());
        fixtureClasses=new HashMap<>();try(var paths=Files.walk(temporary.resolve("classes"))){for(Path p:paths.filter(Files::isRegularFile).toList())fixtureClasses.put(temporary.resolve("classes").relativize(p).toString().replace(File.separatorChar,'/').replace(".class",""),Files.readAllBytes(p));}
    }
    @BeforeEach void setup() {
        var c=new ControlArbiter(()->10000,()->{});c.world("world");c.attach("controller");c.release(c.epoch(),()->{});c.observe(1);c.beginAuto("controller","world",c.epoch(),true);c.grant("controller",c.lease(),c.epoch(),1,c.heartbeat(),10000);
        var p=c.permit();session=SurvivalAuthority.open(new SurvivalAuthority.Context("task",p.controller(),p.lease(),p.world(),p.epoch()),new ArbiterBoundary(c,p,"task"));
    }
    @AfterEach void cleanup() throws InterruptedException {session.close(()->{},()->{});worker.shutdownNow();assertTrue(worker.awaitTermination(3,TimeUnit.SECONDS));}
    private ClassLoader fixtureLoader() {
        return new ClassLoader(getClass().getClassLoader()) {
            @Override protected Class<?> loadClass(String name,boolean resolve) throws ClassNotFoundException {
                String path=name.replace('.','/');if(!fixtureClasses.containsKey(path))return super.loadClass(name,resolve);
                synchronized(getClassLoadingLock(name)){Class<?> type=findLoadedClass(name);if(type==null){byte[] b=fixtureClasses.get(path);if(path.equals(PATH))b=BaritoneCallbacksCompiler.transform(b,NAMED).bytes();type=defineClass(name,b,0,b.length);}if(resolve)resolveClass(type);return type;}
            }
        };
    }
    private record Fixture(Object path,Object search,ClassLoader loader) { }
    private Fixture fixture() throws Exception {
        var loader=fixtureLoader();Object path=loader.loadClass(PATH.replace('/','.')).getConstructor(Executor.class).newInstance(worker);
        Object search=loader.loadClass("baritone.pathing.calc.AbstractNodeCostSearch").getConstructor().newInstance();path.getClass().getField("inProgress").set(path,search);return new Fixture(path,search,loader);
    }
    private void submit(Fixture f) {
        SurvivalAuthority.run(session,()->{
            try{f.path.getClass().getMethod("findPathInNewThread",f.loader.loadClass("net.minecraft.util.math.BlockPos"),boolean.class,f.loader.loadClass("baritone.pathing.movement.CalculationContext")).invoke(f.path,null,false,null);}
            catch(InvocationTargetException e){throw new AssertionError(e.getCause());}catch(ReflectiveOperationException e){throw new AssertionError(e);}
        });
    }
    private void barrier() throws Exception {worker.submit(()->{}).get(3,TimeUnit.SECONDS);}
    private static Object field(Object object,String name) throws ReflectiveOperationException {return object.getClass().getField(name).get(object);}
    @Test void actualPinnedClassesHaveSeventeenEventThreeInputAndThreePathTransforms() throws IOException {
        assertEquals(17,BaritoneCallbacksCompiler.transform(resource(EVENTS),NAMED).sites().size());
        assertEquals(3,BaritoneCallbacksCompiler.transform(resource(INPUT),NAMED).sites().size());
        assertEquals(3,BaritoneCallbacksCompiler.transform(resource(PATH),NAMED).sites().size());
    }
    @Test void actualTransformedClassesPassJvmVerificationWithoutInitializingTheGame() throws Exception {
        var policy=GatePolicy.read(Path.of("gate-policy.json"));
        ClassLoader loader=new ClassLoader(getClass().getClassLoader()) {
            @Override protected Class<?> loadClass(String name,boolean resolve) throws ClassNotFoundException {
                if(!name.startsWith("baritone."))return super.loadClass(name,resolve);
                synchronized(getClassLoadingLock(name)){Class<?> type=findLoadedClass(name);if(type==null){try{byte[] bytes=resource(name.replace('.','/'));bytes=BytecodeGate.transform(bytes,policy).bytes();bytes=BaritoneCallbacksCompiler.transform(bytes,NAMED).bytes();type=defineClass(name,bytes,0,bytes.length);}catch(IOException e){throw new ClassNotFoundException(name,e);}}if(resolve)resolveClass(type);return type;}
            }
        };
        for(String name:List.of(EVENTS,INPUT,PATH))assertTrue(loader.loadClass(name.replace('/','.')).getDeclaredMethods().length>0);
    }
    @Test void workerHasNoPathStateWritesAndCommitChecksTheIdenticalSearch() throws IOException {
        var c=node(BaritoneCallbacksCompiler.transform(resource(PATH),NAMED).bytes());
        var worker=c.methods.stream().filter(m->m.name.equals("lambda$findPathInNewThread$2")).findFirst().orElseThrow();
        assertFalse(Arrays.stream(worker.instructions.toArray()).anyMatch(n->n.getOpcode()==Opcodes.PUTFIELD||n.getOpcode()==Opcodes.MONITORENTER));
        var commit=c.methods.stream().filter(m->m.name.equals("$ats$callback$pathCommit")).findFirst().orElseThrow();
        assertTrue(Arrays.stream(commit.instructions.toArray()).anyMatch(n->n instanceof JumpInsnNode && n.getOpcode()==Opcodes.IF_ACMPEQ));
        assertFalse(commit.tryCatchBlocks.isEmpty());
    }
    @Test void executableSplitCalculatesOnWorkerAndAppliesOnceOnClient() throws Exception {
        var f=fixture();submit(f);barrier();assertEquals(1,field(f.search,"calculations"));assertNotSame(Thread.currentThread(),field(f.search,"calculationThread"));assertEquals(0,field(f.path,"applied"));
        SurvivalAuthority.run(session,SurvivalAsync::drain);assertEquals(1,field(f.path,"applied"));assertSame(Thread.currentThread(),field(f.path,"applyThread"));SurvivalAuthority.run(session,SurvivalAsync::drain);assertEquals(1,field(f.path,"applied"));
    }
    @Test void sameRootReplanRejectsTheOldSearchAndDoesNotClearTheReplacement() throws Exception {
        var f=fixture();submit(f);barrier();Object replacement=f.search.getClass().getConstructor().newInstance();f.path.getClass().getField("inProgress").set(f.path,replacement);
        SurvivalAuthority.run(session,SurvivalAsync::drain);assertEquals(0,field(f.path,"applied"));assertSame(replacement,field(f.path,"inProgress"));
    }
    @Test void taskCloseDiscardsTheCompiledWorkerResultWithoutApplyingIt() throws Exception {
        var f=fixture();submit(f);barrier();session.close(()->{},()->{});assertEquals(0,field(f.path,"applied"));
    }
    @Test void compiledPathEventQueueCanOnlyBeClearedInItsOwnerScope() throws Exception {
        var f=fixture();@SuppressWarnings("unchecked") var queue=(Queue<Object>)field(f.path,"toDispatch");queue.add("old-event");
        var reset=(SurvivalCallbacks.RootResettable)f.path;assertThrows(SurvivalAuthority.Denied.class,reset::atsClearRootEvents);
        session.close(()->{},reset::atsClearRootEvents);assertTrue(queue.isEmpty());
    }
    @Test void changedResultLocalFailsClosedRatherThanGuessingANewShape() throws IOException {
        var c=node(resource(PATH));var m=c.methods.stream().filter(v->v.name.equals("lambda$findPathInNewThread$2")).findFirst().orElseThrow();
        for(AbstractInsnNode n:m.instructions.toArray())if(n instanceof MethodInsnNode call&&call.name.equals("calculate")){((VarInsnNode)call.getNext()).var=10;break;}
        var out=new ClassWriter(0);c.accept(out);assertThrows(IllegalArgumentException.class,()->BaritoneCallbacksCompiler.transform(out.toByteArray(),NAMED));
    }
    @Test void transformingAnAlreadyCompiledClassIsRejected() throws IOException {
        byte[] once=BaritoneCallbacksCompiler.transform(resource(EVENTS),NAMED).bytes();assertThrows(IllegalArgumentException.class,()->BaritoneCallbacksCompiler.transform(once,NAMED));
    }
    @Test void neutralizationFieldOrderDoesNotDependOnMapInsertionOrder() throws IOException {
        Map<String,String> reverse=new LinkedHashMap<>();NAMED.fields().keySet().stream().sorted(Comparator.reverseOrder()).forEach(k->reverse.put(k,k));
        var other=new BaritoneCallbacksCompiler.Symbols(NAMED.mcInput(),NAMED.blockPos(),NAMED.tick(),reverse);
        assertArrayEquals(BaritoneCallbacksCompiler.transform(resource(INPUT),NAMED).bytes(),BaritoneCallbacksCompiler.transform(resource(INPUT),other).bytes());
    }
}
