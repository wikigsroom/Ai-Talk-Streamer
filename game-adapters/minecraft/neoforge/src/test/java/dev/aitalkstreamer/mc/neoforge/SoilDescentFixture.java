package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;
import static dev.aitalkstreamer.mc.neoforge.NativeStepPlan.*;

/** Geometry and receipt boundaries, not a Minecraft excavation acceptance run. */
public final class SoilDescentFixture {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("SOIL_DESCENT_"+checks);}
    private static final Point START=new Point(0,20,0),SOURCE=new Point(3,15,0),NEXT=new Point(1,19,0);
    private static final Map<Point,Cell> cells=new HashMap<>();
    private static final Set<Point> floors=new HashSet<>();
    private static boolean standing=true;
    private static final Terrain terrain=new Terrain(){
        public boolean destination(Point p){return standing && p.equals(START);}
        public boolean support(Point p){return floors.contains(p);}
        public Cell clearance(Point p){return cells.getOrDefault(p,Cell.BLOCKED);}
    };
    private static void reset(){
        cells.clear();floors.clear();standing=true;
        cells.put(new Point(0,21,0),Cell.CLEAR);floors.add(new Point(1,18,0));
        cells.put(new Point(1,21,0),Cell.CLEAR);cells.put(new Point(1,20,0),Cell.CUT);cells.put(NEXT,Cell.CUT);
    }
    private static Step plan(Point source,boolean known){return NativeSoilDescent.choose(terrain,START,source,known);}
    public static void main(String[] args){
        reset();var before=Map.copyOf(cells);var step=plan(SOURCE,true);
        check(step!=null && step.from().equals(START) && step.to().equals(NEXT));
        check(step.cuts().equals(List.of(new Point(1,20,0),NEXT)));
        check(!step.cuts().contains(new Point(0,19,0)) && !step.cuts().contains(new Point(1,18,0)));
        check(cells.equals(before));
        try{step.cuts().clear();throw new AssertionError("MUTABLE_PLAN");}catch(UnsupportedOperationException expected){check(true);}
        check(plan(SOURCE,false)==null);
        for(Point invalid:List.of(new Point(3,20,0),new Point(3,21,0),new Point(3,7,0),
                new Point(13,15,0),new Point(3,15,13),new Point(Integer.MIN_VALUE,15,0)))check(plan(invalid,true)==null);
        standing=false;check(plan(SOURCE,true)==null);reset();
        for(Point blocked:List.of(new Point(0,21,0),new Point(1,21,0),new Point(1,20,0),NEXT)){
            cells.put(blocked,Cell.BLOCKED);check(plan(SOURCE,true)==null);reset();
        }
        cells.put(new Point(0,21,0),Cell.CUT);check(plan(SOURCE,true)==null);reset();
        floors.clear();check(plan(SOURCE,true)==null);reset();
        check(plan(new Point(1,18,0),true)==null); // Do not stand on the intended resource.
        cells.put(new Point(1,21,0),Cell.CUT);check(plan(SOURCE,true).cuts().size()==3);reset();
        cells.put(new Point(1,20,0),Cell.CLEAR);cells.put(NEXT,Cell.CLEAR);
        check(plan(SOURCE,true).cuts().isEmpty());reset();
        for(int x=-12;x<=12;x+=3)for(int z=-12;z<=12;z+=3){
            var source=new Point(x,12,z);var value=plan(source,true);if(value==null)continue;
            check(value.to().y()==START.y()-1 && Math.abs(value.to().x()-START.x())+Math.abs(value.to().z()-START.z())==1);
            check(value.to().distanceSquared(source)<START.distanceSquared(source));
            check(!value.cuts().contains(new Point(0,19,0)) && !value.cuts().contains(new Point(1,18,0)));
        }
        check(NativeSoilDescent.choose(terrain,new Point(0,Integer.MIN_VALUE,0),SOURCE,true)==null);
        var receipt=new NativeStepReceipt(NEXT,()->true,()->100L);
        check(!receipt.confirmed(true));receipt.packet(new Point(2,19,0),true);check(!receipt.confirmed(true));
        receipt.packet(NEXT,true);check(!receipt.confirmed(false));check(receipt.confirmed(true));
        receipt.packet(NEXT,false);check(!receipt.confirmed(true));receipt.close();
        System.out.println("PASS "+checks+" soil descent support/target/clearance/receipt boundaries; no game acceptance");
    }
}
