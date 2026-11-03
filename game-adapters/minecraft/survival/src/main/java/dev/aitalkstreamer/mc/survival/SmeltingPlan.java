package dev.aitalkstreamer.mc.survival;

import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Pure absolute-output goals and finite per-conversion budgets; the game supplies actual recipes. */
final class SmeltingPlan {
    static final int MAX_INPUTS=4;
    static final long MAX_BATCH_MS=63000;
    record Goal(Set<String> outputs,Set<String> materials,int total) {
        Goal {
            require(outputs!=null && materials!=null && !outputs.isEmpty() && !materials.isEmpty()
                    && outputs.size()<=256 && materials.size()<=256 && total>=0 && total<=4096
                    && outputs.stream().allMatch(s->s!=null && !s.isBlank()) && materials.stream().allMatch(s->s!=null && !s.isBlank()),"GAME_RESOURCE_CRAFT_TARGET_INVALID");
            outputs=Set.copyOf(outputs);materials=Set.copyOf(materials);
        }
    }
    static int missing(Goal goal,List<ResourceMaterialsPlan.Stock> stock) {
        long have=0;for(var value:stock) if(goal.outputs().contains(value.item())) have+=value.count();
        return (int)Math.max(0,goal.total()-have);
    }
    static MaterialTargets desired(List<Goal> goals) {
        require(goals!=null && !goals.isEmpty() && goals.size()<=64,"GAME_RESOURCE_CRAFT_TARGET_INVALID");
        var result=new LinkedHashMap<Set<String>,Integer>();for(var goal:goals) result.merge(goal.outputs(),goal.total(),Math::max);
        return new MaterialTargets(result);
    }
    static long cookMillis(int ticks,int maximum) {
        require(ticks>0 && ticks<=maximum && maximum<=1200,"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
        return Math.addExact(Math.multiplyExact((long)ticks,50),3000);
    }
    static long batchMillis(int ticks,int inputs,int maximum) {
        require(inputs>0 && inputs<=MAX_INPUTS,"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
        long duration=cookMillis(ticks,maximum)+(inputs-1)*(ticks*50L+CookingExchange.CLICK_MS);
        require(duration<=MAX_BATCH_MS,"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");return duration;
    }
    static int batchLimit(int rawCount,int missing,int outputPerInput,int outputLimit,int burnTicks,int ticks,int maximum,int inputLimit) {
        cookMillis(ticks,maximum);
        require(rawCount>=0 && rawCount<=99 && missing>=0 && missing<=4096 && outputPerInput>0 && outputPerInput<=outputLimit
                && outputLimit<=99 && burnTicks>=0 && inputLimit>0 && inputLimit<=MAX_INPUTS,"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
        int result=Math.min(inputLimit,Math.min(rawCount,Math.min((missing+outputPerInput-1)/outputPerInput,Math.min(outputLimit/outputPerInput,burnTicks/ticks))));
        while(result>0 && cookMillis(ticks,maximum)+(result-1)*(ticks*50L+CookingExchange.CLICK_MS)>MAX_BATCH_MS)result--;
        return result;
    }
    static boolean fuel(int burnTicks,int cookTicks,boolean remainder,boolean ordinary,boolean protectedItem) {
        return burnTicks>=cookTicks && cookTicks>0 && !remainder && ordinary && !protectedItem;
    }
    static int fuelUnits(boolean rawIsFuel) {return rawIsFuel?2:1;}
    static boolean available(Map<Integer,Integer> free,int raw,int fuel) {
        return free.getOrDefault(raw,0)>=(raw==fuel?2:1) && free.getOrDefault(fuel,0)>0;
    }
}
