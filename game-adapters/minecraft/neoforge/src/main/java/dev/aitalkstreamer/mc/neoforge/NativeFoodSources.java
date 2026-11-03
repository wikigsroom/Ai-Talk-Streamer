package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.CropBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.VoxelShape;
import java.time.Instant;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Read-only loaded client facts, cached for at most one second and one block position. */
final class NativeFoodSources {
    private Object level, player, connection;
    private BlockPos anchor;
    private long scannedAt;
    private JsonObject cached;
    static String harvest(BlockState state) {
        int age = state.getBlock() instanceof CropBlock crop ? crop.getAge(state) : -1;
        return NativeFoodPlan.harvest(BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString(), age);
    }
    static Vec3 aimPoint(BlockPos at, VoxelShape shape) {
        return shape.isEmpty() ? Vec3.atCenterOf(at) : shape.bounds().getCenter().add(at.getX(), at.getY(), at.getZ());
    }
    JsonObject sample(Minecraft client) {
        long now = System.nanoTime() / 1_000_000;
        BlockPos origin = client.player.blockPosition();
        if (cached != null && level == client.level && player == client.player && connection == client.getConnection()
                && origin.equals(anchor) && now >= scannedAt && now - scannedAt < 1000) return cached.deepCopy();
        var rows = new ArrayList<JsonObject>();
        var sites = new ArrayList<JsonObject>();
        String dimension = client.level.dimension().location().toString();
        for (int dy = -3; dy <= 3; dy++) for (int dx = -6; dx <= 6; dx++) for (int dz = -6; dz <= 6; dz++) {
            BlockPos at = origin.offset(dx, dy, dz);
            if (origin.distSqr(at) > 36 || !client.level.hasChunkAt(at)
                    || !client.level.getWorldBorder().isWithinBounds(at)) continue;
            BlockState state = client.level.getBlockState(at);
            if (NativePlanting.site(client, at) != null) sites.add(obj("position",
                    obj("dimension", dimension, "x", at.getX(), "y", at.getY(), "z", at.getZ()),
                    "soil_id", "minecraft:farmland", "line_of_sight", true,
                    "distance", client.player.getEyePosition().distanceTo(NativePlanting.top(at.below()))));
            String item = harvest(state);
            if (item == null || state.hasBlockEntity() || !state.getFluidState().isEmpty()) continue;
            var shape = state.getShape(client.level, at);
            if (shape.isEmpty()) continue;
            Vec3 target = aimPoint(at, shape);
            var hit = client.level.clip(new ClipContext(client.player.getEyePosition(), target,
                    ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, client.player));
            if (hit.getType() != HitResult.Type.BLOCK || !hit.getBlockPos().equals(at)) continue;
            rows.add(row("mature_crop", item, BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString(),
                    at, dimension, Math.sqrt(origin.distSqr(at))));
        }
        for (var loose : client.level.getEntitiesOfClass(ItemEntity.class, client.player.getBoundingBox().inflate(6),
                e -> e.isAlive() && !e.hasPickUpDelay() && client.player.distanceToSqr(e) <= 36)) {
            String item = BuiltInRegistries.ITEM.getKey(loose.getItem().getItem()).toString();
            if (!NativeFoodPlan.gatherable(item)) continue;
            var hit = client.level.clip(new ClipContext(client.player.getEyePosition(), loose.position().add(0, .1, 0),
                    ClipContext.Block.COLLIDER, ClipContext.Fluid.NONE, client.player));
            if (hit.getType() != HitResult.Type.MISS) continue;
            rows.add(row("loose_item", item, null, loose.blockPosition(), dimension,
                    Math.sqrt(client.player.distanceToSqr(loose))));
        }
        rows.sort(Comparator.comparingDouble(r -> r.get("distance").getAsDouble()));
        sites.sort(Comparator.comparingDouble(r -> r.get("distance").getAsDouble()));
        cached = obj("source", "runtime_client", "sampled_at", Instant.now().toString(), "radius", 6, "vertical_radius", 3,
                "items", rows.subList(0, Math.min(8, rows.size())), "truncated", rows.size() > 8,
                "planting_sites", sites.subList(0, Math.min(8, sites.size())), "planting_sites_truncated", sites.size() > 8,
                "action_precondition_required", true, "unknown_fields", List.of("unloaded_chunks", "occluded_sources",
                        "outside_scan_volume", "future_drops", "safe_reachability", "unlisted_food_sources"));
        level = client.level; player = client.player; connection = client.getConnection();
        anchor = origin.immutable(); scannedAt = now;
        return cached.deepCopy();
    }
    private JsonObject row(String kind, String item, String block, BlockPos at, String dimension, double distance) {
        return obj("kind", kind, "item_id", item, "block_id", block, "distance", distance,
                "line_of_sight", true, "position", obj("dimension", dimension, "x", at.getX(), "y", at.getY(), "z", at.getZ()));
    }
}
