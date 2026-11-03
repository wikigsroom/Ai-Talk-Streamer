package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.Json.Rejected;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Exact bounded allocation checks; inventory/recipe projections are fixtures, not MC effects. */
class CraftPlanTest {
    private CraftPlan.Ingredient needs(Integer... slots) { return new CraftPlan.Ingredient(false, Set.of(slots)); }
    private CraftPlan.Recipe recipe(CraftPlan.Ingredient... slots) {
        return new CraftPlan.Recipe("minecraft:test", false, 0, 0, 1, List.of(slots));
    }
    private CraftPlan.Plan plan(CraftPlan.Recipe recipe, List<CraftPlan.Supply> stock, int count) {
        return CraftPlan.prepare(List.of(recipe), stock, "minecraft:stick", 0, count);
    }
    private void valid(CraftPlan.Plan plan, CraftPlan.Recipe recipe, List<CraftPlan.Supply> stock) {
        Map<Integer, Integer> used = new HashMap<>(), assigned = new HashMap<>();
        for (var entry : plan.allocation()) {
            assertTrue(entry.count() > 0);
            assertTrue(recipe.ingredients().get(entry.ingredientIndex()).matchingInventorySlots().contains(entry.inventorySlot()));
            used.merge(entry.inventorySlot(), entry.count(), Integer::sum);
            assigned.merge(entry.ingredientIndex(), entry.count(), Integer::sum);
        }
        for (var supply : stock) assertTrue(used.getOrDefault(supply.inventorySlot(), 0) <= supply.count());
        for (int i = 0; i < recipe.ingredients().size(); i++)
            assertEquals(recipe.ingredients().get(i).empty() ? 0 : plan.target().batches(), assigned.getOrDefault(i, 0));
    }
    @Test void flexibleIngredientLeavesScarceMaterialForTheRestrictedSlot() {
        var recipe = recipe(needs(0, 1), needs(0)); var stock = List.of(new CraftPlan.Supply(0, 1), new CraftPlan.Supply(1, 1));
        var result = plan(recipe, stock, 1); valid(result, recipe, stock);
        assertTrue(result.allocation().contains(new CraftPlan.Allocation(0, 1, 1)));
        assertTrue(result.allocation().contains(new CraftPlan.Allocation(1, 0, 1)));
    }
    @Test void aSingleUnitCannotFillTwoIngredientSlots() {
        var error = assertThrows(Rejected.class, () -> plan(recipe(needs(0), needs(0)), List.of(new CraftPlan.Supply(0, 1)), 1));
        assertEquals("GAME_CRAFT_MATERIALS_MISSING", error.code);
    }
    @Test void allBatchesNeedDistinctMaterialUnits() {
        assertThrows(Rejected.class, () -> plan(recipe(needs(0)), List.of(new CraftPlan.Supply(0, 2)), 3));
    }
    @Test void oneIngredientCanUseSeveralActualInventoryStacks() {
        var recipe = recipe(needs(0, 1)); var stock = List.of(new CraftPlan.Supply(0, 2), new CraftPlan.Supply(1, 1));
        var result = plan(recipe, stock, 3); valid(result, recipe, stock); assertEquals(2, result.allocation().size());
    }
    @Test void outputIsRoundedUpWithoutSubtractingAlreadyOwnedProducts() {
        var recipe = new CraftPlan.Recipe("minecraft:planks", false, 0, 0, 4, List.of(needs(0)));
        var result = CraftPlan.prepare(List.of(recipe), List.of(new CraftPlan.Supply(0, 2)), "minecraft:oak_planks", 3, 5);
        assertEquals(2, result.target().batches()); assertEquals(8, result.target().plannedIncrement()); assertEquals(11, result.target().targetTotal());
    }
    @Test void shapedHolesAndTallNarrowRecipesPreserveTheirGridCoordinates() {
        var empty = new CraftPlan.Ingredient(true, Set.of());
        var recipe = new CraftPlan.Recipe("minecraft:tall", true, 1, 3, 1, List.of(needs(0), empty, needs(0)));
        var result = plan(recipe, List.of(new CraftPlan.Supply(0, 2)), 1);
        assertEquals(3, result.gridSize()); assertEquals(List.of(0, 3, 6), result.gridSlots());
        assertTrue(result.allocation().stream().noneMatch(entry -> entry.ingredientIndex() == 1));
    }
    @Test void fourShapelessIngredientsFitThePlayerGrid() {
        assertEquals(2, plan(recipe(needs(0), needs(0), needs(0), needs(0)), List.of(new CraftPlan.Supply(0, 4)), 1).gridSize());
    }
    @Test void fiveShapelessIngredientsRequireTheTableGrid() {
        var result = plan(recipe(needs(0), needs(0), needs(0), needs(0), needs(0)), List.of(new CraftPlan.Supply(0, 5)), 1);
        assertEquals(3, result.gridSize()); assertEquals(List.of(0, 1, 2, 3, 4), result.gridSlots());
    }
    @Test void noReceivedRecipeIsReportedAsUnavailable() {
        assertEquals("GAME_CRAFT_RECIPE_UNAVAILABLE", assertThrows(Rejected.class,
                () -> CraftPlan.prepare(List.of(), List.of(), "minecraft:stick", 0, 1)).code);
    }
    @Test void multipleRecipesNeverSelectByOrderOrAvailableMaterials() {
        assertEquals("GAME_CRAFT_RECIPE_AMBIGUOUS", assertThrows(Rejected.class,
                () -> CraftPlan.prepare(List.of(recipe(needs(0)), recipe(needs(1))), List.of(new CraftPlan.Supply(0, 1)), "minecraft:stick", 0, 1)).code);
    }
    @Test void duplicateInventoryIdentifiersCannotDuplicateCapacity() {
        assertEquals("GAME_CRAFT_INVENTORY_INVALID", assertThrows(Rejected.class,
                () -> plan(recipe(needs(0)), List.of(new CraftPlan.Supply(0, 1), new CraftPlan.Supply(0, 1)), 2)).code);
    }
    @Test void nonemptyIngredientWithoutAMatchingStackIsNotAnEmptyRecipeCell() {
        assertThrows(Rejected.class, () -> plan(recipe(needs()), List.of(new CraftPlan.Supply(0, 64)), 1));
    }
    @Test void malformedShapeOrAllEmptyInputsCannotBePrepared() {
        assertThrows(Rejected.class, () -> new CraftPlan.Recipe("minecraft:test", true, 3, 3, 1, List.of(needs(0))));
        assertThrows(Rejected.class, () -> new CraftPlan.Recipe("minecraft:test", true, 1, 1, 1,
                List.of(new CraftPlan.Ingredient(true, Set.of()))));
    }
    @Test void inventoryTotalOverflowCannotBeHiddenBySmallRequestedOutput() {
        assertThrows(Rejected.class, () -> CraftPlan.prepare(List.of(recipe(needs(0))), List.of(new CraftPlan.Supply(0, 1)),
                "minecraft:stick", Integer.MAX_VALUE, 1));
    }
    @Test void recordsDoNotRetainMutableIngredientOrOutputLists() {
        Set<Integer> slots = new HashSet<>(Set.of(0)); var ingredient = new CraftPlan.Ingredient(false, slots); slots.clear();
        List<CraftPlan.Ingredient> ingredients = new ArrayList<>(List.of(ingredient));
        var recipe = new CraftPlan.Recipe("minecraft:test", false, 0, 0, 1, ingredients); ingredients.clear();
        var result = plan(recipe, List.of(new CraftPlan.Supply(0, 1)), 1);
        assertThrows(UnsupportedOperationException.class, () -> result.allocation().clear());
        assertThrows(UnsupportedOperationException.class, () -> result.gridSlots().clear());
    }
    @Test void maximumRequestedBatchesUseCapacitiesWithoutExpandingPerItemNodes() {
        var recipe = recipe(needs(0), needs(0), needs(0), needs(0), needs(0), needs(0), needs(0), needs(0), needs(0));
        var stock = List.of(new CraftPlan.Supply(0, Integer.MAX_VALUE)); var result = plan(recipe, stock, 4096);
        valid(result, recipe, stock); assertEquals(9 * 4096, result.allocation().stream().mapToInt(CraftPlan.Allocation::count).sum());
    }
    @Test void everySmallMatchingGraphAgreesWithAnIndependentExhaustiveAssignment() {
        for (int graph = 0; graph < 64; graph++) for (int capacity = 0; capacity < 27; capacity++) for (int batches = 1; batches <= 2; batches++) {
            List<CraftPlan.Ingredient> ingredients = new ArrayList<>();
            for (int ingredient = 0; ingredient < 2; ingredient++) {
                Set<Integer> matches = new HashSet<>();
                for (int slot = 0; slot < 3; slot++) if ((graph & (1 << (ingredient * 3 + slot))) != 0) matches.add(slot);
                ingredients.add(new CraftPlan.Ingredient(false, matches));
            }
            int[] counts = {capacity % 3, capacity / 3 % 3, capacity / 9};
            List<CraftPlan.Supply> stock = new ArrayList<>(); for (int slot = 0; slot < 3; slot++) stock.add(new CraftPlan.Supply(slot, counts[slot]));
            var recipe = new CraftPlan.Recipe("minecraft:test", false, 0, 0, 1, ingredients);
            boolean possible = assign(ingredients, counts.clone(), batches, 0);
            try { var result = plan(recipe, stock, batches); assertTrue(possible); valid(result, recipe, stock); }
            catch (Rejected denied) { assertEquals("GAME_CRAFT_MATERIALS_MISSING", denied.code); assertFalse(possible); }
        }
    }
    private boolean assign(List<CraftPlan.Ingredient> ingredients, int[] counts, int batches, int unit) {
        if (unit == ingredients.size() * batches) return true;
        for (int slot : ingredients.get(unit / batches).matchingInventorySlots()) if (counts[slot] > 0) {
            counts[slot]--; if (assign(ingredients, counts, batches, unit + 1)) return true; counts[slot]++;
        }
        return false;
    }
}
