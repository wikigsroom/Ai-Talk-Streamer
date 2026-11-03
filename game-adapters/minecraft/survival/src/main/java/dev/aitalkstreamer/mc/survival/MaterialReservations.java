package dev.aitalkstreamer.mc.survival;

import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Active ancestor targets in one root; stop removes a frame, never the root's selection budget. */
final class MaterialReservations {
    static final int MAX_FRAMES=64,MAX_OUTPUTS=4096,MAX_SELECTIONS=256;
    private final Map<Object,MaterialTargets> frames=new IdentityHashMap<>();
    private int selections;
    void enter(Object task,Map<String,Integer> targets) {
        enter(task,MaterialTargets.from(targets));
    }
    void enter(Object task,MaterialTargets targets) {
        require(task!=null && targets!=null && !targets.goals().isEmpty() && targets.goals().size()<=64,"GAME_MATERIAL_RESERVATION_INVALID");
        require(frames.containsKey(task) || frames.size()<MAX_FRAMES,"GAME_MATERIAL_RESERVATION_LIMIT");
        var old=frames.get(task);require(old==null || old.equals(targets),"GAME_MATERIAL_RESERVATION_CHANGED");
        desired().merge(targets);frames.put(task,targets);
    }
    void leave(Object task) {frames.remove(task);}
    MaterialTargets desired() {
        var merged=MaterialTargets.from(Map.of());for(var target:frames.values())merged=merged.merge(target);return merged;
    }
    void select() {require(selections<MAX_SELECTIONS,"GAME_RESOURCE_MATERIAL_SELECTION_LIMIT");selections++;}
    int selections() {return selections;}
    void clear() {frames.clear();}
}
