package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.*;
import dev.aitalkstreamer.mc.survival.audit.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.objectweb.asm.*;
import javax.tools.ToolProvider;
import java.io.*;
import java.lang.reflect.InvocationTargetException;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

/** Real transformed call -> real boundary -> real native input owner and arbiter. MC/GLFW APIs are explicit doubles. */
class SneakGateTest {
    @TempDir static Path temporary;
    static Map<String,byte[]> doubles;
    ClassLoader loader; Class<?> clientType, inputType, authority, sessionType, ownerType, writer, physicalType;
    Object client, input, owner, session; PhysicalKeys physical;
    ControlArbiter control; AtomicLong clock=new AtomicLong(100);
    @BeforeAll static void compileDoubles() throws Exception { doubles=compileDoubles(temporary); }
    static Map<String,byte[]> compileDoubles(Path temporary) throws Exception {
        Map<String,String> sources=new LinkedHashMap<>();
        sources.put("net.minecraft.client.input.Input","package net.minecraft.client.input; public class Input { public boolean sneaking=true,jumping,pressingForward,pressingBack,pressingLeft,pressingRight; public float movementForward,movementSideways; }");
        sources.put("baritone.utils.PlayerMovementInput","package baritone.utils; public class PlayerMovementInput extends net.minecraft.client.input.Input {}");
        sources.put("net.minecraft.entity.player.PlayerAbilities","package net.minecraft.entity.player; public class PlayerAbilities {public boolean flying;}");
        sources.put("net.minecraft.world.World","package net.minecraft.world; public class World { public int effects;public void disconnect(){effects++;} }");
        sources.put("net.minecraft.client.input.KeyboardInput","package net.minecraft.client.input; public class KeyboardInput extends Input {}");
        sources.put("net.minecraft.client.util.InputUtil","""
            package net.minecraft.client.util;
            public class InputUtil {
              public enum Type { MOUSE, KEYSYM, SCANCODE }
              public static class Key { public Type type;public int code;public Key(Type type,int code){this.type=type;this.code=code;}public Type getCategory(){return type;}public int getCode(){return code;} }
              public static boolean held=true,fail;public static int lastCode=-1;
              public static boolean isKeyPressed(long window,int code){lastCode=code;if(fail)throw new IllegalStateException("FIXTURE_PHYSICAL_READ");return held;}
            }
            """);
        sources.put("dev.aitalkstreamer.mc.mixin.KeyBindingAccessor","package dev.aitalkstreamer.mc.mixin; public interface KeyBindingAccessor { net.minecraft.client.util.InputUtil.Key mcBridgeBoundKey(); }");
        sources.put("net.minecraft.client.option.KeyBinding","""
            package net.minecraft.client.option;
            public class KeyBinding implements dev.aitalkstreamer.mc.mixin.KeyBindingAccessor {
              public net.minecraft.client.util.InputUtil.Key key=new net.minecraft.client.util.InputUtil.Key(net.minecraft.client.util.InputUtil.Type.KEYSYM,340);
              public net.minecraft.client.util.InputUtil.Key mcBridgeBoundKey(){return key;}public void setPressed(boolean value){}
            }
            """);
        sources.put("net.minecraft.client.option.GameOptions","package net.minecraft.client.option; public class GameOptions { public KeyBinding useKey=new KeyBinding(),attackKey=new KeyBinding(),sneakKey=new KeyBinding(); }");
        sources.put("net.minecraft.entity.player.PlayerInventory","package net.minecraft.entity.player; public class PlayerInventory {public int selectedSlot;}");
        sources.put("net.minecraft.entity.player.PlayerEntity","package net.minecraft.entity.player; public class PlayerEntity {}");
        sources.put("net.minecraft.client.network.ClientPlayerEntity","""
            package net.minecraft.client.network;
            public class ClientPlayerEntity extends net.minecraft.entity.player.PlayerEntity {
              public net.minecraft.client.input.Input input=new net.minecraft.client.input.KeyboardInput();public boolean alive=true;
              private final net.minecraft.entity.player.PlayerInventory inventory=new net.minecraft.entity.player.PlayerInventory();
              private final net.minecraft.entity.player.PlayerAbilities abilities=new net.minecraft.entity.player.PlayerAbilities();public int effects;
              public boolean isAlive(){return alive;}public boolean isUsingItem(){return false;}
              public net.minecraft.entity.player.PlayerInventory getInventory(){return inventory;}
              public net.minecraft.entity.player.PlayerAbilities getAbilities(){return abilities;}
              public boolean checkFallFlying(){effects++;return true;}public void requestRespawn(){effects++;}
              public void setYaw(float value){}public void setPitch(float value){}
            }
            """);
        sources.put("net.minecraft.client.network.ClientPlayNetworkHandler","package net.minecraft.client.network; public class ClientPlayNetworkHandler {public int effects; public void sendChatMessage(String text){effects++;}public void sendChatCommand(String text){effects++;}}");
        sources.put("net.minecraft.client.network.ClientPlayerInteractionManager","package net.minecraft.client.network; public class ClientPlayerInteractionManager { public void stopUsingItem(net.minecraft.entity.player.PlayerEntity player){} }");
        sources.put("net.minecraft.client.world.ClientWorld","package net.minecraft.client.world; public class ClientWorld extends net.minecraft.world.World {}");
        sources.put("net.minecraft.client.util.Window","package net.minecraft.client.util; public class Window {public long getHandle(){return 1;}}");
        sources.put("net.minecraft.client.MinecraftClient","""
            package net.minecraft.client;
            public class MinecraftClient {
              public static final MinecraftClient INSTANCE=new MinecraftClient();public final Thread thread=Thread.currentThread();
              public net.minecraft.client.world.ClientWorld world=new net.minecraft.client.world.ClientWorld();
              public net.minecraft.client.network.ClientPlayerEntity player=new net.minecraft.client.network.ClientPlayerEntity();
              public net.minecraft.client.network.ClientPlayNetworkHandler network=new net.minecraft.client.network.ClientPlayNetworkHandler();
              public net.minecraft.client.network.ClientPlayerInteractionManager interactionManager=new net.minecraft.client.network.ClientPlayerInteractionManager();
              public net.minecraft.client.option.GameOptions options=new net.minecraft.client.option.GameOptions();public boolean focused=true,paused;
              public static MinecraftClient getInstance(){return INSTANCE;}public boolean isOnThread(){return Thread.currentThread()==thread;}
              public boolean isWindowFocused(){return focused;}public boolean isPaused(){return paused;}
              public net.minecraft.client.network.ClientPlayNetworkHandler getNetworkHandler(){return network;}
              public net.minecraft.client.util.Window getWindow(){return new net.minecraft.client.util.Window();}
            }
            """);
        sources.put("org.lwjgl.glfw.GLFW","package org.lwjgl.glfw; public class GLFW {public static int lastButton=-1;public static int glfwGetMouseButton(long window,int button){lastButton=button;return net.minecraft.client.util.InputUtil.held?1:0;}}");
        List<String> args=new ArrayList<>(List.of("-encoding","UTF-8","-d",temporary.toString()));
        for(var row:sources.entrySet()){Path p=temporary.resolve(row.getKey().replace('.','/')+".java");Files.createDirectories(p.getParent());Files.writeString(p,row.getValue());args.add(p.toString());}
        assertEquals(0,ToolProvider.getSystemJavaCompiler().run(null,null,null,args.toArray(String[]::new)));
        Map<String,byte[]> doubles=new HashMap<>();try(var paths=Files.walk(temporary)){
            for(Path p:paths.filter(v->v.toString().endsWith(".class")).toList())
                doubles.put(temporary.relativize(p).toString().replace(File.separatorChar,'.').replaceAll("\\.class$",""),Files.readAllBytes(p));
        }
        return doubles;
    }
    static byte[] resource(String name) throws IOException {
        try(var input=SneakGateTest.class.getClassLoader().getResourceAsStream(name.replace('.','/')+".class")){assertNotNull(input,name);return input.readAllBytes();}
    }
    static byte[] transformed(int opcode) throws Exception {
        ClassWriter bytes=new ClassWriter(ClassWriter.COMPUTE_MAXS);bytes.visit(Opcodes.V21,Opcodes.ACC_PUBLIC,"fixture/SneakWriter",null,"java/lang/Object",null);
        MethodVisitor method=bytes.visitMethod(Opcodes.ACC_PUBLIC|Opcodes.ACC_STATIC,"set","(Lnet/minecraft/client/input/Input;Z)V",null,null);
        method.visitCode();method.visitVarInsn(Opcodes.ALOAD,0);method.visitVarInsn(Opcodes.ILOAD,1);
        method.visitFieldInsn(opcode,"net/minecraft/client/input/Input","sneaking","Z");method.visitInsn(Opcodes.RETURN);method.visitMaxs(0,0);method.visitEnd();bytes.visitEnd();
        return BytecodeGate.transform(bytes.toByteArray(),GatePolicy.read(Path.of("gate-policy.json"))).bytes();
    }
    @BeforeEach void prepare() throws Exception {prepare(doubles);}
    void prepare(Map<String,byte[]> doubles) throws Exception {
        var definitions=new HashMap<>(doubles);definitions.put("fixture.SneakWriter",transformed(Opcodes.PUTFIELD));
        loader=new ClassLoader(getClass().getClassLoader()){
            @Override protected Class<?> loadClass(String name,boolean resolve) throws ClassNotFoundException {
                boolean own=definitions.containsKey(name)||List.of("dev.aitalkstreamer.mc.InputOwner","dev.aitalkstreamer.mc.survival.SurvivalInputs",
                        "dev.aitalkstreamer.mc.survival.SurvivalAuthority","dev.aitalkstreamer.mc.survival.SurvivalPolicy","dev.aitalkstreamer.mc.survival.ArbiterBoundary")
                        .stream().anyMatch(base->name.equals(base)||name.startsWith(base+"$"));
                if(!own)return super.loadClass(name,resolve);
                synchronized(getClassLoadingLock(name)){Class<?> found=findLoadedClass(name);if(found==null)try{
                    byte[] bytes=definitions.containsKey(name)?definitions.get(name):resource(name);found=defineClass(name,bytes,0,bytes.length);
                }catch(IOException error){throw new ClassNotFoundException(name,error);}if(resolve)resolveClass(found);return found;}
            }
        };
        clientType=loader.loadClass("net.minecraft.client.MinecraftClient");client=clientType.getField("INSTANCE").get(null);
        inputType=loader.loadClass("net.minecraft.client.input.Input");input=player().getClass().getField("input").get(player());
        physicalType=loader.loadClass("net.minecraft.client.util.InputUtil");physical=new PhysicalKeys(1);
        ownerType=loader.loadClass("dev.aitalkstreamer.mc.InputOwner");owner=ownerType.getConstructor(clientType,PhysicalKeys.class).newInstance(client,physical);
        authority=loader.loadClass("dev.aitalkstreamer.mc.survival.SurvivalAuthority");sessionType=loader.loadClass(authority.getName()+"$Session");writer=loader.loadClass("fixture.SneakWriter");
        control=new ControlArbiter(clock::get,()->{});control.world("world");control.attach("controller");control.release(control.epoch(),()->{});control.observe(1);
        control.beginAuto("controller","world",control.epoch(),true);control.grant("controller",control.lease(),control.epoch(),1,control.heartbeat(),3000);
    }
    static Object invoke(java.lang.reflect.Method method,Object receiver,Object... args){try{return method.invoke(receiver,args);}
        catch(InvocationTargetException e){if(e.getCause() instanceof RuntimeException r)throw r;if(e.getCause() instanceof Error r)throw r;throw new IllegalStateException(e.getCause());}
        catch(ReflectiveOperationException e){throw new IllegalStateException(e);}}
    Object player() throws Exception{return clientType.getField("player").get(client);}
    void open() throws Exception {
        var permit=control.permit();Class<?> context=loader.loadClass(authority.getName()+"$Context"),boundary=loader.loadClass(authority.getName()+"$Boundary");
        Object c=context.getConstructor(String.class,String.class,String.class,String.class,long.class).newInstance("task",permit.controller(),permit.lease(),permit.world(),permit.epoch());
        Object b=loader.loadClass("dev.aitalkstreamer.mc.survival.ArbiterBoundary").getConstructor(ControlArbiter.class,ControlArbiter.Permit.class,String.class,ownerType)
                .newInstance(control,permit,"task",owner);
        session=invoke(authority.getMethod("open",context,boundary),null,c,b);
    }
    void run(Runnable action) throws Exception{invoke(authority.getMethod("run",sessionType,Runnable.class),null,session,action);}
    void set(Object target,boolean next){try{invoke(writer.getMethod("set",inputType,boolean.class),null,target,next);}catch(NoSuchMethodException e){throw new IllegalStateException(e);}}
    void close() throws Exception{if(session!=null)invoke(sessionType.getMethod("close",Runnable.class,Runnable.class),session,(Runnable)()->{},(Runnable)()->{});}
    boolean value(Object target) throws Exception{return inputType.getField("sneaking").getBoolean(target);}
    void physical(boolean value) throws Exception{physicalType.getField("held").setBoolean(null,value);}
    @AfterEach void cleanup() throws Exception {physicalType.getField("fail").setBoolean(null,false);close();}

