package dev.aitalkstreamer.mc.neoforge;

import java.util.Set;

/** Preserve a useful crafting denial unless a received cooking alternative is usable. */
final class NativeCraftRoute {
    private static final Set<String> RECIPE_FAILURES = Set.of(
            "GAME_CRAFT_RECIPE_UNAVAILABLE", "GAME_CRAFT_MATERIALS_MISSING", "GAME_CRAFT_WORKSTATION_UNAVAILABLE");
    private NativeCraftRoute() { }

    static boolean mayTryCooking(String craftReason) {
        return craftReason != null && RECIPE_FAILURES.contains(craftReason);
    }

    static boolean cooking(String craftReason, boolean cookingAllowed) {
        return mayTryCooking(craftReason) && (cookingAllowed || "GAME_CRAFT_RECIPE_UNAVAILABLE".equals(craftReason));
    }
}
