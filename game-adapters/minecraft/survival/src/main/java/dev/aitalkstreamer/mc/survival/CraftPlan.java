package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.InventoryTarget;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Prepares a current-recipe material allocation. It is not a crafting-effect receipt. */
public final class CraftPlan {
    public record Supply(int inventorySlot, int count) {
        public Supply { require(inventorySlot >= 0 && inventorySlot < 36 && count >= 0, "GAME_CRAFT_INVENTORY_INVALID"); }
    }
    public record Ingredient(boolean empty, Set<Integer> matchingInventorySlots) {
        public Ingredient {
            matchingInventorySlots = Set.copyOf(matchingInventorySlots);
            require(!empty || matchingInventorySlots.isEmpty(), "GAME_CRAFT_INGREDIENT_INVALID");
            require(matchingInventorySlots.stream().allMatch(slot -> slot >= 0 && slot < 36), "GAME_CRAFT_INGREDIENT_INVALID");
        }
    }
    public record Recipe(String recipeId, boolean shaped, int width, int height, int outputPerBatch, List<Ingredient> ingredients) {
        public Recipe {
            ingredients = List.copyOf(ingredients);
            require(recipeId != null && !recipeId.isBlank() && ingredients.size() >= 1 && ingredients.size() <= 9,
                    "GAME_CRAFT_RECIPE_UNAVAILABLE");
            require(outputPerBatch >= 1 && outputPerBatch <= 4096, "GAME_CRAFT_OUTPUT_COUNT_INVALID");
            if (shaped) require(width >= 1 && width <= 3 && height >= 1 && height <= 3 && ingredients.size() == width * height,
                    "GAME_CRAFT_RECIPE_UNAVAILABLE");
            else require(width == 0 && height == 0 && ingredients.stream().noneMatch(Ingredient::empty), "GAME_CRAFT_RECIPE_UNAVAILABLE");
            require(ingredients.stream().anyMatch(slot -> !slot.empty()), "GAME_CRAFT_RECIPE_UNAVAILABLE");
        }
    }
    public record Allocation(int ingredientIndex, int inventorySlot, int count) { }
    public record Plan(String recipeId, int gridSize, List<Integer> gridSlots, InventoryTarget target, List<Allocation> allocation) {
        public Plan { gridSlots = List.copyOf(gridSlots); allocation = List.copyOf(allocation); }
    }
    private CraftPlan() { }
    static int[] remainingBySlot(Plan plan,int[] remaining) {
        require(remaining.length==plan.allocation().size(),"GAME_CRAFT_ALLOCATION_INVALID");int[] result=new int[36];
        for(int i=0;i<remaining.length;i++) {
            var original=plan.allocation().get(i);
            require(remaining[i]>=0 && remaining[i]<=original.count(),"GAME_CRAFT_ALLOCATION_INVALID");
            result[original.inventorySlot()]=Math.addExact(result[original.inventorySlot()],remaining[i]);
        }
        return result;
    }

    public static Plan prepare(List<Recipe> candidates, List<Supply> inventory, String itemId, int baseline, int requestedIncrement) {
        return prepare(candidates,inventory,itemId,baseline,requestedIncrement,List.of());
    }
    static Plan prepare(List<Recipe> candidates,List<Supply> inventory,String itemId,int baseline,int requestedIncrement,List<MaterialAllocation.Need> holds) {
        return prepare(candidates,inventory,itemId,baseline,requestedIncrement,holds,List.of());
    }
    static Plan prepare(List<Recipe> candidates,List<Supply> inventory,String itemId,int baseline,int requestedIncrement,
                        List<MaterialAllocation.Need> holds,List<MaterialAllocation.Limit> limits) {
        require(holds.stream().allMatch(MaterialAllocation.Need::retained),"GAME_MATERIAL_REQUIREMENT_INVALID");
        require(!candidates.isEmpty(), "GAME_CRAFT_RECIPE_UNAVAILABLE");
        require(candidates.size() == 1, "GAME_CRAFT_RECIPE_AMBIGUOUS");
        require(inventory.size() <= 36 && inventory.stream().map(Supply::inventorySlot).distinct().count() == inventory.size(),
                "GAME_CRAFT_INVENTORY_INVALID");
        Recipe recipe = candidates.getFirst();
        InventoryTarget target = new InventoryTarget(itemId, baseline, requestedIncrement, recipe.outputPerBatch());
        int grid = recipe.shaped() ? recipe.width() <= 2 && recipe.height() <= 2 ? 2 : 3
                : recipe.ingredients().size() <= 4 ? 2 : 3;
        List<Integer> positions = new ArrayList<>();
        for (int i = 0; i < recipe.ingredients().size(); i++) positions.add(recipe.shaped()
                ? (i / recipe.width()) * grid + i % recipe.width() : i);

        var needs=new ArrayList<>(holds);
        for(int i=0;i<recipe.ingredients().size();i++) {
            var ingredient=recipe.ingredients().get(i);
            if(!ingredient.empty()) needs.add(new MaterialAllocation.Need("ingredient:"+i,target.batches(),ingredient.matchingInventorySlots(),false));
        }
        var assigned=limits.isEmpty()?MaterialAllocation.allocate(inventory,needs):MaterialAllocation.constrained(inventory,needs,limits);
        require(assigned.complete(),"GAME_CRAFT_MATERIALS_MISSING");
        List<Allocation> allocation=new ArrayList<>();
        for(var part:assigned.assignments()) if(part.key().startsWith("ingredient:"))
            allocation.add(new Allocation(Integer.parseInt(part.key().substring("ingredient:".length())),part.slot(),part.count()));
        allocation.sort(Comparator.comparingInt(Allocation::ingredientIndex).thenComparingInt(Allocation::inventorySlot));
        return new Plan(recipe.recipeId(), grid, positions, target, allocation);
    }
}
