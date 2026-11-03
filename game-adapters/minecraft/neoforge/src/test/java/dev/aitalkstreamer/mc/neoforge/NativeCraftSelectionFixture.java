package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import dev.aitalkstreamer.mc.core.Json.Rejected;
import static dev.aitalkstreamer.mc.neoforge.NativeCraftPlan.*;

/** Supplied vanilla/utilitarian bread collision and general recipe choices; no game writes. */
public final class NativeCraftSelectionFixture {
    private static int checks;
    private static final Ingredient WHEAT = new Ingredient(false, Set.of(0));
    private static final Ingredient EMPTY = new Ingredient(true, Set.of());
    private static List<Integer> stock(int amount) {
        var counts = new ArrayList<>(Collections.nCopies(36, 0)); counts.set(0, amount); return counts;
    }
    private static void equal(Object expected, Object actual) {
        checks++; if (!Objects.equals(expected, actual)) throw new AssertionError("check " + checks + ": " + expected + " != " + actual);
    }
    private static void denied(String reason, Runnable action) {
        checks++; try { action.run(); } catch (Rejected error) {
            if (reason.equals(error.code)) return; throw new AssertionError(error.code);
        }
        throw new AssertionError("expected " + reason);
    }
    private static Plan plan(String id, int output, int ingredients, int requested) {
        return allocate(new Recipe(id, false, 0, 0, output, Collections.nCopies(ingredients, WHEAT)),
                stock(64), "minecraft:bread", 2, requested);
    }
    public static void main(String[] args) {
        var vanilla = allocate(new Recipe("minecraft:bread", true, 3, 1, 1, List.of(WHEAT, WHEAT, WHEAT)),
                stock(9), "minecraft:bread", 0, 1);
        var utility = allocate(new Recipe("utilitarian:utility/bread", true, 2, 2, 1, List.of(WHEAT, WHEAT, WHEAT, EMPTY)),
                stock(9), "minecraft:bread", 0, 1);
        for (var order : List.of(List.of(vanilla, utility), List.of(utility, vanilla))) {
            var selected = select(order);
            equal("utilitarian:utility/bread", selected.recipe().id());
            equal(2, selected.recipe().gridSize());
            equal(3, selected.allocations().stream().mapToInt(Allocation::count).sum());
            equal(List.of(0, 1, 2, 3), selected.positions());
            equal(1, selected.target().plannedIncrement());
        }
        equal(vanilla, select(List.of(vanilla)));
        equal(utility, select(List.of(utility)));
        var expensive = plan("live:expensive", 1, 3, 3);
        var economical = plan("live:economical", 3, 1, 3);
        var equalCostSurplus = plan("live:surplus", 4, 1, 3);
        for (var order : List.of(List.of(expensive, economical, equalCostSurplus),
                List.of(equalCostSurplus, expensive, economical), List.of(economical, equalCostSurplus, expensive))) {
            equal(economical, select(order));
            equal(3, select(order).target().plannedIncrement());
        }
        var a = plan("live:a", 1, 1, 1); var z = plan("live:z", 1, 1, 1);
        equal(a, select(List.of(z, a))); equal(a, select(List.of(a, z)));
        denied("GAME_CRAFT_MATERIALS_MISSING", () -> select(List.of()));
        denied("GAME_CRAFT_RECIPE_AMBIGUOUS", () -> select(List.of(vanilla, vanilla)));
        denied("GAME_CRAFT_ALLOCATION_INVALID", () -> select(List.of(vanilla, a)));
        equal(null, allocate(new Recipe("live:unaffordable", false, 0, 0, 1, List.of(WHEAT, WHEAT)),
                stock(1), "minecraft:bread", 0, 1));
        System.out.println("PASS NativeCraftSelectionFixture " + checks + " checks; no game or input effects");
    }
}
