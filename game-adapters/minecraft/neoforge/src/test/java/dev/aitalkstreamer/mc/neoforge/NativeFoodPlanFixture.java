package dev.aitalkstreamer.mc.neoforge;

import java.util.Objects;

/** Runs on the supplied native JDK; these are policy boundaries, not a game harvest. */
public final class NativeFoodPlanFixture {
    private static int checks;
    private static void equal(Object expected, Object actual) {
        checks++;
        if (!Objects.equals(expected, actual)) throw new AssertionError(expected + " != " + actual);
    }
    public static void main(String[] args) {
        String[] blocks = {"wheat", "carrots", "potatoes", "beetroots"};
        String[] items = {"wheat", "carrot", "potato", "beetroot"};
        for (int i = 0; i < blocks.length; i++) {
            int mature = i == 3 ? 3 : 7;
            for (int age = -1; age <= 9; age++) equal(age == mature ? "minecraft:" + items[i] : null,
                    NativeFoodPlan.harvest("minecraft:" + blocks[i], age));
            equal(true, NativeFoodPlan.gatherable("minecraft:" + items[i]));
        }
        equal("minecraft:melon_slice", NativeFoodPlan.harvest("minecraft:melon", -1));
        equal(null, NativeFoodPlan.harvest("minecraft:melon", 0));
        for (String unknown : new String[]{null, "minecraft:oak_leaves", "minecraft:sweet_berry_bush", "mod:carrots", "minecraft:poisonous_potato"})
            equal(null, NativeFoodPlan.harvest(unknown, 7));
        for (String unsafe : new String[]{null, "minecraft:wheat", "minecraft:rotten_flesh", "minecraft:poisonous_potato", "minecraft:spider_eye", "minecraft:pufferfish", "mod:apple"})
            equal(false, NativeFoodPlan.edible(unsafe));
        for (String food : new String[]{"carrot", "potato", "beetroot", "melon_slice", "bread", "apple", "cooked_beef", "baked_potato", "sweet_berries", "glow_berries"}) {
            equal(true, NativeFoodPlan.edible("minecraft:" + food));
            equal(true, NativeFoodPlan.gatherable("minecraft:" + food));
        }
        equal(false, NativeFoodPlan.gatherable("minecraft:poisonous_potato"));
        System.out.println("PASS NativeFoodPlanFixture " + checks + " checks; no game or input effects");
    }
}
