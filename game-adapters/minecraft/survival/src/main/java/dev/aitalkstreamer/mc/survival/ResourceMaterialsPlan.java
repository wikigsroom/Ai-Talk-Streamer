package dev.aitalkstreamer.mc.survival;

import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Catalogue acquisition budget; native crafting separately verifies actual recipes and components. */
final class ResourceMaterialsPlan {
    record Stock(int slot,String item,int count) {
        Stock {new CraftPlan.Supply(slot,count);require(item!=null && !item.isBlank(),"GAME_MATERIAL_STOCK_INVALID");}
    }
    record Goal(String output,int baseline,int targetTotal,int outputPerBatch,List<Set<String>> ingredients) {
        Goal {
            require(output!=null && !output.isBlank() && baseline>=0 && targetTotal>=0 && outputPerBatch>0 && outputPerBatch<=4096,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
            require(ingredients.size()<=9 && !ingredients.isEmpty(),"GAME_MATERIAL_REQUIREMENT_INVALID");
            ingredients=ingredients.stream().map(Set::copyOf).toList();
            require(ingredients.stream().allMatch(options->options.size()<=256 && options.stream().allMatch(v->v!=null && !v.isBlank())),"GAME_MATERIAL_REQUIREMENT_INVALID");
        }
    }
    record Request(Set<String> items,int missing,int currentMatching,int targetMatching) {
        Request {items=Set.copyOf(items);}
    }
    record Plan(MaterialAllocation.Result allocation,List<Request> requests) {
        Plan {requests=List.copyOf(requests);}
        boolean complete() {return allocation.complete();}
    }
    static List<MaterialAllocation.Need> holds(List<Stock> stock,Map<String,Integer> desired) {
        var result=new ArrayList<MaterialAllocation.Need>();
        require(desired.size()<=MaterialReservations.MAX_OUTPUTS,"GAME_MATERIAL_RESERVATION_LIMIT");
        for(var entry:new TreeMap<>(desired).entrySet()) {
            require(entry.getValue()>=0,"GAME_MATERIAL_REQUIREMENT_INVALID");
            int have=count(stock,Set.of(entry.getKey())),keep=Math.min(have,entry.getValue());
            if(keep>0) result.add(new MaterialAllocation.Need("hold:"+entry.getKey(),keep,slots(stock,Set.of(entry.getKey())),true));
        }
        return result;
    }
    static Map<String,Integer> quantities(List<Stock> stock) {
        var counts=new TreeMap<String,Integer>();for(var value:stock) if(value.count()>0) counts.merge(value.item(),value.count(),Math::addExact);return Map.copyOf(counts);
    }
    private static int count(List<Stock> stock,Set<String> options) {
        int count=0;for(var item:stock) if(options.contains(item.item())) count=Math.addExact(count,item.count());return count;
    }
    private static Set<Integer> slots(List<Stock> stock,Set<String> options) {
        var result=new HashSet<Integer>();for(var item:stock) if(item.count()>0 && options.contains(item.item())) result.add(item.slot());return result;
    }
    static Plan prepare(List<Goal> goals,List<Stock> stock,Map<String,Integer> inheritedHolds) {
        return prepare(goals,stock,MaterialTargets.from(inheritedHolds));
    }
    static Plan prepare(List<Goal> goals,List<Stock> stock,MaterialTargets inheritedHolds) {
        require(goals.size()<=64 && !goals.isEmpty(),"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        require(stock.size()<=36 && stock.stream().map(Stock::slot).distinct().count()==stock.size(),"GAME_CRAFT_INVENTORY_INVALID");
        var desired=inheritedHolds;var grouped=new HashMap<Set<String>,Integer>();
        var unique=new LinkedHashMap<String,Goal>();
        for(var goal:goals) {
            var old=unique.get(goal.output());
            require(old==null || old.baseline()==goal.baseline() && old.outputPerBatch()==goal.outputPerBatch() && old.ingredients().equals(goal.ingredients()),"GAME_RESOURCE_MATERIAL_TARGET_AMBIGUOUS");
            if(old==null || goal.targetTotal()>old.targetTotal()) unique.put(goal.output(),goal);
        }
        for(var goal:unique.values()) {
            desired=desired.merge(MaterialTargets.from(Map.of(goal.output(),goal.targetTotal())));
            int missing=Math.max(0,goal.targetTotal()-goal.baseline());require(missing<=4096,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
            if(missing==0) continue;
            int batches=(missing+goal.outputPerBatch()-1)/goal.outputPerBatch();
            for(var options:goal.ingredients()) if(!options.isEmpty()) grouped.merge(options,batches,Math::addExact);
        }
        return allocate(stock,desired,grouped);
    }
    static Plan materials(Set<String> items,int count,List<Stock> stock,Map<String,Integer> desired) {
        return materials(items,count,stock,MaterialTargets.from(desired));
    }
    static Plan materials(Set<String> items,int count,List<Stock> stock,MaterialTargets desired) {
        require(items!=null && !items.isEmpty() && items.size()<=256 && items.stream().allMatch(s->s!=null && !s.isBlank())
                && count>0 && count<=4096,"GAME_MATERIAL_REQUIREMENT_INVALID");
        return allocate(stock,desired,Map.of(Set.copyOf(items),count));
    }
    static Map<Integer,Integer> available(List<Stock> stock,Map<String,Integer> desired) {
        return available(stock,MaterialTargets.from(desired));
    }
    static Map<Integer,Integer> available(List<Stock> stock,MaterialTargets desired) {
        var candidates=new HashSet<Integer>();for(var value:stock)candidates.add(value.slot());
        var selected=usable(stock,desired,candidates);var result=new TreeMap<Integer,Integer>();
        for(var value:stock)result.put(value.slot(),selected.getOrDefault(value.slot(),0));return Map.copyOf(result);
    }
    /** Retained outputs may move to an equal item stack while exact component-aware consumers share capacity. */
    static Map<String,Integer> singleUnits(List<Stock> stock,Map<String,Integer> desired,Map<String,Set<Integer>> candidates) {
        return singleUnits(stock,MaterialTargets.from(desired),candidates);
    }
    static Map<String,Integer> singleUnits(List<Stock> stock,MaterialTargets desired,Map<String,Set<Integer>> candidates) {
        require(candidates!=null && !candidates.isEmpty() && candidates.size()<=64
                && candidates.entrySet().stream().allMatch(e->e.getKey()!=null && !e.getKey().isBlank() && e.getValue()!=null),"GAME_MATERIAL_REQUIREMENT_INVALID");
        var needs=new ArrayList<MaterialAllocation.Need>();
        for(var entry:new TreeMap<>(candidates).entrySet()) needs.add(new MaterialAllocation.Need("consume:"+entry.getKey(),1,entry.getValue(),false));
        var result=allocate(stock,desired,needs);
        if(!result.complete()) return Map.of();
        var selected=new TreeMap<String,Integer>();
        for(var assignment:result.assignments()) if(assignment.key().startsWith("consume:")) selected.put(assignment.key().substring(8),assignment.slot());
        return Map.copyOf(selected);
    }
    /** Counted raw units and one exact fuel share the same stock and retained-output capacity. */
    static int conversionFuel(List<Stock> stock,Map<String,Integer> desired,int rawSlot,int rawCount,Set<Integer> fuels) {
        return conversionFuel(stock,MaterialTargets.from(desired),rawSlot,rawCount,fuels);
    }
    static int conversionFuel(List<Stock> stock,MaterialTargets desired,int rawSlot,int rawCount,Set<Integer> fuels) {
        require(rawCount>0 && rawCount<=4 && fuels!=null,"GAME_MATERIAL_REQUIREMENT_INVALID");
        var needs=new ArrayList<MaterialAllocation.Need>();
        needs.add(new MaterialAllocation.Need("consume:raw",rawCount,Set.of(rawSlot),false));
        needs.add(new MaterialAllocation.Need("consume:fuel",1,fuels,false));
        var result=allocate(stock,desired,needs);
        if(!result.complete())return -1;
        return result.assignments().stream().filter(a->a.key().equals("consume:fuel")).findFirst().orElseThrow().slot();
    }
    static boolean removable(List<Stock> stock,Map<String,Integer> desired,int slot,int count) {
        return removable(stock,MaterialTargets.from(desired),slot,count);
    }
    static boolean removable(List<Stock> stock,MaterialTargets desired,int slot,int count) {
        require(count>0 && count<=99,"GAME_MATERIAL_REQUIREMENT_INVALID");
        var needs=new ArrayList<MaterialAllocation.Need>();
        needs.add(new MaterialAllocation.Need("consume:remove",count,Set.of(slot),false));
        return allocate(stock,desired,needs).complete();
    }
    /** Cursor/offhand contents are outside the main inventory, but may still fulfill a retained target. */
    static int externalUsable(List<Stock> stock,Map<String,Integer> desired,String item,int count) {
        return externalUsable(stock,MaterialTargets.from(desired),item,count);
    }
    static int externalUsable(List<Stock> stock,MaterialTargets desired,String item,int count) {
        return desired.externalUsable(stock,item,count);
    }
    /** Maximize usable units jointly with retained outputs; no writes and no reservation of a future item. */
    static Map<Integer,Integer> usable(List<Stock> stock,Map<String,Integer> desired,Set<Integer> candidates) {
        return usable(stock,MaterialTargets.from(desired),candidates);
    }
    static Map<Integer,Integer> usable(List<Stock> stock,MaterialTargets desired,Set<Integer> candidates) {
        require(candidates!=null,"GAME_MATERIAL_REQUIREMENT_INVALID");
        var needs=new ArrayList<MaterialAllocation.Need>();int total=0;
        for(var value:stock) if(candidates.contains(value.slot())) total=Math.addExact(total,value.count());
        needs.add(new MaterialAllocation.Need("consume:usable",total,candidates,false));
        var result=allocate(stock,desired,needs);
        var selected=new TreeMap<Integer,Integer>();
        for(var assignment:result.assignments()) if(assignment.key().equals("consume:usable")) selected.merge(assignment.slot(),assignment.count(),Math::addExact);
        return Map.copyOf(selected);
    }
    private static MaterialAllocation.Result allocate(List<Stock> stock,MaterialTargets desired,List<MaterialAllocation.Need> needs) {
        return MaterialAllocation.constrained(stock.stream().map(s->new CraftPlan.Supply(s.slot(),s.count())).toList(),needs,desired.limits(stock));
    }
    private static Plan allocate(List<Stock> stock,MaterialTargets desired,Map<Set<String>,Integer> grouped) {
        require(stock.size()<=36 && stock.stream().map(Stock::slot).distinct().count()==stock.size(),"GAME_CRAFT_INVENTORY_INVALID");
        var needs=new ArrayList<MaterialAllocation.Need>();var materials=new LinkedHashMap<String,Set<String>>();
        var groups=new ArrayList<>(grouped.keySet());groups.sort(Comparator.<Set<String>>comparingInt(Set::size).thenComparing(s->String.join("\n",new TreeSet<>(s))));
        for(int i=0;i<groups.size();i++) {String key="material:"+i;var options=groups.get(i);materials.put(key,options);needs.add(new MaterialAllocation.Need(key,grouped.get(options),slots(stock,options),false));}
        var result=allocate(stock,desired,needs);
        var requests=new ArrayList<Request>();
        for(var entry:materials.entrySet()) {
            int missing=result.missing().getOrDefault(entry.getKey(),0);if(missing==0) continue;
            int have=count(stock,entry.getValue());requests.add(new Request(entry.getValue(),missing,have,Math.addExact(have,missing)));
        }
        return new Plan(result,requests);
    }
}
