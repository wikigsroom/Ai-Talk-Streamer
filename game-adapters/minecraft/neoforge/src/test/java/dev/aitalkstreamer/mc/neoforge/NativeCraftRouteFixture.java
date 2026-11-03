package dev.aitalkstreamer.mc.neoforge;

/** Regression for the supplied pack's bread crafting/cooking collision; no game effects. */
public final class NativeCraftRouteFixture {
    private static int checks;
    private static void equal(boolean expected, boolean actual) {
        checks++; if (expected != actual) throw new AssertionError("check " + checks);
    }
    public static void main(String[] args) {
        // Nine held wheat plus a missing table must still request a table, even
        // when this pack also advertises an unusable furnace bread recipe.
        equal(false, NativeCraftRoute.cooking("GAME_CRAFT_WORKSTATION_UNAVAILABLE", false));
        equal(false, NativeCraftRoute.cooking("GAME_CRAFT_MATERIALS_MISSING", false));
        equal(true, NativeCraftRoute.cooking("GAME_CRAFT_WORKSTATION_UNAVAILABLE", true));
        equal(true, NativeCraftRoute.cooking("GAME_CRAFT_MATERIALS_MISSING", true));
        // A cooking-only output still reports its own missing furnace/fuel.
        equal(true, NativeCraftRoute.cooking("GAME_CRAFT_RECIPE_UNAVAILABLE", false));
        equal(true, NativeCraftRoute.cooking("GAME_CRAFT_RECIPE_UNAVAILABLE", true));
        for (String reason : new String[]{null, "GAME_GUI_BLOCKED", "GAME_WORLD_UNAVAILABLE", "GAME_WRONG_THREAD",
                "GAME_CRAFT_CONTEXT_CHANGED", "GAME_CRAFT_HANDLER_INVALID", "GAME_CRAFT_GRID_NOT_EMPTY",
                "GAME_CRAFT_RECIPE_AMBIGUOUS", "GAME_CRAFT_INVENTORY_INVALID", "GAME_CRAFT_OUTPUT_COUNT_INVALID"}) {
            equal(false, NativeCraftRoute.mayTryCooking(reason));
            equal(false, NativeCraftRoute.cooking(reason, false));
            equal(false, NativeCraftRoute.cooking(reason, true));
        }
        System.out.println("PASS NativeCraftRouteFixture " + checks + " checks; no game or input effects");
    }
}
