package dev.aitalkstreamer.mc.survival;

import java.util.*;
import dev.aitalkstreamer.mc.core.InventoryExchange.State;
import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import static dev.aitalkstreamer.mc.core.Json.require;

/** Exact player-handler transfers. No quick-move, dropping, merging, or cursor residue. */
public final class EquipmentPlan {
    public enum Action { PICKUP, SWAP }
    public record Step(State before, State after, int slot, int button, Action action) { }
    private EquipmentPlan() { }
    static void ready(State before) {
        require(before.cursor().equals(Stack.EMPTY) && before.slots().subList(0,5).stream().allMatch(Stack.EMPTY::equals),"GAME_EQUIPMENT_GRID_NOT_EMPTY");
    }
    public static List<Step> main(State before,int source,int hotbar) {
        ready(before);require(source>=9&&source<=44&&hotbar>=36&&hotbar<=44,"GAME_EQUIPMENT_SLOT_INVALID");
        return source==hotbar?List.of():List.of(new Step(before,before.swap(source,hotbar),source,hotbar-36,Action.SWAP));
    }
    public static List<Step> offhand(State before,int source) {
        ready(before);require(source>=9&&source<=44,"GAME_EQUIPMENT_SLOT_INVALID");
        return List.of(new Step(before,before.swap(source,45),source,40,Action.SWAP));
    }
    public static List<Step> armor(State before,int source,int target) {
        ready(before);require(source>=9&&source<=44&&target>=5&&target<=8,"GAME_EQUIPMENT_SLOT_INVALID");
        var value=before.slots().get(source);var old=before.slots().get(target);
        require(value.count()==1&&old.count()<=1&&!value.equals(old),"GAME_EQUIPMENT_ARMOR_INVALID");
        var first=new State(before.slot(source,Stack.EMPTY).slots(),value);
        var second=new State(first.slot(target,value).slots(),old);
        var steps=new ArrayList<Step>();steps.add(new Step(before,first,source,0,Action.PICKUP));steps.add(new Step(first,second,target,0,Action.PICKUP));
        if(!old.equals(Stack.EMPTY))steps.add(new Step(second,new State(second.slot(source,old).slots(),Stack.EMPTY),source,0,Action.PICKUP));
        return List.copyOf(steps);
    }
}
