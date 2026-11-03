package dev.aitalkstreamer.mc.survival;

import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Only the amount committed by this original task, independent of pre-existing container contents. */
final class StorageLedger<K> {
    private final Map<K,Integer> confirmed=new HashMap<>();
    int need(Collection<K> matches,int target) {
        require(matches!=null && !matches.isEmpty() && matches.size()<=256 && matches.stream().allMatch(Objects::nonNull)
                && target>=0 && target<=4096,"GAME_STORAGE_TARGET_INVALID");
        var unique=new HashSet<>(matches);int have=0;
        for(K item:unique)have=Math.addExact(have,confirmed.getOrDefault(item,0));
        return Math.max(0,target-have);
    }
    void credit(K item,int count) {
        require(item!=null && count>0 && count<=99 && (confirmed.containsKey(item)||confirmed.size()<256),"GAME_STORAGE_STATE_INVALID");
        int next=Math.addExact(confirmed.getOrDefault(item,0),count);
        require(next<=262144,"GAME_STORAGE_STATE_INVALID");confirmed.put(item,next);
    }
}
