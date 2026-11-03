package dev.aitalkstreamer.mc.neoforge;

import java.util.Objects;

/** Selection boundaries only; actual hunting and inventory receipts need the real game. */
public final class NativeHuntPlanFixture {
    private static int checks;
    private static void equal(Object expected, Object actual) {
        checks++; if (!Objects.equals(expected, actual)) throw new AssertionError(expected + " != " + actual);
    }
    public static void main(String[] args) {
        String[] types = {"sheep", "cow", "pig"}, items = {"mutton", "beef", "porkchop"};
        for (int i = 0; i < types.length; i++) {
            String type = "minecraft:" + types[i], item = "minecraft:" + items[i];
            equal(item, NativeHuntPlan.raw(type)); equal(true, NativeHuntPlan.material(item));
            equal(true, NativeFoodPlan.gatherable(item)); equal(false, NativeFoodPlan.edible(item));
            for (int flags = 0; flags < 64; flags++) equal(flags == 1,
                    NativeHuntPlan.eligible(type, item, (flags & 1) != 0, (flags & 2) != 0,
                            (flags & 4) != 0, (flags & 8) != 0, (flags & 16) != 0, (flags & 32) != 0, 4));
            for (double range : new double[]{-1, 256.01, Double.NaN, Double.POSITIVE_INFINITY})
                equal(false, NativeHuntPlan.eligible(type, item, true, false, false, false, false, false, range));
            equal(true, NativeHuntPlan.eligible(type, item, true, false, false, false, false, false, 256));
            equal(false, NativeHuntPlan.eligible(type, "minecraft:bread", true, false, false, false, false, false, 4));
        }
        for (String type : new String[]{null, "minecraft:wolf", "minecraft:chicken", "mod:sheep"}) equal(null, NativeHuntPlan.raw(type));
        equal(false, NativeHuntPlan.material(null)); equal(false, NativeHuntPlan.material("minecraft:rotten_flesh"));
        for (int food = 0; food <= 21; food++) equal(food >= 6 && food <= 20, NativeHuntPlan.playerReady(12.033335f, food));
        for (float health : new float[]{-1, 0, 9.99f, Float.NaN, Float.POSITIVE_INFINITY})
            equal(false, NativeHuntPlan.playerReady(health, 17));
        equal(false, NativeHuntPlan.playerReady(20, -1)); equal(true, NativeHuntPlan.playerReady(10, 6));
        System.out.println("PASS NativeHuntPlanFixture " + checks + " checks; no game or input effects");
    }
}
