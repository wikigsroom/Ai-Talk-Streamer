package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.ControlArbiter;
import dev.aitalkstreamer.mc.survival.audit.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;

/** Actual bytecode/compiler, original scope, arbiter and input owner; Minecraft is an explicit API double. */
class MovementPolicyGateTest {
    @TempDir static Path temporary;
    static Map<String,byte[]> doubles;
    SneakGateTest nativeInput;Class<?> writer,motionType;Object motion;
    @BeforeAll static void compileDoubles() throws Exception {doubles=SneakGateTest.compileDoubles(temporary);}
    static byte[] writerBytes() throws Exception {
        ClassWriter bytes=new ClassWriter(ClassWriter.COMPUTE_MAXS);
        bytes.visit(Opcodes.V21,Opcodes.ACC_PUBLIC,"fixture/MovementPolicyWriter",null,"java/lang/Object",null);
        GatePolicy policy=GatePolicy.read(Path.of("gate-policy.json"));
        var rows=new com.google.gson.Gson().fromJson(Files.readString(Path.of("gate-policy.json")),com.google.gson.JsonObject.class).getAsJsonArray("rules");
        for(var element:rows){var row=element.getAsJsonObject();String relay=row.get("relay").getAsString();
            if(!relay.startsWith("motion_")&&!relay.startsWith("policy_")&&!relay.equals("movement"))continue;
            String owner=row.get("owner").getAsString(),name=row.get("name").getAsString(),descriptor=row.get("descriptor").getAsString();
            boolean field=row.get("kind").getAsString().equals("FIELD");
            Type result=field?Type.VOID_TYPE:Type.getReturnType(descriptor);
            List<Type> arguments=new ArrayList<>();arguments.add(Type.getObjectType(owner));
            arguments.addAll(Arrays.asList(field?new Type[]{Type.getType(descriptor)}:Type.getArgumentTypes(descriptor)));
            GeneratorAdapter method=new GeneratorAdapter(Opcodes.ACC_PUBLIC|Opcodes.ACC_STATIC,
                    new Method(relay,Type.getMethodDescriptor(result,arguments.toArray(Type[]::new))),null,null,bytes);
            method.loadArgs();
            if(field)method.visitFieldInsn(Opcodes.PUTFIELD,owner,name,descriptor);
            else method.visitMethodInsn(Opcodes.INVOKEVIRTUAL,owner,name,descriptor,false);
            method.returnValue();method.endMethod();
        }
        bytes.visitEnd();return BytecodeGate.transform(bytes.toByteArray(),policy).bytes();
    }
    @BeforeEach void prepare() throws Exception {
        nativeInput=new SneakGateTest();nativeInput.prepare(doubles);nativeInput.open();
        byte[] bytes=writerBytes();writer=new ClassLoader(nativeInput.loader){Class<?> define(){return defineClass(null,bytes,0,bytes.length);}}.define();
        motionType=nativeInput.loader.loadClass("baritone.utils.PlayerMovementInput");motion=motionType.getConstructor().newInstance();
        var install=writer.getMethod("movement",nativeInput.player().getClass(),nativeInput.inputType);
        nativeInput.run(()->SneakGateTest.invoke(install,null,nativeInput.uncheckedPlayer(),motion));
    }
    @AfterEach void cleanup() throws Exception {nativeInput.close();}
    void write(String field,Object value) {
        try{SneakGateTest.invoke(writer.getMethod("motion_"+field,motionType,field.startsWith("movement")?float.class:boolean.class),null,motion,value);}
        catch(ReflectiveOperationException error){throw new IllegalStateException(error);}
    }
    @ParameterizedTest(name="{displayName} [{index}] {arguments}") @ValueSource(strings={"movementForward","movementSideways","pressingForward","pressingBack","pressingLeft","pressingRight","jumping","sneaking"})
    void allEightMovementFieldsReachTheOriginalNativeOwner(String field) throws Exception {
        Object value=field.startsWith("movement")?Float.valueOf(-0.5f):Boolean.FALSE;
        nativeInput.run(()->write(field,value));assertEquals(value,nativeInput.inputType.getField(field).get(motion));
        nativeInput.close();assertSame(nativeInput.input,nativeInput.player().getClass().getField("input").get(nativeInput.player()));
    }
    @ParameterizedTest(name="{displayName} [{index}] {arguments}") @ValueSource(strings={"movementForward","movementSideways","pressingForward","pressingBack","pressingLeft","pressingRight","jumping","sneaking"})
    void allEightFieldsRejectDetachedObjectsEvenInsideTheCurrentRoot(String field) throws Exception {
        Object detached=motionType.getConstructor().newInstance();nativeInput.player().getClass().getField("input").set(nativeInput.player(),detached);
        Object before=nativeInput.inputType.getField(field).get(motion),value=field.startsWith("movement")?Float.valueOf(1):Boolean.FALSE;
        assertThrows(RuntimeException.class,()->nativeInput.run(()->write(field,value)));
        assertEquals(before,nativeInput.inputType.getField(field).get(motion));nativeInput.close();
        assertSame(detached,nativeInput.player().getClass().getField("input").get(nativeInput.player()));
    }
    @Test void anActiveInputNotInstalledByThisOwnerCannotBorrowItsPermit() throws Exception {
        nativeInput.ownerType.getMethod("release").invoke(nativeInput.owner);
        nativeInput.player().getClass().getField("input").set(nativeInput.player(),motion);
        assertThrows(RuntimeException.class,()->nativeInput.run(()->write("movementForward",1f)));
        assertEquals(0f,nativeInput.inputType.getField("movementForward").getFloat(motion));
    }
    @ParameterizedTest @ValueSource(floats={Float.NaN,Float.POSITIVE_INFINITY,Float.NEGATIVE_INFINITY,1.01f,-1.01f})
    void nonFiniteOrUnboundedAxesNeverReachTheOwnedInput(float value) throws Exception {
        assertThrows(RuntimeException.class,()->nativeInput.run(()->write("movementForward",value)));
        assertEquals(0f,nativeInput.inputType.getField("movementForward").getFloat(motion));
    }
    @Test void revokedAndPreviousRootsCannotWriteTheNextMovementInput() throws Exception {
        Object old=nativeInput.session;nativeInput.control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY);
        assertThrows(RuntimeException.class,()->nativeInput.run(()->write("movementForward",1f)));nativeInput.close();
        assertSame(nativeInput.input,nativeInput.player().getClass().getField("input").get(nativeInput.player()));
        assertThrows(RuntimeException.class,()->SneakGateTest.invoke(nativeInput.authority.getMethod("run",nativeInput.sessionType,Runnable.class),null,old,(Runnable)()->write("movementForward",1f)));
    }
    @Test void aForeignThreadCannotBorrowTheMovementScope() throws Exception {
        var failure=new AtomicReference<Throwable>();Thread thread=new Thread(()->{try{nativeInput.run(()->write("movementForward",1f));}catch(Throwable error){failure.set(error);}});
        thread.start();thread.join();assertNotNull(failure.get());assertEquals(0f,nativeInput.inputType.getField("movementForward").getFloat(motion));
    }
    Object policy(String operation,Object subject,Object... values) {
        try{
            Class<?> type=switch(operation){case "chatCommand","chatMessage"->nativeInput.loader.loadClass("net.minecraft.client.network.ClientPlayNetworkHandler");
                case "disconnect"->nativeInput.loader.loadClass("net.minecraft.world.World");case "grounded"->nativeInput.loader.loadClass("net.minecraft.entity.player.PlayerAbilities");
                default->nativeInput.loader.loadClass("net.minecraft.client.network.ClientPlayerEntity");};
            Class<?>[] parameters=values.length==0?new Class<?>[]{type}:new Class<?>[]{type,operation.equals("grounded")?boolean.class:String.class};
            Object[] arguments=new Object[values.length+1];arguments[0]=subject;System.arraycopy(values,0,arguments,1,values.length);
            return SneakGateTest.invoke(writer.getMethod("policy_"+operation,parameters),null,arguments);
        }catch(ReflectiveOperationException error){throw new IllegalStateException(error);}
    }
    @ParameterizedTest @ValueSource(strings={"chatCommand","chatMessage","fallFlying","respawn","disconnect"})
    void fixedSurvivalRootsCannotIssueChatCommandsOrChangePlayerLifecycle(String operation) throws Exception {
        Object subject=switch(operation){case "chatCommand","chatMessage"->nativeInput.clientType.getField("network").get(nativeInput.client);
            case "disconnect"->nativeInput.clientType.getField("world").get(nativeInput.client);default->nativeInput.player();};
        assertThrows(RuntimeException.class,()->nativeInput.run(()->{
            if(operation.startsWith("chat"))policy(operation,subject,"fixture");else policy(operation,subject);
        }));assertEquals(0,subject.getClass().getField("effects").getInt(subject));
    }
    Object abilities() throws Exception {return nativeInput.player().getClass().getMethod("getAbilities").invoke(nativeInput.player());}
    @Test void groundNavigationConfirmsFalseWithoutChangingFlightCapabilities() throws Exception {
        Object abilities=abilities();nativeInput.run(()->policy("grounded",abilities,false));
        assertFalse(abilities.getClass().getField("flying").getBoolean(abilities));
    }
    @Test void requestingFlightOrDisablingExistingHumanFlightIsRejected() throws Exception {
        Object abilities=abilities();assertThrows(RuntimeException.class,()->nativeInput.run(()->policy("grounded",abilities,true)));
        abilities.getClass().getField("flying").setBoolean(abilities,true);
        assertThrows(RuntimeException.class,()->nativeInput.run(()->policy("grounded",abilities,false)));
        assertTrue(abilities.getClass().getField("flying").getBoolean(abilities));
    }
    @Test void groundNavigationRequiresTheActualCurrentPlayersAbilities() throws Exception {
        Object foreign=abilities().getClass().getConstructor().newInstance();assertThrows(RuntimeException.class,()->nativeInput.run(()->policy("grounded",foreign,false)));
    }
    @Test void allSelectedProductionEffectsNowHaveExplicitTypedRoutes() throws Exception {
        var json=com.google.gson.JsonParser.parseString(Files.readString(Path.of("gate-policy.json"))).getAsJsonObject();
        assertEquals(38,json.getAsJsonArray("rules").size());for(var row:json.getAsJsonArray("rules"))assertTrue(row.getAsJsonObject().has("relay"));
    }
}
