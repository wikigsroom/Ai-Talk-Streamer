package dev.aitalkstreamer.mc.survival;

import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Match a catalogue intention to current server recipes and allocate actual stock, never a cached recipe name. */
final class ResourceRecipePlan {
    static final int MAX_CANDIDATES = 64, SEARCH_LIMIT = 20000;
    private int searched;
    private record Box(int left, int top, int width, int height) { }
    private final List<CraftPlan.Supply> stock;
    private final String item;
    private final int baseline, needed;
    private final List<MaterialAllocation.Need> holds;
    private final List<MaterialAllocation.Limit> limits;
    private ResourceRecipePlan(List<CraftPlan.Supply> stock, String item, int baseline, int needed,List<MaterialAllocation.Need> holds,List<MaterialAllocation.Limit> limits) {
        this.stock=List.copyOf(stock);this.item=item;this.baseline=baseline;this.needed=needed;this.holds=List.copyOf(holds);this.limits=List.copyOf(limits);
    }
    static CraftPlan.Plan select(List<CraftPlan.Recipe> candidates, CraftPlan.Recipe intent,
                                 List<CraftPlan.Supply> stock, String item, int baseline, int targetTotal) {
        return select(candidates,intent,stock,item,baseline,targetTotal,List.of());
    }
    static CraftPlan.Plan select(List<CraftPlan.Recipe> candidates,CraftPlan.Recipe intent,List<CraftPlan.Supply> stock,
                                 String item,int baseline,int targetTotal,List<MaterialAllocation.Need> holds) {
        return select(candidates,intent,stock,item,baseline,targetTotal,holds,List.of());
    }
    static CraftPlan.Plan select(List<CraftPlan.Recipe> candidates,CraftPlan.Recipe intent,List<CraftPlan.Supply> stock,
                                 String item,int baseline,int targetTotal,List<MaterialAllocation.Need> holds,List<MaterialAllocation.Limit> limits) {
        require(baseline>=0 && targetTotal>=0,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        if (baseline>=targetTotal) return null;
        int needed=Math.subtractExact(targetTotal,baseline);
        require(needed<=4096,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        require(candidates.size()<=MAX_CANDIDATES && candidates.stream().map(CraftPlan.Recipe::recipeId).distinct().count()==candidates.size(),
                "GAME_RESOURCE_CRAFT_RECIPE_SET_INVALID");
        var search=new ResourceRecipePlan(stock,item,baseline,needed,holds,limits);
        CraftPlan.Plan selected=null;boolean compatible=false;
        for (var candidate:candidates) {
            if (candidate.outputPerBatch()!=intent.outputPerBatch() || cells(candidate).size()!=cells(intent).size()) continue;
            CraftPlan.Plan result;
            if (candidate.shaped() && intent.shaped()) {
                var actual=box(candidate);var expected=box(intent);
                if (actual.width()!=expected.width() || actual.height()!=expected.height()) continue;
                compatible=true;result=search.shaped(candidate,intent,actual,expected,false);
                if (result==null) result=search.shaped(candidate,intent,actual,expected,true);
            } else {
                compatible=true;
                result=search.unordered(candidate,intent,cells(candidate),cells(intent),0,new boolean[cells(intent).size()],new ArrayList<>(candidate.ingredients()));
            }
            if (result!=null) {
                require(selected==null,"GAME_CRAFT_RECIPE_AMBIGUOUS");selected=result;
            }
        }
        require(selected!=null,compatible?"GAME_CRAFT_MATERIALS_MISSING":"GAME_CRAFT_RECIPE_UNAVAILABLE");
        return selected;
    }
    private void step() { require(++searched<=SEARCH_LIMIT,"GAME_RESOURCE_CRAFT_SEARCH_LIMIT"); }
    private static List<Integer> cells(CraftPlan.Recipe recipe) {
        var result=new ArrayList<Integer>();
        for (int i=0;i<recipe.ingredients().size();i++) if (!recipe.ingredients().get(i).empty()) result.add(i);
        return result;
    }
    private static Box box(CraftPlan.Recipe recipe) {
        int left=recipe.width(),right=-1,top=recipe.height(),bottom=-1;
        for (int index:cells(recipe)) {int x=index%recipe.width(),y=index/recipe.width();left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
        return new Box(left,top,right-left+1,bottom-top+1);
    }
    private static CraftPlan.Ingredient intersection(CraftPlan.Ingredient actual,CraftPlan.Ingredient intended) {
        if (actual.empty()!=intended.empty()) return null;
        if (actual.empty()) return actual;
        var options=new HashSet<>(actual.matchingInventorySlots());options.retainAll(intended.matchingInventorySlots());
        return new CraftPlan.Ingredient(false,options);
    }
    private CraftPlan.Plan shaped(CraftPlan.Recipe recipe,CraftPlan.Recipe intent,Box actual,Box expected,boolean mirror) {
        step();var filtered=new ArrayList<>(recipe.ingredients());
        for (int y=0;y<actual.height();y++) for (int x=0;x<actual.width();x++) {
            int source=(actual.top()+y)*recipe.width()+actual.left()+x;
            int match=(expected.top()+y)*intent.width()+expected.left()+(mirror?expected.width()-1-x:x);
            var material=intersection(recipe.ingredients().get(source),intent.ingredients().get(match));
            if (material==null) return null;filtered.set(source,material);
        }
        return allocate(recipe,filtered);
    }
    private CraftPlan.Plan unordered(CraftPlan.Recipe recipe,CraftPlan.Recipe intent,List<Integer> actual,List<Integer> expected,
                                     int at,boolean[] used,List<CraftPlan.Ingredient> filtered) {
        step();if (at==actual.size()) return allocate(recipe,filtered);
        int source=actual.get(at);var seen=new HashSet<Set<Integer>>();
        for (int i=0;i<expected.size();i++) if (!used[i]) {
            var material=intersection(recipe.ingredients().get(source),intent.ingredients().get(expected.get(i)));
            if (material==null || material.matchingInventorySlots().isEmpty()
                    || !seen.add(intent.ingredients().get(expected.get(i)).matchingInventorySlots())) continue;
            filtered.set(source,material);used[i]=true;
            var result=unordered(recipe,intent,actual,expected,at+1,used,filtered);used[i]=false;
            if (result!=null) return result;
        }
        return null;
    }
    private CraftPlan.Plan allocate(CraftPlan.Recipe recipe,List<CraftPlan.Ingredient> ingredients) {
        step();
        try {return CraftPlan.prepare(List.of(new CraftPlan.Recipe(recipe.recipeId(),recipe.shaped(),recipe.width(),recipe.height(),
                recipe.outputPerBatch(),ingredients)),stock,item,baseline,needed,holds,limits);}
        catch (Rejected failure) {if (!failure.code.equals("GAME_CRAFT_MATERIALS_MISSING")) throw failure;return null;}
    }
}
