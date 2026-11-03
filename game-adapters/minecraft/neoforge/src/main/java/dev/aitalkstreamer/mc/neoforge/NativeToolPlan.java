package dev.aitalkstreamer.mc.neoforge;

import java.util.List;
import static dev.aitalkstreamer.mc.core.Json.require;

/** Chooses among actual stack capabilities; it never guesses a tier from an item name. */
final class NativeToolPlan {
    record Candidate(boolean harvests, float speed, int durability) { }
    private NativeToolPlan() { }
    static int choose(List<Candidate> stock, int selected) {
        require((stock.size()==36 || stock.size()==37) && selected>=0 && selected<9,"GAME_GATHER_TOOL_STATE_INVALID");
        int best=-1;
        for(int slot=0;slot<stock.size();slot++) {
            var candidate=stock.get(slot);
            if(candidate==null || !candidate.harvests() || !Float.isFinite(candidate.speed()) || candidate.speed()<=0
                    || candidate.durability()!=-1 && candidate.durability()<2) continue;
            if(best<0 || better(candidate,slot,stock.get(best),best,selected)) best=slot;
        }
        return best;
    }
    private static int rank(int slot,int selected){return slot==selected?0:slot<9?1:2;}
    private static boolean better(Candidate a,int aSlot,Candidate b,int bSlot,int selected){
        int speed=Float.compare(a.speed(),b.speed());if(speed!=0)return speed>0;
        int rank=Integer.compare(rank(aSlot,selected),rank(bSlot,selected));if(rank!=0)return rank<0;
        int lifeA=a.durability()==-1?Integer.MAX_VALUE:a.durability(),lifeB=b.durability()==-1?Integer.MAX_VALUE:b.durability();
        return lifeA!=lifeB?lifeA>lifeB:aSlot<bSlot;
    }
}