    @Test void transformedFieldWritesUseTheSoleNativeInputOwner() throws Exception {
        List<String> calls=new ArrayList<>();new ClassReader(transformed(Opcodes.PUTFIELD)).accept(new ClassVisitor(Opcodes.ASM9){
            @Override public MethodVisitor visitMethod(int a,String n,String d,String s,String[] e){return new MethodVisitor(Opcodes.ASM9){
                @Override public void visitFieldInsn(int op,String o,String n,String d){assertNotEquals(Opcodes.PUTFIELD,op);}
                @Override public void visitMethodInsn(int op,String o,String n,String d,boolean itf){calls.add(o+":"+n+d);}
            };}},0);
        assertTrue(calls.contains("dev/aitalkstreamer/mc/survival/SurvivalInputs:sneaking(Lnet/minecraft/client/input/Input;Z)V"));
        open();run(()->set(input,false));assertFalse(value(input));close();assertTrue(value(input));
    }
    @Test void noRootCannotAlterTheRealNativeInputOwner() throws Exception {assertThrows(RuntimeException.class,()->set(input,false));assertTrue(value(input));}
    @Test void normalPrePostWritesEndOwnershipBeforeTheFollowingKeyboardUpdate() throws Exception {
        open();run(()->{set(input,false);set(input,true);});inputType.getField("sneaking").setBoolean(input,false);close();assertFalse(value(input));
    }
    @Test void keyUpDuringTemporarySuppressionIsNotRestoredAsAnOldHeldKey() throws Exception {
        open();run(()->set(input,false));physical(false);control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY);close();assertFalse(value(input));
    }
    @Test void stillHeldPhysicalKeyIsRestoredAfterRevocation() throws Exception {
        open();run(()->set(input,false));control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY);close();assertTrue(value(input));
    }
    @Test void anExceptionBetweenTheTwoUpstreamWritesStillRestoresAtRootClose() throws Exception {
        open();assertThrows(IllegalStateException.class,()->run(()->{set(input,false);throw new IllegalStateException("fixture block interaction");}));close();assertTrue(value(input));
    }
    @Test void foreignInputsCannotBeWrittenAndAnInterveningValueIsPreserved() throws Exception {
        open();Object foreign=inputType.getConstructor().newInstance();assertThrows(RuntimeException.class,()->run(()->set(foreign,false)));
        run(()->set(input,false));inputType.getField("sneaking").setBoolean(input,true);physical(false);close();assertTrue(value(input));assertTrue(value(foreign));
    }
    @Test void expiryPreventsThePostWriteButKeepsCleanupAvailable() throws Exception {
        open();run(()->set(input,false));clock.addAndGet(4000);assertThrows(RuntimeException.class,()->run(()->set(input,true)));close();assertTrue(value(input));
    }
    @Test void focusPauseAndDeathCannotWriteFlags() throws Exception {
        open();clientType.getField("focused").setBoolean(client,false);assertThrows(RuntimeException.class,()->run(()->set(input,false)));
        clientType.getField("focused").setBoolean(client,true);clientType.getField("paused").setBoolean(client,true);assertThrows(RuntimeException.class,()->run(()->set(input,false)));
        clientType.getField("paused").setBoolean(client,false);player().getClass().getField("alive").setBoolean(player(),false);
        assertThrows(RuntimeException.class,()->run(()->set(input,false)));assertTrue(value(input));
    }
    @Test void everyNativeIdentityChangeBlocksTheFieldEffect() throws Exception {
        open();for(String name:List.of("world","player","network","interactionManager")){
            var field=clientType.getField(name);Object saved=field.get(client);field.set(client,field.getType().getConstructor().newInstance());
            assertThrows(RuntimeException.class,()->run(()->set(input,false)));field.set(client,saved);
        }assertTrue(value(input));
    }
    @Test void wrongThreadCannotBorrowTheOriginalInputScope() throws Exception {
        open();var failure=new AtomicReference<Throwable>();Thread t=new Thread(()->{try{run(()->set(input,false));}catch(Throwable e){failure.set(e);}});
        t.start();t.join(3000);assertFalse(t.isAlive());assertNotNull(failure.get());assertTrue(value(input));
    }
    @Test void currentKeyMappingIsReadWhenRestoringAKeyboardInput() throws Exception {
        open();run(()->set(input,false));Object options=clientType.getField("options").get(client),key=options.getClass().getField("sneakKey").get(options);
        Object bound=key.getClass().getField("key").get(key);bound.getClass().getField("code").setInt(bound,75);close();
        assertEquals(75,physicalType.getField("lastCode").getInt(null));assertTrue(value(input));
    }
    @Test void mouseAndScancodeBindingsUseTheirExistingNativePhysicalResolvers() throws Exception {
        for(String category:List.of("MOUSE","SCANCODE")){
            Object options=clientType.getField("options").get(client),key=options.getClass().getField("sneakKey").get(options),bound=key.getClass().getField("key").get(key);
            var type=bound.getClass().getField("type");Object enumValue=Arrays.stream(type.getType().getEnumConstants()).filter(v->v.toString().equals(category)).findFirst().orElseThrow();
            type.set(bound,enumValue);bound.getClass().getField("code").setInt(bound,7);physical.event(1,-1,7,1);
            open();run(()->set(input,false));close();assertTrue(value(input));
        }
    }
    @Test void nonKeyboardSyntheticInputRestoresItsOwnOriginalWithoutPhysicalPolling() throws Exception {
        Object replacement=inputType.getConstructor().newInstance();player().getClass().getField("input").set(player(),replacement);input=replacement;
        physicalType.getField("fail").setBoolean(null,true);open();run(()->set(input,false));close();assertTrue(value(input));
    }
    @Test void failedPhysicalRestoreRetainsTheRootAndRetriesWithoutRegranting() throws Exception {
        open();run(()->set(input,false));physicalType.getField("fail").setBoolean(null,true);assertThrows(RuntimeException.class,this::close);
        assertThrows(RuntimeException.class,this::open);physicalType.getField("fail").setBoolean(null,false);close();assertTrue(value(input));
    }
    @Test void oldCleanupCannotRestoreOverTheNextTaskInput() throws Exception {
        open();run(()->set(input,false));Object old=session;close();open();run(()->set(input,false));
        invoke(sessionType.getMethod("close",Runnable.class,Runnable.class),old,(Runnable)()->{},(Runnable)()->{});assertFalse(value(input));close();assertTrue(value(input));
    }
    @Test void replacedCurrentInputIsPreservedWhileTheOldKeyboardFlagIsRestored() throws Exception {
        open();Object original=input;run(()->set(input,false));Object replacement=inputType.getConstructor().newInstance();
        player().getClass().getField("input").set(player(),replacement);close();assertSame(replacement,player().getClass().getField("input").get(player()));assertTrue(value(original));
    }
    @Test void temporaryFlagsOnBothOriginalAndInstalledMovementInputsAreReleasedTogether() throws Exception {
        open();Object original=input;run(()->set(original,false));Object replacement=inputType.getConstructor().newInstance();
        var movement=ownerType.getMethod("movement",player().getClass(),inputType,ControlArbiter.class,ControlArbiter.Permit.class);
        run(()->invoke(movement,owner,uncheckedPlayer(),replacement,control,control.permit()));run(()->set(replacement,false));close();
        assertSame(original,player().getClass().getField("input").get(player()));assertTrue(value(original));assertTrue(value(replacement));
    }
    Object uncheckedPlayer(){try{return player();}catch(Exception e){throw new IllegalStateException(e);}}
    @Test void malformedFieldPoliciesAndStaticWritesAreRejected() throws Exception {
        String valid=Files.readString(Path.of("gate-policy.json"));var json=com.google.gson.JsonParser.parseString(valid).getAsJsonObject();
        for(var element:json.getAsJsonArray("rules")){var row=element.getAsJsonObject();if(row.has("relay")&&row.get("relay").getAsString().equals("sneaking"))row.addProperty("descriptor","I");}
        Path bad=temporary.resolve("bad-sneak-policy.json");Files.writeString(bad,json.toString());assertThrows(IllegalArgumentException.class,()->GatePolicy.read(bad));
        assertThrows(IllegalArgumentException.class,()->transformed(Opcodes.PUTSTATIC));
    }
}
