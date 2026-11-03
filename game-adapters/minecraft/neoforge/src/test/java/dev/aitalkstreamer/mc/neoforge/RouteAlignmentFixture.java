package dev.aitalkstreamer.mc.neoforge;

import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Replay the received off-centre stair origin; no synthetic position or world writes. */
public final class RouteAlignmentFixture {
    private static int checks;
    private static void check(boolean ok){checks++;if(!ok)throw new AssertionError("ALIGNMENT_"+checks);}
    public static void main(String[] args){
        Point p=new Point(1263,70,-98);double x=1263.2908256572687,z=-97.50305386515069;
        // The old 0.316 waypoint radius accepted a body still crossing the previous cell.
        double remaining=Math.pow(p.x()+.5-x,2)+Math.pow(p.z()+.5-z,2);
        check(remaining<.10 && x-.3<p.x() && !NativeRouteAlignment.centered(p,x,z));
        check(NativeRouteAlignment.centered(p,1263.5,-97.5));
        var a=new NativeRouteAlignment();check(!a.begin(p,x,z,false));
        check(!a.begin(p,Double.NaN,z,true));check(!a.begin(p,x,Double.POSITIVE_INFINITY,true));
        check(a.begin(p,x,z,true));check(a.observe(p,x,z,true)==NativeRouteAlignment.State.MOVING);
        check(a.observe(p,1263.5,-97.5,true)==NativeRouteAlignment.State.ALIGNED);
        check(!a.active() && a.totalTicks()==1 && a.episodes()==1);
        check(a.begin(p,x,z,true));check(a.observe(p,x,z,false)==NativeRouteAlignment.State.BLOCKED);
        check(!a.begin(p,x,z,true)); // Same stance cannot reset its two-episode budget.
        a.reset();check(a.begin(p,x,z,true));
        check(a.observe(new Point(1264,70,-98),x,z,true)==NativeRouteAlignment.State.BLOCKED);
        a.reset();check(a.begin(p,x,z,true));
        for(int i=0;i<40;i++)check(a.observe(p,x,z,true)==NativeRouteAlignment.State.MOVING);
        check(a.observe(p,x,z,true)==NativeRouteAlignment.State.TIMED_OUT && a.totalTicks()==40);
        for(int n=1;n<=2;n++){
            Point other=new Point(p.x()+n,p.y(),p.z());check(a.begin(other,other.x()+.2,z,true));
            for(int i=0;i<40;i++)check(a.observe(other,other.x()+.2,z,true)==NativeRouteAlignment.State.MOVING);
            check(a.observe(other,other.x()+.2,z,true)==NativeRouteAlignment.State.TIMED_OUT);
        }
        check(a.totalTicks()==120 && !a.begin(new Point(1270,70,-98),1270.2,z,true));
        a.reset();
        for(int n=0;n<6;n++){
            Point other=new Point(p.x()+n,p.y(),p.z());check(a.begin(other,other.x()+.2,z,true));
            check(a.observe(other,other.x()+.5,z,true)==NativeRouteAlignment.State.ALIGNED);
        }
        check(!a.begin(new Point(1270,70,-98),1270.2,z,true));
        System.out.println("PASS "+checks+" alignment boundaries; ordinary-input budget only, no terrain authority or world writes");
    }
}
