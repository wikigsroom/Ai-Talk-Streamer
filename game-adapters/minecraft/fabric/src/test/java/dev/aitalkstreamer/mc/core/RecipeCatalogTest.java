package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.Test;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

/** Explicit recipe-data fixtures; no Minecraft client is initialized here. */
class RecipeCatalogTest {
    private RecipeCatalog.Source source(String id, String item, int output) {
        return new RecipeCatalog.Source(id,"minecraft:crafting",item,output,"shapeless",0,0,
                ()->List.of(List.of("minecraft:oak_log","minecraft:birch_log")));
    }
    private JsonObject lookup(int count, RecipeCatalog.Source... sources) { return RecipeCatalog.lookup("minecraft:oak_planks",count,List.of(sources)); }
    @Test void batchesRespectRecipeOutputAndDoNotClaimInventoryOrAnEffect() {
        var result=lookup(7,source("minecraft:planks","minecraft:oak_planks",4));
        var choice=result.getAsJsonArray("recipes").get(0).getAsJsonObject();
        assertEquals(2,choice.get("batches").getAsInt());assertEquals(8,choice.get("output_for_batches").getAsInt());
        assertFalse(result.get("inventory_checked").getAsBoolean());assertFalse(result.has("effect_status"));
        assertTrue(result.getAsJsonArray("unknown_fields").contains(new JsonPrimitive("ingredient_components")));
    }
    @Test void multipleRecipesRemainAmbiguousAndOrderedWithoutChoosingOne() {
        var result=lookup(1,source("test:z","minecraft:oak_planks",4),source("test:a","minecraft:oak_planks",2));
        assertTrue(result.get("ambiguous").getAsBoolean());assertEquals(2,result.get("candidate_count").getAsInt());
        assertEquals("test:a",result.getAsJsonArray("recipes").get(0).getAsJsonObject().get("recipe_id").getAsString());
        assertFalse(result.has("selected_recipe_id"));
    }
    @Test void noReceivedRecipeDoesNotInventARecipeOrARestriction() {
        var result=lookup(1,source("test:other","minecraft:stick",4));
        assertFalse(result.get("recipe_known").getAsBoolean());assertEquals(0,result.getAsJsonArray("recipes").size());
        assertTrue(result.getAsJsonArray("unknown_fields").contains(new JsonPrimitive("unreceived_server_recipes")));
    }
    @Test void onlySelectedMatchingRecipesReadIngredientsAndEachQueryReadsItsOwnCatalog() {
        AtomicInteger reads=new AtomicInteger();var expensive=new RecipeCatalog.Source("test:other","minecraft:crafting","minecraft:stick",1,"other",0,0,()->{reads.incrementAndGet();throw new AssertionError();});
        lookup(1,expensive);assertEquals(0,reads.get());
        assertEquals(4,lookup(1,source("test:a","minecraft:oak_planks",4)).getAsJsonArray("recipes").get(0).getAsJsonObject().get("output_per_batch").getAsInt());
        assertEquals(2,lookup(1,source("test:a","minecraft:oak_planks",2)).getAsJsonArray("recipes").get(0).getAsJsonObject().get("output_per_batch").getAsInt());
    }
    @Test void recipeLimitIsExplicitAndIndependentOfIterationOrder() {
        List<RecipeCatalog.Source> many=new ArrayList<>();for(int i=0;i<20;i++)many.add(source("test:recipe_"+String.format("%02d",i),"minecraft:oak_planks",1));
        var a=RecipeCatalog.lookup("minecraft:oak_planks",1,many);Collections.reverse(many);
        assertEquals(a,RecipeCatalog.lookup("minecraft:oak_planks",1,many));assertEquals(16,a.getAsJsonArray("recipes").size());
        assertEquals(20,a.get("candidate_count").getAsInt());assertTrue(a.get("truncated").getAsBoolean());
    }
    @Test void alternativeLimitRetainsTotalAndTheEmptyShapedSlot() {
        List<String> alternatives=new ArrayList<>();for(int i=0;i<20;i++)alternatives.add("test:item_"+i);
        var source=new RecipeCatalog.Source("test:grid","minecraft:crafting","minecraft:oak_planks",1,"shaped",2,1,()->List.of(alternatives,List.of()));
        var result=lookup(1,source);var slots=result.getAsJsonArray("recipes").get(0).getAsJsonObject().getAsJsonArray("slots");
        assertEquals(16,slots.get(0).getAsJsonObject().getAsJsonArray("alternatives").size());
        assertEquals(20,slots.get(0).getAsJsonObject().get("alternatives_total").getAsInt());
        assertTrue(slots.get(1).getAsJsonObject().get("empty").getAsBoolean());assertTrue(result.get("truncated").getAsBoolean());
    }
    @Test void largeModdedTagRetainsRealVanillaMembersWithoutInventingTagMembership() {
        List<String> alternatives = new ArrayList<>();
        for (int i = 0; i < 612; i++) alternatives.add("chipped:planks_" + i);
        alternatives.add("minecraft:oak_planks");
        var source = new RecipeCatalog.Source("minecraft:stick", "minecraft:crafting", "minecraft:stick", 4,
                "shaped", 1, 2, () -> List.of(alternatives, alternatives));
        var result = RecipeCatalog.lookup("minecraft:stick", 4, List.of(source));
        var slot = result.getAsJsonArray("recipes").get(0).getAsJsonObject().getAsJsonArray("slots").get(0).getAsJsonObject();
        assertEquals(613, slot.get("alternatives_total").getAsInt());
        assertTrue(slot.get("truncated").getAsBoolean());
        assertEquals(16, slot.getAsJsonArray("alternatives").size());
        assertEquals("minecraft:oak_planks", slot.getAsJsonArray("alternatives").get(0).getAsString());
        for (var id : slot.getAsJsonArray("alternatives")) assertTrue(alternatives.contains(id.getAsString()));
        Collections.reverse(alternatives);
        assertEquals(result, RecipeCatalog.lookup("minecraft:stick", 4, List.of(source)));
    }
    @Test void serializedResultHasAByteBudgetAndMatchesTheEmbeddedContract() {
        List<String> alternatives=new ArrayList<>();for(int i=0;i<16;i++)alternatives.add("test:"+"a".repeat(130)+i);
        List<RecipeCatalog.Source> many=new ArrayList<>();for(int i=0;i<16;i++)many.add(new RecipeCatalog.Source("test:large_"+i,"minecraft:crafting","minecraft:oak_planks",1,"shaped",3,3,()->Collections.nCopies(9,alternatives)));
        var result=RecipeCatalog.lookup("minecraft:oak_planks",1,many);
        assertTrue(result.toString().getBytes(StandardCharsets.UTF_8).length<=RecipeCatalog.BYTE_LIMIT);
        assertTrue(result.get("truncated").getAsBoolean());assertTrue(result.getAsJsonArray("recipes").size()>0);
        result.addProperty("world_session_id","fixture-world");result.addProperty("based_on_seq",1);new Wire().validate("RecipeResult",result);
    }
    @Test void noIngredientProjectionStaysExplicitlyUnknown() {
        var result=lookup(1,new RecipeCatalog.Source("test:special","minecraft:crafting","minecraft:oak_planks",1,"other",0,0,List::of));
        assertFalse(result.getAsJsonArray("recipes").get(0).getAsJsonObject().get("ingredients_known").getAsBoolean());
    }
    @Test void oversizedCatalogAndInvalidAmountsFailWithTypedErrors() {
        var source=source("test:other","minecraft:stick",1);
        assertEquals("GAME_RECIPE_SCAN_LIMIT",assertThrows(Json.Rejected.class,()->RecipeCatalog.lookup("minecraft:oak_planks",1,Collections.nCopies(8193,source))).code);
        assertThrows(Json.Rejected.class,()->lookup(0));assertThrows(Json.Rejected.class,()->lookup(4097));
    }
    @Test void largeModdedCatalogFindsALateCandidateWithoutDroppingOutputBudgets() {
        var many = new ArrayList<>(Collections.nCopies(12000, source("test:other", "minecraft:stick", 1)));
        many.add(source("test:late_planks", "minecraft:oak_planks", 4));
        var result = RecipeCatalog.lookup("minecraft:oak_planks", 8, many, RecipeCatalog.MODDED_SCAN_LIMIT);
        assertTrue(result.get("recipe_known").getAsBoolean()); assertEquals(1, result.get("candidate_count").getAsInt());
        assertEquals(2, result.getAsJsonArray("recipes").get(0).getAsJsonObject().get("batches").getAsInt());
        assertTrue(result.toString().getBytes(StandardCharsets.UTF_8).length <= RecipeCatalog.BYTE_LIMIT);
    }
    @Test void moddedScanBudgetRemainsFiniteAndCannotChangeTheDefaultBudget() {
        var other = source("test:other", "minecraft:stick", 1);
        assertThrows(Json.Rejected.class, () -> RecipeCatalog.lookup("minecraft:oak_planks", 1,
                Collections.nCopies(RecipeCatalog.MODDED_SCAN_LIMIT + 1, other), RecipeCatalog.MODDED_SCAN_LIMIT));
        for (int budget : new int[]{0, RecipeCatalog.MODDED_SCAN_LIMIT + 1})
            assertEquals("GAME_RECIPE_SCAN_BUDGET_INVALID", assertThrows(Json.Rejected.class, () ->
                    RecipeCatalog.lookup("minecraft:oak_planks", 1, List.of(other), budget)).code);
        assertEquals("GAME_RECIPE_SCAN_LIMIT", assertThrows(Json.Rejected.class, () -> RecipeCatalog.lookup("minecraft:oak_planks", 1,
                Collections.nCopies(RecipeCatalog.SCAN_LIMIT + 1, other))).code);
    }
    @Test void unknownPortDoesNotPublishAnInventedRecipeImplementation() {
        GamePort port=new GamePort(){public void execute(Runnable r){}public void releaseInputs(){}public JsonObject capabilities(String s){return null;}public JsonObject check(JsonObject g){return null;}public void start(JsonObject t,ControlArbiter c,java.util.function.Consumer<JsonObject> done){}public void cancel(String r){}};
        assertEquals("GAME_CAPABILITY_UNAVAILABLE",assertThrows(Json.Rejected.class,()->port.recipe(Json.obj("item_id","minecraft:oak_planks","count",1))).code);
    }
    @Test void unsupportedModOutputDoesNotHideAKnownStaticRecipeOrClaimACompleteCatalogue() {
        var result = RecipeCatalog.lookupProjected("minecraft:oak_planks", 8, List.of("broken", "planks"), id -> {
            if (id.equals("broken")) throw new UnsupportedOperationException("fixture dynamic recipe");
            return source("test:planks", "minecraft:oak_planks", 4);
        }, RecipeCatalog.MODDED_SCAN_LIMIT);
        assertTrue(result.get("recipe_known").getAsBoolean()); assertTrue(result.get("truncated").getAsBoolean());
        assertEquals(1, result.get("candidate_count").getAsInt());
        assertTrue(result.getAsJsonArray("unknown_fields").contains(new JsonPrimitive("candidate_count")));
        result.addProperty("world_session_id", "fixture-world"); result.addProperty("based_on_seq", 1);
        new Wire().validate("RecipeResult", result);
    }
    @Test void unknownOutputCannotBeReportedAsNoRecipeAndEveryReceivedEntryConsumesTheScanBudget() {
        assertEquals("GAME_RECIPE_PROJECTION_UNAVAILABLE", assertThrows(Json.Rejected.class, () ->
                RecipeCatalog.lookupProjected("minecraft:oak_planks", 1, List.of(1), entry -> null, 1)).code);
        AtomicInteger projections = new AtomicInteger();
        assertEquals("GAME_RECIPE_SCAN_LIMIT", assertThrows(Json.Rejected.class, () ->
                RecipeCatalog.lookupProjected("minecraft:oak_planks", 1, List.of(1, 2), entry -> {
                    projections.incrementAndGet(); return null;
                }, 1)).code);
        assertEquals(1, projections.get());
    }
    @Test void incompleteProjectionKeepsItsByteBudgetAfterAddingUnknownMarkers() {
        List<String> alternatives = new ArrayList<>(); for (int i = 0; i < 16; i++) alternatives.add("test:" + "a".repeat(130) + i);
        var result = RecipeCatalog.lookupProjected("minecraft:oak_planks", 1, java.util.stream.IntStream.range(0, 17).boxed().toList(), i ->
                i == 16 ? null : new RecipeCatalog.Source("test:large_" + i, "minecraft:crafting", "minecraft:oak_planks", 1,
                        "shaped", 3, 3, () -> Collections.nCopies(9, alternatives)), RecipeCatalog.MODDED_SCAN_LIMIT);
        assertTrue(result.get("truncated").getAsBoolean()); assertFalse(result.getAsJsonArray("recipes").isEmpty());
        assertTrue(result.toString().getBytes(StandardCharsets.UTF_8).length <= RecipeCatalog.BYTE_LIMIT);
    }
    @Test void largeCandidateCountStillMatchesTheWireAndRetainsOnlySixteenChoices() {
        var many = java.util.stream.IntStream.range(0, 8200).mapToObj(i -> source("test:planks_" + i, "minecraft:oak_planks", 4)).toList();
        var result = RecipeCatalog.lookup("minecraft:oak_planks", 1, many, RecipeCatalog.MODDED_SCAN_LIMIT);
        assertEquals(8200, result.get("candidate_count").getAsInt()); assertEquals(16, result.getAsJsonArray("recipes").size());
        result.addProperty("world_session_id", "fixture-world"); result.addProperty("based_on_seq", 1);
        new Wire().validate("RecipeResult", result);
    }
}
