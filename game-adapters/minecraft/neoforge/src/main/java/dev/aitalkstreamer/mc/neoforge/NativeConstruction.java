package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.CollisionContext;
import java.time.Instant;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Loaded, visible construction facts. Never places blocks or writes a world. */
final class NativeConstruction {
    private Object world, player, connection;
    private BlockPos anchor;
    private long sampled;
    private JsonObject cached;
    static boolean supported(String item) {
        return "minecraft:crafting_table".equals(item) || "minecraft:furnace".equals(item) || terrain(item);
    }
    static boolean terrain(String item) { return "minecraft:dirt".equals(item); }
    static BlockHitResult terrainSite(Minecraft client, BlockPos at) {
        if(client.player==null || client.level==null)return null;
        var p=client.player.blockPosition();
        if(!NativeTerrainStep.admissible(new NativeWalkPlanner.Point(p.getX(),p.getY(),p.getZ()),
                new NativeWalkPlanner.Point(at.getX(),at.getY(),at.getZ()),client.player.onGround(),
                client.player.getHealth(),client.player.getFoodData().getFoodLevel(),
                !client.player.isInWater() && !client.player.isInLava() && !client.player.isOnFire()))return null;
        if(!client.level.hasChunkAt(at.below())
                || client.level.getBlockState(at.below()).getBlock() instanceof net.minecraft.world.level.block.FallingBlock)return null;
        return site(client,at);
    }
    static BlockHitResult site(Minecraft client, BlockPos at) {
        if (client.level == null || client.player == null || !client.level.hasChunkAt(at)
                || !client.level.hasChunkAt(at.below()) || !client.level.getWorldBorder().isWithinBounds(at)
                || at.getY() <= client.level.getMinBuildHeight() || at.getY() >= client.level.getMaxBuildHeight()
                || !client.level.getBlockState(at).isAir() || !client.level.getFluidState(at).isEmpty()
                || !client.level.getFluidState(at.below()).isEmpty()
                || !client.level.getBlockState(at.below()).isCollisionShapeFullBlock(client.level, at.below())
                || !client.level.isUnobstructed(Blocks.CRAFTING_TABLE.defaultBlockState(), at, CollisionContext.of(client.player))) return null;
        var eye = client.player.getEyePosition();
        var hit = client.level.clip(new ClipContext(eye, new Vec3(at.getX()+.5, at.getY()-.0001, at.getZ()+.5),
                ClipContext.Block.COLLIDER, ClipContext.Fluid.NONE, client.player));
        return hit.getType() == HitResult.Type.BLOCK && hit.getDirection() == Direction.UP
                && hit.getBlockPos().equals(at.below())
                && eye.distanceToSqr(hit.getLocation()) <= Math.pow(client.player.blockInteractionRange(),2) ? hit : null;
    }
    private static boolean visible(Minecraft client, BlockPos at) {
        var eye=client.player.getEyePosition();
        for (Direction face:Direction.values()) {
            var aim=Vec3.atCenterOf(at).add(Vec3.atLowerCornerOf(face.getNormal()).scale(.499));
            if (eye.distanceToSqr(aim)>Math.pow(client.player.blockInteractionRange(),2)) continue;
            var hit=client.level.clip(new ClipContext(eye,aim,ClipContext.Block.COLLIDER,ClipContext.Fluid.NONE,client.player));
            if (hit.getType()==HitResult.Type.BLOCK && hit.getBlockPos().equals(at)) return true;
        }
        return false;
    }
    private static JsonObject position(String dimension, BlockPos at) {
        return obj("dimension",dimension,"x",at.getX(),"y",at.getY(),"z",at.getZ());
    }
    JsonObject sample(Minecraft client) {
        long now=System.nanoTime()/1_000_000;
        var origin=client.player.blockPosition();
        if (cached!=null && world==client.level && player==client.player && connection==client.getConnection()
                && origin.equals(anchor) && now>=sampled && now-sampled<1000) return cached.deepCopy();
        var sites=new ArrayList<JsonObject>();var stations=new ArrayList<JsonObject>();
        String dimension=client.level.dimension().location().toString();
        for (BlockPos mutable:BlockPos.betweenClosed(origin.offset(-4,-3,-4),origin.offset(4,3,4))) {
            var at=mutable.immutable();
            if (!client.level.hasChunkAt(at) || !client.level.getWorldBorder().isWithinBounds(at)) continue;
            double distance=client.player.getEyePosition().distanceTo(Vec3.atCenterOf(at));
            String block=BuiltInRegistries.BLOCK.getKey(client.level.getBlockState(at).getBlock()).toString();
            if (supported(block) && !terrain(block) && visible(client,at)) stations.add(obj("block_id",block,"position",position(dimension,at),"distance",distance));
            if (site(client,at)!=null) sites.add(obj("position",position(dimension,at),"distance",distance,
                    "support_id",BuiltInRegistries.BLOCK.getKey(client.level.getBlockState(at.below()).getBlock()).toString()));
        }
        sites.sort(Comparator.comparingDouble(row->row.get("distance").getAsDouble()));
        stations.sort(Comparator.comparingDouble(row->row.get("distance").getAsDouble()));
        cached=obj("source","runtime_client","sampled_at",Instant.now().toString(),"radius",4,"vertical_radius",3,
                "placement_sites",sites.subList(0,Math.min(8,sites.size())),"sites_truncated",sites.size()>8,
                "workstations",stations.subList(0,Math.min(4,stations.size())),"workstations_truncated",stations.size()>4,
                "action_precondition_required",true,"unknown_fields",List.of("unloaded_chunks","occluded_cells","server_placement_rules","future_collisions"));
        world=client.level;player=client.player;connection=client.getConnection();anchor=origin.immutable();sampled=now;
        return cached.deepCopy();
    }
}
