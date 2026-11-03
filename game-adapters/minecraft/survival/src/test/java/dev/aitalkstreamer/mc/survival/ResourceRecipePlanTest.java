package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.Json.Rejected;
import org.junit.jupiter.api.Test;
import java.util.*;
import java.util.stream.IntStream;
import static org.junit.jupiter.api.Assertions.*;

class ResourceRecipePlanTest {
    CraftPlan.Ingredient need(Integer... slots){return new CraftPlan.Ingredient(false,Set.of(slots));}
    CraftPlan.Ingredient empty(){return new CraftPlan.Ingredient(true,Set.of());}
    CraftPlan.Recipe plain(String id,int output,CraftPlan.Ingredient... items){return new CraftPlan.Recipe(id,false,0,0,output,List.of(items));}
    CraftPlan.Recipe shape(String id,int w,int h,CraftPlan.Ingredient... items){return new CraftPlan.Recipe(id,true,w,h,1,List.of(items));}
    List<CraftPlan.Supply> stock(int... counts){return IntStream.range(0,counts.length).mapToObj(i->new CraftPlan.Supply(i,counts[i])).toList();}
    CraftPlan.Plan select(List<CraftPlan.Recipe> actual,CraftPlan.Recipe intent,List<CraftPlan.Supply> stock,int baseline,int total){return ResourceRecipePlan.select(actual,intent,stock,"minecraft:stick",baseline,total);}
    void denied(String code,Runnable run){assertEquals(code,assertThrows(Rejected.class,run::run).code);}
    @Test void internalTotalCountsAreConvertedToAnIncrement(){var r=plain("live:a",4,need(0));var p=select(List.of(r),r,stock(1),6,8);assertEquals(2,p.target().requestedIncrement());assertEquals(1,p.target().batches());assertEquals(10,p.target().targetTotal());}
    @Test void aSatisfiedTotalDoesNotPlanAnyNewCraft(){assertNull(select(List.of(),plain("intent",1,need(0)),stock(),8,8));}
    @Test void paddedCatalogueShapeMatchesTheActualTrimmedRecipe(){var intent=shape("intent",2,2,need(0),empty(),need(0),empty());var actual=shape("live:stick",1,2,need(0),need(0));var p=select(List.of(actual),intent,stock(2),0,1);assertEquals(List.of(0,2),p.gridSlots());}
    @Test void leadingEmptyRowsAndColumnsDoNotChangeTheRequestedMaterials(){var intent=shape("intent",3,3,empty(),empty(),empty(),empty(),need(0),empty(),empty(),need(1),empty());var actual=shape("live:a",1,2,need(0),need(1));assertNotNull(select(List.of(actual),intent,stock(1,1),0,1));}
    @Test void shapedRecipesCanUseTheVanillaHorizontalMirror(){var actual=shape("live:a",2,1,need(0),need(1));var intent=shape("intent",2,1,need(1),need(0));var p=select(List.of(actual),intent,stock(1,1),0,1);assertTrue(p.allocation().contains(new CraftPlan.Allocation(0,0,1)));}
    @Test void aTallRecipeCannotBeSilentlyReplacedByAWideOne(){var actual=shape("live:a",2,1,need(0),need(0));var intent=shape("intent",1,2,need(0),need(0));denied("GAME_CRAFT_RECIPE_UNAVAILABLE",()->select(List.of(actual),intent,stock(2),0,1));}
    @Test void internalHolesStayEmptyInsteadOfBeingCompressed(){var actual=shape("live:a",3,1,need(0),empty(),need(1));var intent=shape("intent",3,1,need(0),need(1),empty());denied("GAME_CRAFT_RECIPE_UNAVAILABLE",()->select(List.of(actual),intent,stock(1,1),0,1));}
    @Test void anUnorderedNativeRecipePreservesAllCatalogueIngredients(){var actual=plain("live:a",1,need(0),need(1));var intent=shape("intent",2,2,need(1),empty(),need(0),empty());assertNotNull(select(List.of(actual),intent,stock(1,1),0,1));}
    @Test void anUnorderedIntentionCanUseTheActualNativeGrid(){var actual=shape("live:a",3,1,need(0),empty(),need(1));var intent=plain("intent",1,need(1),need(0));assertEquals(3,select(List.of(actual),intent,stock(1,1),0,1).gridSize());}
    @Test void nativeAndIntendedIngredientSetsAreBothEnforced(){var actual=plain("live:a",1,need(0));var intent=plain("intent",1,need(1));denied("GAME_CRAFT_MATERIALS_MISSING",()->select(List.of(actual),intent,stock(1,1),0,1));}
    @Test void oneUnitCannotSatisfyTwoRecipeRequirements(){var r=plain("live:a",1,need(0),need(0));denied("GAME_CRAFT_MATERIALS_MISSING",()->select(List.of(r),r,stock(1),0,1));}
    @Test void batchMaterialsCanComeFromSeveralActualStacks(){var r=plain("live:a",1,need(0,1));assertEquals(2,select(List.of(r),r,stock(1,2),0,3).allocation().size());}
    @Test void nativeOutputCountControlsRoundingForAllBatches(){var r=plain("live:a",4,need(0));var p=select(List.of(r),r,stock(2),3,8);assertEquals(2,p.target().batches());assertEquals(8,p.target().plannedIncrement());}
    @Test void twoExecutableServerRecipesRemainAnExplicitAmbiguity(){var a=plain("live:a",1,need(0));var b=plain("live:b",1,need(0));denied("GAME_CRAFT_RECIPE_AMBIGUOUS",()->select(List.of(a,b),a,stock(1),0,1));}
    @Test void onlyTheRecipeExecutableWithActualStockIsSelected(){var a=plain("live:a",1,need(0));var b=plain("live:b",1,need(1));var intent=plain("intent",1,need(0,1));assertEquals("live:b",select(List.of(a,b),intent,stock(0,1),0,1).recipeId());}
    @Test void candidateOrderCannotResolveAnAmbiguity(){var a=plain("live:a",1,need(0));var b=plain("live:b",1,need(0));denied("GAME_CRAFT_RECIPE_AMBIGUOUS",()->select(List.of(b,a),a,stock(1),0,1));}
    @Test void eachSelectionUsesTheSuppliedCurrentRecipeSet(){var a=plain("live:before",1,need(0));var b=plain("live:after",1,need(0));assertEquals("live:before",select(List.of(a),a,stock(1),0,1).recipeId());assertEquals("live:after",select(List.of(b),a,stock(1),0,1).recipeId());}
    @Test void changedOutputMetadataCannotSilentlyUseTheOldCatalogueCount(){var a=plain("live:a",4,need(0));var intent=plain("intent",1,need(0));denied("GAME_CRAFT_RECIPE_UNAVAILABLE",()->select(List.of(a),intent,stock(1),0,1));}
    @Test void duplicateServerRecipeIdentifiersAreRejected(){var a=plain("live:a",1,need(0));denied("GAME_RESOURCE_CRAFT_RECIPE_SET_INVALID",()->select(List.of(a,a),a,stock(2),0,1));}
    @Test void candidateSetsAreBoundedBeforeSearch(){var list=IntStream.range(0,65).mapToObj(i->plain("live:"+i,1,need(0))).toList();denied("GAME_RESOURCE_CRAFT_RECIPE_SET_INVALID",()->select(list,list.getFirst(),stock(1),0,1));}
    @Test void anInternalRequestCannotExpandBeyondThePublicMaterialBudget(){var a=plain("live:a",1,need(0));denied("GAME_RESOURCE_CRAFT_TARGET_INVALID",()->select(List.of(a),a,stock(5000),0,4097));}
    @Test void negativeInventoryOrTargetFactsAreRejected(){var a=plain("live:a",1,need(0));denied("GAME_RESOURCE_CRAFT_TARGET_INVALID",()->select(List.of(a),a,stock(1),-1,1));denied("GAME_RESOURCE_CRAFT_TARGET_INVALID",()->select(List.of(a),a,stock(1),0,-1));}
    @Test void flexibleMatchesLeaveScarceUnitsForRestrictedIngredients(){var actual=plain("live:a",1,need(0,1),need(0));var intent=plain("intent",1,need(0),need(0,1));var p=select(List.of(actual),intent,stock(1,1),0,1);assertTrue(p.allocation().contains(new CraftPlan.Allocation(0,1,1)));}
    @Test void identicalIntentSlotsDoNotManufactureRecipeAmbiguity(){var r=plain("live:a",1,need(0),need(0),need(0));assertNotNull(select(List.of(r),r,stock(3),0,1));}
    @Test void noServerRecipeCannotFallBackToAnUnverifiedManualPattern(){var r=plain("intent",1,need(0));denied("GAME_CRAFT_RECIPE_UNAVAILABLE",()->select(List.of(),r,stock(1),0,1));}
    @Test void pathologicalUnorderedSearchTerminatesAtItsFixedBudget(){var ingredients=IntStream.range(0,9).mapToObj(i->need(0,1,2,3,4,5,6,7,8)).toArray(CraftPlan.Ingredient[]::new);var intent=plain("intent",1,IntStream.range(0,9).mapToObj(i->need(i)).toArray(CraftPlan.Ingredient[]::new));var actual=plain("live:a",1,ingredients);denied("GAME_RESOURCE_CRAFT_SEARCH_LIMIT",()->select(List.of(actual),intent,stock(1,1,1,1,1,1,1,1,0),0,1));}
}
