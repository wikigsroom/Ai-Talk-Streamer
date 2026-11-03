package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.*;

/** Regression for a four-block roof surrounded by actual stair-shaped eaves. */
public final class DryDescentFixture {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("DRY_DESCENT_"+checks);}
    private static Terrain roof(double health, boolean columnClear) {
        return new Terrain() {
            public boolean stand(Point p){return p.z()==0 && (p.y()==79 && p.x()>=0 && p.x()<=2 || p.y()==75 && p.x()==3);}
            public boolean step(Point a,Point b){return a.y()-b.y()<=2 || NativeDryDescent.admissible(a,b,health,columnClear);}
        };
    }
    public static void main(String[] args) {
        var start=new Point(0,79,0);var edge=new Point(2,79,0);var ground=new Point(3,75,0);
        var route=find(roof(20,true),start,ground,0,256);
        check(route.reachesGoal());check(route.points().equals(List.of(start,new Point(1,79,0),edge,ground)));
        check(reachable(roof(20,true),start,8,256).contains(ground));
        check(!find(roof(11,true),start,ground,0,256).reachesGoal());
        check(!find(roof(20,false),start,ground,0,256).reachesGoal());
        check(NativeDryDescent.admissible(edge,new Point(3,76,0),12,true));
        check(!NativeDryDescent.admissible(edge,new Point(3,74,0),20,true));
        check(!NativeDryDescent.admissible(edge,new Point(4,75,0),20,true));
        check(!NativeDryDescent.admissible(edge,ground,Double.NaN,true));
        check(!NativeDryDescent.admissible(edge,ground,0,true));
        check(!NativeDryDescent.admissible(edge,new Point(3,77,0),20,true));
        var partial=new Point(0,72,0);var lower=new Point(1,70,0);
        check(NativeDryDescent.admissible(partial,lower,12,true,72.125));
        check(!NativeDryDescent.admissible(partial,lower,11,true,72.125));
        check(!NativeDryDescent.admissible(partial,lower,20,false,72.125));
        check(!NativeDryDescent.admissible(partial,new Point(1,68,0),20,true,72.125));
        check(!NativeDryDescent.admissible(partial,lower,20,true,Double.NaN));
        check(!NativeDryDescent.admissible(partial,lower,20,true,71.875));
        check(!NativeDryDescent.admissible(partial,lower,20,true,73.125));
        check(NativeDryDescent.admissible(partial,new Point(1,69,0),20,true,72.5));
        System.out.println("PASS "+checks+" roof-route and dry-descent regression checks; no world writes or input");
    }
}
