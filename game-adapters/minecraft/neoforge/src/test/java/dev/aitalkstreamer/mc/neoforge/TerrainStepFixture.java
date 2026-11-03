package dev.aitalkstreamer.mc.neoforge;

import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Native admission boundaries, not proof of a placement or a Minecraft playtest. */
public final class TerrainStepFixture {
    private static int checks;
    private static void check(boolean value) { checks++; if(!value)throw new AssertionError("terrain boundary "+checks); }
    public static void main(String[] args) {
        var p=new Point(1359,71,-160);var next=new Point(1360,71,-160);
        check(NativeTerrainStep.admissible(p,next,true,12,6,true));
        check(NativeTerrainStep.admissible(p,new Point(1358,71,-160),true,20,20,true));
        check(NativeTerrainStep.admissible(p,new Point(1359,71,-159),true,18,17,true));
        check(NativeTerrainStep.admissible(p,new Point(1359,71,-161),true,18,17,true));
        check(!NativeTerrainStep.admissible(p,p,true,18,17,true));
        check(!NativeTerrainStep.admissible(p,new Point(1360,72,-160),true,18,17,true));
        check(NativeTerrainStep.admissible(p,new Point(1360,70,-160),true,18,17,true));
        check(!NativeTerrainStep.admissible(p,new Point(1360,69,-160),true,18,17,true));
        check(!NativeTerrainStep.admissible(p,new Point(1359,70,-160),true,18,17,true));
        check(!NativeTerrainStep.admissible(new Point(1,Integer.MIN_VALUE,1),new Point(2,Integer.MAX_VALUE,1),true,18,17,true));
        check(!NativeTerrainStep.admissible(p,new Point(1360,71,-159),true,18,17,true));
        check(!NativeTerrainStep.admissible(p,new Point(1361,71,-160),true,18,17,true));
        check(!NativeTerrainStep.admissible(p,next,false,18,17,true));
        check(!NativeTerrainStep.admissible(p,next,true,11.99,17,true));
        check(!NativeTerrainStep.admissible(p,next,true,Double.NaN,17,true));
        check(!NativeTerrainStep.admissible(p,next,true,18,5,true));
        check(!NativeTerrainStep.admissible(p,next,true,18,21,true));
        check(!NativeTerrainStep.admissible(p,next,true,18,17,false));
        check(!NativeTerrainStep.admissible(null,next,true,18,17,true));
        check(!NativeTerrainStep.admissible(p,null,true,18,17,true));
        check(!NativeTerrainStep.admissible(new Point(Integer.MIN_VALUE,71,-160),new Point(Integer.MAX_VALUE,71,-160),true,18,17,true));
        System.out.println("terrain step boundaries passed: "+checks);
    }
}
