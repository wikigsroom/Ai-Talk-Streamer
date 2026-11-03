package dev.aitalkstreamer.mc.neoforge;

/** Actual 0.125-block grave footing and refusal boundaries, without game input. */
public final class PartialFootingFixture {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("PARTIAL_FOOTING_"+checks);}
    private static boolean footing(int y,double feet,double height,boolean ground,boolean clear,boolean support,boolean dry){
        return NativePartialFooting.admissible(y,feet,height,ground,clear,support,dry);
    }
    public static void main(String[] args) {
        check(footing(72,72.125,1.8,true,true,true,true));
        check(footing(72,72.5,1.8,true,true,true,true));
        check(footing(-20,-19.875,1.8,true,true,true,true));
        check(!footing(72,72,1.8,true,true,true,true));
        check(!footing(72,72.5001,1.8,true,true,true,true));
        check(!footing(72,Double.NaN,1.8,true,true,true,true));
        check(!footing(72,Double.POSITIVE_INFINITY,1.8,true,true,true,true));
        check(!footing(72,72.125,Double.NaN,true,true,true,true));
        check(!footing(72,72.125,1.5,true,true,true,true));
        check(!footing(72,72.125,2.0,true,true,true,true));
        check(!footing(72,72.125,1.8,false,true,true,true));
        check(!footing(72,72.125,1.8,true,false,true,true));
        check(!footing(72,72.125,1.8,true,true,false,true));
        check(!footing(72,72.125,1.8,true,true,true,false));
        check(!footing(72,71.125,1.8,true,true,true,true));
        check(!footing(72,73.125,1.8,true,true,true,true));
        double path=NativePartialFooting.shallowSurfaceY(74,true,true,0,0,0,1,15.0/16,1);
        check(path==74.9375 && Math.floor(path)==74);
        check(NativePartialFooting.shallowSurfaceY(-20,true,true,0,0,0,1,15.0/16,1)==-19.0625);
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,false,true,0,0,0,1,15.0/16,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,false,0,0,0,1,15.0/16,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,true,.1,0,0,1,15.0/16,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,true,0,.1,0,1,15.0/16,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,true,0,0,.1,1,15.0/16,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,true,0,0,0,.9,15.0/16,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,true,0,0,0,1,.5,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,true,0,0,0,1,1,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,true,0,0,0,1,Double.NaN,1)));
        check(Double.isNaN(NativePartialFooting.shallowSurfaceY(74,true,true,0,0,0,1,15.0/16,.9)));
        // Integer protocol cells remain unchanged; physical arrival uses the received surface.
        check(Math.abs(path-74)>.3 && Math.abs(path-74.9375)<.3);
        var cells=java.util.Map.of(new NativeWalkPlanner.Point(0,75,0),75.0,
                new NativeWalkPlanner.Point(1,74,0),path,new NativeWalkPlanner.Point(2,75,0),75.0);
        var terrain=new NativeWalkPlanner.Terrain(){
            public boolean stand(NativeWalkPlanner.Point p){return cells.containsKey(p);}
            public boolean step(NativeWalkPlanner.Point a,NativeWalkPlanner.Point b){
                return cells.containsKey(a) && cells.containsKey(b) && Math.abs(cells.get(a)-cells.get(b))<=1;
            }
        };
        var route=NativeWalkPlanner.find(terrain,new NativeWalkPlanner.Point(0,75,0),new NativeWalkPlanner.Point(2,75,0),0,64);
        check(route.reachesGoal() && route.points().contains(new NativeWalkPlanner.Point(1,74,0)));
        check(NativeWalkPlanner.reachable(terrain,new NativeWalkPlanner.Point(0,75,0),8,256).contains(new NativeWalkPlanner.Point(2,75,0)));
        check(!footing(74,path,1.8,true,true,true,true)); // Generic partial-origin allowance stays capped at half a block.
        // The currently observed body can rest over an edge at an integer Y.
        // This never admits another cell or a falling, blocked, wet or unsupported body.
        check(NativePartialFooting.supportedIntegerOrigin(75,75,1.8,true,true,true,true));
        check(NativePartialFooting.supportedIntegerOrigin(-20,-20,1.8,true,true,true,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,75,1.8,false,true,true,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,75,1.8,true,false,true,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,75,1.8,true,true,false,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,75,1.8,true,true,true,false));
        check(!NativePartialFooting.supportedIntegerOrigin(75,74.9375,1.8,true,true,true,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,75.125,1.8,true,true,true,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,Double.NaN,1.8,true,true,true,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,75,Double.NaN,true,true,true,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,75,1.5,true,true,true,true));
        check(!NativePartialFooting.supportedIntegerOrigin(75,75,2,true,true,true,true));
        System.out.println("PASS "+checks+" actual partial-footing boundaries; no world writes or input");
    }
}
