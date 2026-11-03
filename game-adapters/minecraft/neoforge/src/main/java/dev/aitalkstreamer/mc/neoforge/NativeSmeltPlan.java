package dev.aitalkstreamer.mc.neoforge;

import dev.aitalkstreamer.mc.core.InventoryTarget;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Finite conversions with actual fuel durations; raw stock is reserved before any fuel allocation. */
public final class NativeSmeltPlan {
    public static final int MAX_INPUTS=4, MAX_BATCHES=32;
    public static final long MAX_BATCH_MS=63000, MAX_TOTAL_MS=240000;
    public record Stock(int count, boolean raw, int burnTicks) {
        public Stock { require(count>=0 && count<=99 && burnTicks>=0 && burnTicks<=1_000_000,"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED"); }
    }
    public record Batch(int rawSlot,int fuelSlot,int inputs,long budgetMillis) { }
    public record Plan(InventoryTarget target,List<Batch> batches) {
        public Plan { batches=List.copyOf(batches); }
        public int[] requiredFrom(int start) {
            require(start>=0 && start<=batches.size(),"GAME_COOKING_MATERIAL_CHANGED");
            int[] result=new int[36];
            for(int i=start;i<batches.size();i++){var batch=batches.get(i);result[batch.rawSlot]+=batch.inputs;result[batch.fuelSlot]++;}
            return result;
        }
        public long budgetMillis() {return batches.stream().mapToLong(Batch::budgetMillis).sum();}
    }
    private NativeSmeltPlan(){ }
    public static long batchMillis(int ticks,int inputs) {
        require(ticks>0 && ticks<=1200 && inputs>0 && inputs<=MAX_INPUTS,"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
        return ticks*50L*inputs+1500L*(inputs-1)+3000;
    }
    public static Plan allocate(List<Stock> stock,int ticks,int perInput,int outputLimit,String item,int baseline,int requested) {
        stock=List.copyOf(stock);
        require(stock.size()==36 && ticks>0 && ticks<=1200 && perInput>0 && perInput<=outputLimit && outputLimit<=99,
                "GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
        var target=new InventoryTarget(item,baseline,requested,perInput);
        int remaining=target.batches(),rawTotal=stock.stream().filter(Stock::raw).mapToInt(Stock::count).sum();
        require(rawTotal>=remaining,"GAME_RESOURCE_MATERIAL_UNAVAILABLE");
        int[] counts=stock.stream().mapToInt(Stock::count).toArray();var batches=new ArrayList<Batch>();long totalMillis=0;
        while(remaining>0) {
            Batch best=null;boolean bestRawFuel=true;int bestWaste=Integer.MAX_VALUE;
            for(int raw=0;raw<36;raw++)if(stock.get(raw).raw && counts[raw]>0) {
                for(int fuel=0;fuel<36;fuel++)if(counts[fuel]>0 && stock.get(fuel).burnTicks>=ticks) {
                    boolean rawFuel=stock.get(fuel).raw;
                    if(rawFuel && rawTotal<=remaining)continue;
                    int inputs=Math.min(MAX_INPUTS,Math.min(remaining,Math.min(counts[raw]-(raw==fuel?1:0),
                            Math.min(outputLimit/perInput,stock.get(fuel).burnTicks/ticks))));
                    while(inputs>0 && batchMillis(ticks,inputs)>MAX_BATCH_MS)inputs--;
                    if(inputs<=0)continue;
                    int waste=stock.get(fuel).burnTicks-inputs*ticks;
                    if(best==null || inputs>best.inputs || inputs==best.inputs && (bestRawFuel && !rawFuel
                            || bestRawFuel==rawFuel && waste<bestWaste)) {
                        best=new Batch(raw,fuel,inputs,batchMillis(ticks,inputs));bestRawFuel=rawFuel;bestWaste=waste;
                    }
                }
            }
            require(best!=null,"GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE");
            require(batches.size()<MAX_BATCHES && totalMillis+best.budgetMillis<=MAX_TOTAL_MS,"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED");
            counts[best.rawSlot]-=best.inputs;counts[best.fuelSlot]--;
            rawTotal-=best.inputs+(stock.get(best.fuelSlot).raw?1:0);remaining-=best.inputs;
            batches.add(best);totalMillis+=best.budgetMillis;
        }
        return new Plan(target,batches);
    }
}
