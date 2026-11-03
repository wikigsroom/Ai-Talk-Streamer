package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.function.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Root-local finite observers consume confirmed transfer facts, never locally predicted slot events. */
final class StorageObservers<K,P> {
    private record Watch<K,P>(Predicate<P> accepts,BiConsumer<K,Integer> receive) { }
    private final Map<Object,Watch<K,P>> values=new IdentityHashMap<>();
    void watch(Object owner,Predicate<P> accepts,BiConsumer<K,Integer> receive) {
        require(owner!=null && accepts!=null && receive!=null && (values.containsKey(owner)||values.size()<64),"GAME_STORAGE_TARGET_INVALID");
        values.put(owner,new Watch<>(accepts,receive));
    }
    void unwatch(Object owner){values.remove(owner);}
    void confirmed(P position,K item,int count) {
        require(position!=null && item!=null && count>0 && count<=99,"GAME_STORAGE_STATE_INVALID");
        for(var entry:List.copyOf(values.entrySet())) {
            var value=entry.getValue();if(values.get(entry.getKey())==value && value.accepts().test(position))value.receive().accept(item,count);
        }
    }
    void clear(){values.clear();}
}
