package dev.aitalkstreamer.mc.survival;

import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Absolute inventory conditions: every group keeps its total, and groups may share the same items. */
record MaterialTargets(Map<Set<String>,Integer> goals) {
    MaterialTargets {
        require(goals!=null && goals.size()<=MaterialReservations.MAX_OUTPUTS,"GAME_MATERIAL_RESERVATION_LIMIT");
        var copy=new LinkedHashMap<Set<String>,Integer>();var kinds=new HashSet<String>();
        for(var entry:goals.entrySet()) {
            var items=entry.getKey();var count=entry.getValue();
            require(items!=null && !items.isEmpty() && items.size()<=256 && count!=null && count>=0
                    && items.stream().allMatch(s->s!=null && !s.isBlank()),"GAME_MATERIAL_REQUIREMENT_INVALID");
            copy.merge(Set.copyOf(items),count,Math::max);kinds.addAll(items);
        }
        require(kinds.size()<=MaterialReservations.MAX_OUTPUTS,"GAME_MATERIAL_RESERVATION_LIMIT");
        goals=Collections.unmodifiableMap(copy);
    }
    static MaterialTargets from(Map<String,Integer> values) {
        require(values!=null,"GAME_MATERIAL_REQUIREMENT_INVALID");var result=new LinkedHashMap<Set<String>,Integer>();
        for(var entry:values.entrySet()) {
            require(entry.getKey()!=null,"GAME_MATERIAL_REQUIREMENT_INVALID");result.put(Set.of(entry.getKey()),entry.getValue());
        }
        return new MaterialTargets(result);
    }
    MaterialTargets merge(MaterialTargets other) {
        var result=new LinkedHashMap<>(goals);other.goals.forEach((items,count)->result.merge(items,count,Math::max));return new MaterialTargets(result);
    }
    List<MaterialAllocation.Limit> limits(List<ResourceMaterialsPlan.Stock> stock) {
        require(stock.size()<=36 && stock.stream().map(ResourceMaterialsPlan.Stock::slot).distinct().count()==stock.size(),"GAME_CRAFT_INVENTORY_INVALID");
        var result=new ArrayList<MaterialAllocation.Limit>();
        for(var entry:goals.entrySet()) {
            int have=0;var slots=new HashSet<Integer>();
            for(var value:stock) if(entry.getKey().contains(value.item()) && value.count()>0) {have=Math.addExact(have,value.count());slots.add(value.slot());}
            // An incomplete target retains what is already present, without reserving future stock.
            if(!slots.isEmpty() && entry.getValue()>0) result.add(new MaterialAllocation.Limit(slots,Math.max(0,have-entry.getValue())));
        }
        return List.copyOf(result);
    }
    int externalUsable(List<ResourceMaterialsPlan.Stock> stock,String item,int count) {
        require(item!=null && !item.isBlank() && count>=0 && count<=99 && stock.size()<=36
                && stock.stream().map(ResourceMaterialsPlan.Stock::slot).distinct().count()==stock.size(),"GAME_MATERIAL_STOCK_INVALID");
        int free=count;
        for(var entry:goals.entrySet()) if(entry.getKey().contains(item)) {
            long have=count;for(var value:stock) if(entry.getKey().contains(value.item())) have+=value.count();
            free=(int)Math.min(free,Math.max(0,have-entry.getValue()));
        }
        return free;
    }
}
