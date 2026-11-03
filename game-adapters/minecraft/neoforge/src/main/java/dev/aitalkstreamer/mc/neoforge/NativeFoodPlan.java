package dev.aitalkstreamer.mc.neoforge;

import java.util.Map;
import java.util.Set;

/** Vanilla food and bread materials; visibility never promises inventory effects. */
public final class NativeFoodPlan {
    private NativeFoodPlan() { }
    private record Crop(String item, int matureAge) { }
    private static final Map<String, Crop> CROPS = Map.of(
            "minecraft:wheat", new Crop("minecraft:wheat", 7),
            "minecraft:carrots", new Crop("minecraft:carrot", 7),
            "minecraft:potatoes", new Crop("minecraft:potato", 7),
            "minecraft:beetroots", new Crop("minecraft:beetroot", 3),
            "minecraft:melon", new Crop("minecraft:melon_slice", -1),
            "minecraft:hay_block", new Crop("minecraft:hay_block", -1));
    private static final Set<String> EDIBLE = Set.of("minecraft:bread", "minecraft:cooked_beef",
            "minecraft:cooked_porkchop", "minecraft:cooked_chicken", "minecraft:cooked_mutton",
            "minecraft:cooked_rabbit", "minecraft:baked_potato", "minecraft:cooked_cod",
            "minecraft:cooked_salmon", "minecraft:carrot", "minecraft:apple", "minecraft:potato",
            "minecraft:beetroot", "minecraft:melon_slice", "minecraft:sweet_berries", "minecraft:glow_berries");

    public static boolean edible(String item) { return item != null && EDIBLE.contains(item); }
    /** In-flight travel can restore food for normal regeneration without changing health or hunger. */
    public static boolean needsIntervention(int hunger, float health, float maxHealth) {
        if (hunger < 0 || hunger > 20 || !Float.isFinite(health) || !Float.isFinite(maxHealth)
                || health <= 0 || maxHealth <= 0 || health > maxHealth) return false;
        return hunger <= 14 || health < maxHealth && hunger < 18;
    }
    public static boolean gatherable(String item) {
        return edible(item) || NativeHuntPlan.material(item) || "minecraft:wheat".equals(item) || "minecraft:hay_block".equals(item);
    }
    public static String kind(String block) {
        return "minecraft:hay_block".equals(block) ? "food_material" : "mature_crop";
    }
    public static String harvest(String block, int age) {
        Crop crop = block == null ? null : CROPS.get(block);
        return crop != null && age == crop.matureAge ? crop.item : null;
    }
}
