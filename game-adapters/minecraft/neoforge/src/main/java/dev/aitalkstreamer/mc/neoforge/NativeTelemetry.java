package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.*;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.item.ItemStack;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Client-observed information only. Unopened storage and unsent server rules remain unknown. */
final class NativeTelemetry {
    private NativeTelemetry() { }
    static JsonObject stack(int slot, ItemStack stack) {
        return obj("slot", slot, "item_id", stack.isEmpty() ? "minecraft:air" : BuiltInRegistries.ITEM.getKey(stack.getItem()).toString(),
                "count", stack.getCount(), "damage", stack.isDamageableItem() ? stack.getDamageValue() : null,
                "max_damage", stack.isDamageableItem() ? stack.getMaxDamage() : null);
    }
    static Integer loadedRadius(Minecraft client) {
        BlockPos center = client.player.blockPosition();
        int cx = center.getX() >> 4, cz = center.getZ() >> 4;
        if (!client.level.hasChunk(cx, cz)) return null;
        int known = 0;
        for (int radius = 1; radius <= 4; radius++) {
            for (int x = -radius; x <= radius; x++) for (int z = -radius; z <= radius; z++)
                if ((Math.abs(x) == radius || Math.abs(z) == radius) && !client.level.hasChunk(cx + x, cz + z)) return known;
            known = radius;
        }
        return known;
    }
    static JsonObject sample(Minecraft client, NativeFoodSources food, NativeConstruction construction, NativeTravel travel) {
        var player = client.player; var level = client.level; var menu = player.containerMenu;
        JsonArray slots = new JsonArray(), visible = new JsonArray(), threats = new JsonArray();
        for (int i = 0; i < player.getInventory().getContainerSize(); i++) slots.add(stack(i, player.getInventory().getItem(i)));
        boolean container = client.screen instanceof net.minecraft.client.gui.screens.inventory.AbstractContainerScreen<?>;
        if (container) for (int i = 0; i < Math.min(256, menu.slots.size()); i++) visible.add(stack(i, menu.getSlot(i).getItem()));
        var monsters = level.getEntitiesOfClass(Monster.class, player.getBoundingBox().inflate(16),
                e -> e.isAlive() && player.distanceToSqr(e) <= 16 * 16);
        monsters.sort(Comparator.comparingDouble(player::distanceToSqr));
        for (var entity : monsters.subList(0, Math.min(32, monsters.size()))) {
            var p = entity.blockPosition();
            threats.add(obj("entity_id", entity.getId(), "type", BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString(),
                    "health", entity.getHealth(), "visible", player.hasLineOfSight(entity),
                    "distance", Math.sqrt(player.distanceToSqr(entity)), "position", obj("dimension", level.dimension().location().toString(),
                            "x", p.getX(), "y", p.getY(), "z", p.getZ())));
        }
        var biome = level.getBiome(player.blockPosition()).unwrapKey().map(key -> key.location().toString()).orElse(null);
        return obj("source", "runtime_client", "selected_hotbar", player.getInventory().selected,
                "inventory_slots", slots, "cursor", stack(-1, menu.getCarried()),
                "gui", obj("kind", container ? "container" : client.screen == null ? "gameplay" : "screen",
                        "title", client.screen == null ? null : client.screen.getTitle().getString().substring(0, Math.min(240, client.screen.getTitle().getString().length())),
                        "container_id", container ? menu.containerId : null, "slots", visible,
                        "truncated", container && menu.slots.size() > 256),
                "hazards", obj("on_fire", player.isOnFire(), "in_water", player.isInWater(), "in_lava", player.isInLava(),
                        "fall_distance", Math.max(0, player.fallDistance), "on_ground", player.onGround()),
                "environment", obj("biome", biome, "day_time", Math.max(0, level.getDayTime()), "raining", level.isRaining(),
                        "thundering", level.isThundering(), "singleplayer", client.getSingleplayerServer() != null,
                        "game_paused", client.isPaused(), "local_server_published",
                        client.getSingleplayerServer() == null ? null : client.getSingleplayerServer().isPublished()),
                "received_rules", obj("difficulty", level.getDifficulty().getKey(),
                        "game_mode", client.gameMode.getPlayerMode().getName(), "world_border_size", level.getWorldBorder().getSize()),
                "nearby_food", food.sample(client),
                "construction", construction.sample(client),
                "navigation", travel.navigation(),
                "nearby_hostiles", threats, "hostiles_truncated", monsters.size() > 32,
                "unknown_fields", List.of("unopened_container_contents", "unsent_server_gamerules", "entities_outside_16_blocks",
                        "loaded_chunks_beyond_checked_radius", "modded_rule_semantics"));
    }
}
