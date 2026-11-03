package dev.aitalkstreamer.mc.survival;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.InventoryTarget;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.ItemStack;
import net.minecraft.recipe.*;
import net.minecraft.registry.Registries;
import java.util.*;
import java.util.stream.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Current recipe and exact material stacks, re-read for preflight and again before execution. */
final class CraftSpec {
    final RecipeEntry<CraftingRecipe> entry;
    final CraftPlan.Plan plan;
    private final List<ItemStack> stock;
    private CraftSpec(RecipeEntry<CraftingRecipe> entry, CraftPlan.Plan plan, List<ItemStack> stock) {
        this.entry = entry; this.plan = plan; this.stock = stock.stream().map(ItemStack::copy).toList();
    }
    List<ItemStack> stock() { return stock.stream().map(ItemStack::copy).toList(); }
    /** Internal catalogue counts are absolute totals, unlike the public craft increment. */
    @SuppressWarnings("unchecked")
    static CraftSpec captureResource(adris.altoclef.util.RecipeTarget target) {
        SurvivalAuthority.requireScope();var client=MinecraftClient.getInstance();
        require(client.isOnThread() && client.world!=null && client.player!=null && client.getNetworkHandler()!=null,"GAME_WORLD_UNAVAILABLE");
        ItemStack output=new ItemStack(target.getOutputItem());String item=Registries.ITEM.getId(output.getItem()).toString();
        int baseline=0;
        for (int i=0;i<client.player.getInventory().size();i++) {
            var value=client.player.getInventory().getStack(i);if(value.isOf(target.getOutputItem())) baseline=Math.addExact(baseline,value.getCount());
        }
        if(baseline>=target.getTargetCount()) return null;
        List<ItemStack> stock=client.player.getInventory().main.stream().map(ItemStack::copy).toList();
        var supplies=IntStream.range(0,stock.size()).mapToObj(i->new CraftPlan.Supply(i,stock.get(i).getCount())).toList();
        var requested=target.getRecipe();var intentions=new ArrayList<CraftPlan.Ingredient>();
        for(int i=0;i<requested.getSlotCount();i++) {
            var slot=requested.getSlot(i);boolean empty=slot==null || slot.getMatches()==null || slot.getMatches().length==0;
            if(requested.isShapeless() && empty) continue;
            intentions.add(new CraftPlan.Ingredient(empty,empty?Set.of():IntStream.range(0,stock.size())
                    .filter(s->!stock.get(s).isEmpty() && slot.matches(stock.get(s).getItem())).boxed().collect(Collectors.toSet())));
        }
        var intent=new CraftPlan.Recipe("internal:intention",!requested.isShapeless(),requested.isShapeless()?0:requested.getWidth(),
                requested.isShapeless()?0:requested.getHeight(),requested.outputCount(),intentions);
        Map<String,RecipeEntry<CraftingRecipe>> entries=new HashMap<>();List<CraftPlan.Recipe> candidates=new ArrayList<>();
        for(var raw:client.getNetworkHandler().getRecipeManager().values()) {
            if(!(raw.value() instanceof ShapedRecipe || raw.value() instanceof ShapelessRecipe)) continue;
            var entry=(RecipeEntry<CraftingRecipe>)(RecipeEntry<?>)raw;var recipe=entry.value();
            var result=recipe.getResult(client.world.getRegistryManager());if(!result.isOf(target.getOutputItem())) continue;
            boolean shaped=recipe instanceof ShapedRecipe;var ingredients=recipe.getIngredients().stream().map(ingredient->
                    new CraftPlan.Ingredient(ingredient.isEmpty(),ingredient.isEmpty()?Set.of():IntStream.range(0,stock.size())
                            .filter(s->!stock.get(s).isEmpty() && ingredient.test(stock.get(s))).boxed().collect(Collectors.toSet()))).toList();
            candidates.add(new CraftPlan.Recipe(entry.id().toString(),shaped,shaped?((ShapedRecipe)recipe).getWidth():0,
                    shaped?((ShapedRecipe)recipe).getHeight():0,result.getCount(),ingredients));entries.put(entry.id().toString(),entry);
        }
        candidates.sort(Comparator.comparing(CraftPlan.Recipe::recipeId));
        var plan=ResourceRecipePlan.select(candidates,intent,supplies,item,baseline,target.getTargetCount(),List.of(),ResourceMaterials.limits());
        return new CraftSpec(entries.get(plan.recipeId()),plan,stock);
    }
    @SuppressWarnings("unchecked")
    static CraftSpec capture(JsonObject goal, InventoryTarget accepted) {
        MinecraftClient client = MinecraftClient.getInstance();
        require(client.isOnThread() && client.player != null && client.world != null && client.getNetworkHandler() != null,
                "GAME_WORLD_UNAVAILABLE");
        String item = str(goal, "item_id"); int requested = Math.toIntExact(num(goal, "count"));
        var candidates = client.getNetworkHandler().getRecipeManager().values().stream()
                .filter(e -> (e.value() instanceof ShapedRecipe || e.value() instanceof ShapelessRecipe)
                        && Registries.ITEM.getId(e.value().getResult(client.world.getRegistryManager()).getItem()).toString().equals(item))
                .sorted(Comparator.comparing(e -> e.id().toString())).toList();
        require(!candidates.isEmpty(), "GAME_CRAFT_RECIPE_UNAVAILABLE");
        require(candidates.size() == 1, "GAME_CRAFT_RECIPE_AMBIGUOUS");
        var entry = (RecipeEntry<CraftingRecipe>) (RecipeEntry<?>) candidates.getFirst();
        var recipe = entry.value(); var ingredients = recipe.getIngredients();
        ItemStack output = recipe.getResult(client.world.getRegistryManager());
        List<ItemStack> stock = client.player.getInventory().main.stream().map(ItemStack::copy).toList();
        int baseline = 0;
        for (int i = 0; i < client.player.getInventory().size(); i++) {
            var stack = client.player.getInventory().getStack(i);
            if (Registries.ITEM.getId(stack.getItem()).toString().equals(item)) baseline = Math.addExact(baseline, stack.getCount());
        }
        if (accepted != null) require(accepted.itemId().equals(item) && accepted.baseline() == baseline
                && accepted.requestedIncrement() == requested, "GAME_INVENTORY_BASELINE_CHANGED");
        var supplies = IntStream.range(0, stock.size()).mapToObj(i -> new CraftPlan.Supply(i, stock.get(i).getCount())).toList();
        var matches = ingredients.stream().map(ingredient -> new CraftPlan.Ingredient(ingredient.isEmpty(),
                ingredient.isEmpty() ? Set.of() : IntStream.range(0, stock.size())
                        .filter(i -> !stock.get(i).isEmpty() && ingredient.test(stock.get(i))).boxed().collect(Collectors.toSet()))).toList();
        boolean shaped = recipe instanceof ShapedRecipe;
        var plan = CraftPlan.prepare(List.of(new CraftPlan.Recipe(entry.id().toString(), shaped,
                shaped ? ((ShapedRecipe) recipe).getWidth() : 0, shaped ? ((ShapedRecipe) recipe).getHeight() : 0,
                output.getCount(), matches)), supplies, item, baseline, requested);
        return new CraftSpec(entry, plan, stock);
    }
}
