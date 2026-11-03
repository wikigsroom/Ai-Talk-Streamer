package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.*;
import com.mojang.blaze3d.platform.NativeImage;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;
import net.minecraft.client.gui.components.AbstractWidget;
import net.minecraft.core.registries.BuiltInRegistries;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.fml.ModList;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.RenderFrameEvent;
import net.neoforged.neoforge.event.GameShuttingDownEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;

/** Native player integration and diagnostic evidence. BridgeCore is the only transport authority. */
@Mod(value="ai_talk_streamer_native", dist=Dist.CLIENT)
public final class NativeClient {
    private static final Logger LOG=LoggerFactory.getLogger("AiTalkStreamerNeoForge");
    private static final Gson GSON=new GsonBuilder().setPrettyPrinting().create();
    private final ExecutorService io=Executors.newSingleThreadExecutor(r->{
        Thread t=new Thread(r,"mc-native-facts");t.setDaemon(true);return t;
    });
    private int ticks,worldSamples;
    private boolean frame,stopping;
    private NativeBridge bridge;
    public NativeClient(){
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Post.class,this::tick);
        NeoForge.EVENT_BUS.addListener(RenderFrameEvent.Post.class,event->{if(bridge!=null)bridge.rendered();});
        NeoForge.EVENT_BUS.addListener(GameShuttingDownEvent.class,event->{if(bridge!=null)bridge.close();});
    }

    private void tick(ClientTickEvent.Post ignored){
        if(stopping)return;
        Minecraft c=Minecraft.getInstance();
        if(bridge==null)bridge=new NativeBridge(c);
        bridge.tick(c);
        if(++ticks%20!=0)return;
        try{
            JsonObject value=new JsonObject();
            value.addProperty("schema_version",1);
            value.addProperty("classification","ACTUAL_NEOFORGE_CLIENT_FACTS_NOT_AUTOMATIC_GAMEPLAY_ACCEPTANCE");
            value.addProperty("observed_at",Instant.now().toString());
            value.addProperty("adapter","minecraft.neoforge");
            value.addProperty("username",c.getUser().getName());
            value.addProperty("profile_id",c.getUser().getProfileId().toString());
            value.addProperty("minecraft","1.21.1");
            value.addProperty("neoforge",ModList.get().getModContainerById("neoforge").orElseThrow().getModInfo().getVersion().toString());
            value.addProperty("loaded_mods",ModList.get().size());
            value.addProperty("automatic_input_authorized",bridge!=null&&bridge.authorized());
            value.addProperty("gameplay_executor_bound",NativeHooks.ready());
            value.add("missing_native_hooks",GSON.toJsonTree(NativeHooks.missing()));
            value.addProperty("control_mode",bridge==null?"DISABLED":bridge.mode());
            value.add("control_proof",bridge==null?JsonNull.INSTANCE:bridge.controlProof());
            value.addProperty("in_world",c.level!=null&&c.player!=null&&c.getConnection()!=null);
            value.addProperty("screen",c.screen==null?"gameplay":c.screen.getClass().getName());
            value.addProperty("overlay",c.getOverlay()==null?null:c.getOverlay().getClass().getName());
            value.addProperty("no_render",c.noRender);
            value.addProperty("game_load_finished",c.isGameLoadFinished());
            value.addProperty("window_active",c.isWindowActive());
            value.addProperty("fps",c.getFps());
            if(c.screen!=null){
                value.addProperty("screen_title",c.screen.getTitle().getString());
                value.addProperty("screen_width",c.screen.width);
                value.addProperty("screen_height",c.screen.height);
                JsonArray widgets=new JsonArray();
                for(var child:c.screen.children())if(child instanceof AbstractWidget widget){
                    JsonObject row=new JsonObject();row.addProperty("text",widget.getMessage().getString());
                    row.addProperty("x",widget.getX());row.addProperty("y",widget.getY());
                    row.addProperty("width",widget.getWidth());row.addProperty("height",widget.getHeight());
                    row.addProperty("active",widget.active);row.addProperty("visible",widget.visible);widgets.add(row);
                }
                value.add("screen_widgets",widgets);
                if(ticks==20||ticks%200==0)capture(c,"ai-talk-streamer-screen.png");
            }
            if(c.level!=null&&c.player!=null&&c.getConnection()!=null){
                ++worldSamples;var p=c.player;
                value.addProperty("received_recipes",c.getConnection().getRecipeManager().getRecipes().size());
                value.addProperty("player_name",p.getGameProfile().getName());
                value.addProperty("player_uuid",p.getUUID().toString());
                value.addProperty("dimension",c.level.dimension().location().toString());
                value.addProperty("health",p.getHealth());value.addProperty("max_health",p.getMaxHealth());
                value.addProperty("food",p.getFoodData().getFoodLevel());
                value.addProperty("x",p.getX());value.addProperty("y",p.getY());value.addProperty("z",p.getZ());
                value.addProperty("alive",p.isAlive());
                value.addProperty("selected_slot",p.getInventory().selected);
                value.addProperty("mainhand_item",BuiltInRegistries.ITEM.getKey(p.getMainHandItem().getItem()).toString());
                value.addProperty("offhand_item",BuiltInRegistries.ITEM.getKey(p.getOffhandItem().getItem()).toString());
                TreeMap<String,Integer> counts=new TreeMap<>();
                for(int i=0;i<p.getInventory().getContainerSize();i++){
                    var stack=p.getInventory().getItem(i);
                    if(!stack.isEmpty())counts.merge(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(),stack.getCount(),Integer::sum);
                }
                JsonArray inventory=new JsonArray();counts.forEach((item,count)->{
                    JsonObject row=new JsonObject();row.addProperty("item_id",item);row.addProperty("count",count);inventory.add(row);
                });value.add("inventory",inventory);
                if(!frame&&worldSamples>=3){
                    frame=true;capture(c,"ai-talk-streamer-native.png");
                }
            }
            value.addProperty("world_samples",worldSamples);
            Path output=c.gameDirectory.toPath().resolve("logs/ai-talk-streamer-native.json");
            io.execute(()->persist(output,value));
            if(Boolean.getBoolean("ai.talk.streamer.integrationProbe")
                    &&worldSamples>=Math.clamp(Integer.getInteger("ai.talk.streamer.integrationWorldSamples",5),5,300)){
                stopping=true;
                io.execute(()->c.execute(c::stop));
            }
        }catch(Throwable error){stopping=true;LOG.error("Native integration facts failed",error);c.stop();}
    }
    private void capture(Minecraft client,String name){
        NativeImage image=Screenshot.takeScreenshot(client.getMainRenderTarget());
        Path output=client.gameDirectory.toPath().resolve("logs").resolve(name);
        io.execute(()->{try(image){
            Path temp=output.resolveSibling(name+".tmp");image.writeToFile(temp);
            Files.move(temp,output,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
        }catch(Exception error){LOG.error("Native frame capture failed",error);}});
    }
    private void persist(Path output,JsonObject value){
        try{
            Files.createDirectories(output.getParent());Path temp=output.resolveSibling(output.getFileName()+".tmp");
            Files.writeString(temp,GSON.toJson(value)+"\n",StandardCharsets.UTF_8);
            Files.move(temp,output,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
        }catch(Exception error){LOG.error("Native facts persistence failed",error);}
    }
}
