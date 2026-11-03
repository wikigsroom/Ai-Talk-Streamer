package dev.aitalkstreamer.mc.neoforge;

import java.util.Map;

/** Only these ordinary adult livestock can supply raw cooking materials. */
public final class NativeHuntPlan {
    private NativeHuntPlan() { }
    private static final Map<String, String> RAW = Map.of(
            "minecraft:sheep", "minecraft:mutton", "minecraft:cow", "minecraft:beef",
            "minecraft:pig", "minecraft:porkchop");
    public static String raw(String entity) { return entity == null ? null : RAW.get(entity); }
    public static boolean material(String item) { return item != null && RAW.containsValue(item); }
    public static boolean eligible(String entity, String item, boolean alive, boolean baby, boolean named,
                                   boolean leashed, boolean passenger, boolean vehicle, double distanceSquared) {
        return material(item) && item.equals(raw(entity)) && alive && !baby && !named && !leashed
                && !passenger && !vehicle && Double.isFinite(distanceSquared)
                && distanceSquared >= 0 && distanceSquared <= 256;
    }
    public static boolean playerReady(float health, int food) {
        return Float.isFinite(health) && health >= 10 && food >= 6 && food <= 20;
    }
}
