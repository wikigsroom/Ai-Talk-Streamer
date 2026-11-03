package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Replay a closed stone exit, with no world writes or simulated success receipts. */
public final class ExcavationStepFixture {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("EXCAVATION_STEP_"+checks);}
    private static final Point START=new Point(1262,69,-96),GOAL=new Point(1263,70,-96);
    private static final class Terrain implements NativeStepPlan.Terrain {
        boolean floor=true,standable=false;
        final Map<Point,NativeStepPlan.Cell> cells=new HashMap<>();
        Terrain(){cells.put(GOAL,NativeStepPlan.Cell.CUT);cells.put(new Point(1263,71,-96),NativeStepPlan.Cell.CUT);}
        public boolean destination(Point p){return standable&&p.equals(GOAL);}
        public boolean support(Point p){return floor&&p.equals(new Point(1263,69,-96));}
        public NativeStepPlan.Cell clearance(Point p){return cells.getOrDefault(p,NativeStepPlan.Cell.CLEAR);}
    }
    public static void main(String[] args){
        Terrain terrain=new Terrain();var step=NativeStepPlan.choose(terrain,START,GOAL);
        check(step!=null&&step.to().equals(GOAL)&&step.cuts().size()==2);
        check(terrain.cells.size()==2&&!terrain.standable); // A plan never clears the blocks.
        terrain.cells.put(new Point(1262,71,-96),NativeStepPlan.Cell.CUT);
        check(NativeStepPlan.choose(terrain,START,GOAL).cuts().size()==3);
        terrain.floor=false;check(NativeStepPlan.choose(terrain,START,GOAL)==null);terrain.floor=true;
        for(Point blocked:List.of(GOAL,new Point(1263,71,-96),new Point(1262,71,-96),new Point(1262,70,-96))){
            var old=terrain.cells.put(blocked,NativeStepPlan.Cell.BLOCKED);
            check(NativeStepPlan.choose(terrain,START,GOAL)==null);
            if(old==null)terrain.cells.remove(blocked);else terrain.cells.put(blocked,old);
        }
        check(NativeStepPlan.choose(terrain,START,new Point(1264,70,-96))==null);
        check(NativeStepPlan.choose(terrain,START,new Point(1263,71,-96))==null);
        check(NativeStepPlan.choose(terrain,START,new Point(1263,69,-96))==null);
        terrain.cells.clear();check(NativeStepPlan.choose(terrain,START,GOAL)==null); // Entity collision alone cannot authorize a cut.
        terrain.standable=true;check(NativeStepPlan.choose(terrain,START,GOAL)==null);
        terrain.cells.put(new Point(1262,71,-96),NativeStepPlan.Cell.CUT);
        check(NativeStepPlan.choose(terrain,START,GOAL)!=null); // Existing clear destination + low ceiling remains supported.
        System.out.println("PASS "+checks+" excavation admission boundaries; no world writes");
    }
}
