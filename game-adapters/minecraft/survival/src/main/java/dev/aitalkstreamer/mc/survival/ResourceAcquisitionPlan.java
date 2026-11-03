package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.function.Predicate;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Bounded state for actual acquisition paths within one original execution root. */
final class ResourceAcquisitionPlan {
    static final int MAX_ACTIVE=64, MAX_SOURCES=512, MAX_FAILURES=512;
    enum Kind { CATALOGUE, ITEM }
    record Source(Kind kind,String name,Set<String> items) {
        Source {
            require(kind!=null && name!=null && !name.isBlank() && name.length()<=256,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
            require(items!=null && !items.isEmpty() && items.size()<=256
                    && items.stream().allMatch(v->v!=null && !v.isBlank()),"GAME_MATERIAL_REQUIREMENT_INVALID");
            items=Set.copyOf(items);
            require(kind!=Kind.ITEM || items.contains(name),"GAME_MATERIAL_REQUIREMENT_INVALID");
        }
    }
    record Choice(Source source,boolean blockedByCycle,boolean blockedByFailure) { }
    private record Claim(Source source,Map<String,Integer> baseline,Map<String,Integer> cycleContext) { }
    private record Failed(Source source,Map<String,Integer> stock) { }
    record Failure(Source source,Map<String,Integer> stock,String reason) {
        Failure {stock=Map.copyOf(stock);}
    }
    private final IdentityHashMap<Object,Claim> active=new IdentityHashMap<>();
    private final Map<Failed,String> failures=new HashMap<>();

    private static Map<String,Integer> quantities(List<ResourceMaterialsPlan.Stock> stock) {
        require(stock!=null && stock.size()<=36 && stock.stream().allMatch(Objects::nonNull)
                && stock.stream().map(ResourceMaterialsPlan.Stock::slot).distinct().count()==stock.size(),"GAME_CRAFT_INVENTORY_INVALID");
        return ResourceMaterialsPlan.quantities(stock);
    }
    private boolean cycle(Object owner,Source source,Map<String,Integer> stock,Predicate<Object> isAncestor) {
        for(var entry:active.entrySet()) if(entry.getKey()!=owner && isAncestor.test(entry.getKey())
                && entry.getValue().source().equals(source) && entry.getValue().cycleContext().equals(stock)) return true;
        return false;
    }
    Choice choose(Object owner,List<Source> sources,List<ResourceMaterialsPlan.Stock> stock,Predicate<Object> isAncestor) {
        require(owner!=null && sources!=null && sources.size()<=MAX_SOURCES && sources.stream().allMatch(Objects::nonNull)
                && isAncestor!=null,"GAME_MATERIAL_REQUIREMENT_LIMIT");
        var counts=quantities(stock);boolean cycle=false,failed=false;
        for(var source:new LinkedHashSet<>(sources)) {
            if(cycle(owner,source,counts,isAncestor)) {cycle=true;continue;}
            if(failures.containsKey(new Failed(source,counts))) {failed=true;continue;}
            return new Choice(source,cycle,failed);
        }
        return new Choice(null,cycle,failed);
    }
    void begin(Object owner,Source source,List<ResourceMaterialsPlan.Stock> baseline,List<ResourceMaterialsPlan.Stock> stock,Predicate<Object> isAncestor) {
        require(owner!=null && source!=null && isAncestor!=null,"GAME_MATERIAL_REQUIREMENT_INVALID");
        var before=quantities(baseline);var now=quantities(stock);var previous=active.get(owner);
        if(previous!=null) {
            require(previous.source().equals(source) && previous.baseline().equals(before),"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");
            return;
        }
        require(active.size()<MAX_ACTIVE,"GAME_MATERIAL_RESERVATION_LIMIT");
        require(!cycle(owner,source,now,isAncestor),"GAME_RESOURCE_MATERIAL_CYCLE");
        active.put(owner,new Claim(source,before,now));
    }
    boolean finish(Object owner,List<ResourceMaterialsPlan.Stock> stock) {
        var claim=active.get(owner);require(claim!=null,"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");
        var now=quantities(stock);long before=0,after=0;
        for(var item:claim.source().items()) {before+=claim.baseline().getOrDefault(item,0);after+=now.getOrDefault(item,0);}
        boolean gained=after>before;
        if(gained) failures.keySet().removeIf(value->value.source().equals(claim.source()));
        else remember(claim,now,"GAME_RESOURCE_MATERIAL_NO_PROGRESS");
        active.remove(owner);return gained;
    }
    private void remember(Claim claim,Map<String,Integer> now,String reason) {
        var additions=new HashSet<>(List.of(new Failed(claim.source(),claim.baseline()),new Failed(claim.source(),now)));
        additions.removeAll(failures.keySet());require(failures.size()+additions.size()<=MAX_FAILURES,"GAME_MATERIAL_REQUIREMENT_LIMIT");
        for(var failure:additions)failures.put(failure,reason);
    }
    void failed(Object owner,List<ResourceMaterialsPlan.Stock> stock,String reason) {
        require(ResourceBranchRecovery.recoverable(reason),"GAME_MATERIAL_REQUIREMENT_INVALID");
        var claim=active.get(owner);require(claim!=null,"GAME_RESOURCE_MATERIAL_CONTEXT_CHANGED");
        remember(claim,quantities(stock),reason);active.remove(owner);
    }
    List<Failure> failures() {
        return failures.entrySet().stream().map(e->new Failure(e.getKey().source(),e.getKey().stock(),e.getValue()))
                .sorted(Comparator.comparing((Failure f)->f.source().kind().name()).thenComparing(f->f.source().name())
                        .thenComparing(f->new TreeMap<>(f.stock()).toString())).toList();
    }
    void release(Object owner) {active.remove(owner);}
    void clear() {active.clear();failures.clear();}
}
