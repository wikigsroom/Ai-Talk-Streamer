package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.*;

/** Geometry/search regression only; actual collision and pursuit require the game. */
public final class DiagonalRouteFixture {
    private static int checks;
    private static void check(boolean value) { checks++;if(!value)throw new AssertionError("DIAGONAL_ROUTE_"+checks); }
    private static Terrain flat(boolean enabled,Set<Point> blocked,Set<String> edges) {
        return new Terrain() {
            public boolean stand(Point p){return p.y()==0 && !blocked.contains(p);}
            public boolean diagonals(){return enabled;}
            public boolean step(Point a,Point b){return b.y()==0 && !edges.contains(a+":"+b);}
        };
    }
    public static void main(String[] args) {
        Point start=new Point(0,0,0),goal=new Point(8,0,8),one=new Point(1,0,1);
        var blocked=new HashSet<Point>();var edges=new HashSet<String>();
        var terrain=flat(true,blocked,edges);
        var route=find(terrain,start,goal,0,256);
        check(route.reachesGoal() && route.points().size()==9 && route.points().getLast().equals(goal));
        for(int i=1;i<route.points().size();i++) {
            Point a=route.points().get(i-1),b=route.points().get(i);
            check(Math.abs(a.x()-b.x())==1 && Math.abs(a.z()-b.z())==1);
            check(allowedStep(terrain,a,b));
        }
        var cardinal=find(flat(false,Set.of(),Set.of()),start,goal,0,256);
        check(cardinal.reachesGoal() && cardinal.points().size()==17);
        check(!allowedStep(flat(false,Set.of(),Set.of()),start,one));
        for(Point side:List.of(new Point(1,0,0),new Point(0,0,1))) {
            blocked.add(side);check(!allowedStep(terrain,start,one));
            var detour=find(terrain,start,one,0,256);
            check(detour.reachesGoal() && detour.points().size()>2);
            blocked.clear();check(allowedStep(terrain,start,one));
        }
        for(String edge:List.of(start+":"+new Point(1,0,0),start+":"+new Point(0,0,1),
                new Point(1,0,0)+":"+one,new Point(0,0,1)+":"+one,start+":"+one)) {
            edges.add(edge);check(!allowedStep(terrain,start,one));
            edges.clear();check(allowedStep(terrain,start,one));
        }
        check(!allowedStep(terrain,start,new Point(1,1,1)));
        check(!allowedStep(terrain,start,new Point(2,0,1)));
        check(!allowedStep(terrain,new Point(Integer.MIN_VALUE,0,0),new Point(Integer.MAX_VALUE,0,1)));
        Terrain island=new Terrain(){
            public boolean stand(Point p){return p.equals(start)||p.equals(one);}
            public boolean diagonals(){return true;}
            public boolean step(Point a,Point b){return true;}
        };
        check(find(island,start,one,0,16).points().isEmpty());
        check(reachable(island,start,1,16).isEmpty());
        for(int budget:List.of(1,2,4,8)) {
            var partial=find(terrain,start,goal,0,budget);check(partial.expanded()<=budget);
            for(int i=1;i<partial.points().size();i++)check(allowedStep(terrain,partial.points().get(i-1),partial.points().get(i)));
        }
        var list=reachable(terrain,start,1,32);
        check(list.contains(one) && list.size()==8);
        try{route.points().clear();throw new AssertionError("MUTABLE_ROUTE");}catch(UnsupportedOperationException expected){checks++;}
        System.out.println("PASS "+checks+" diagonal support/corner/live-edge/search boundaries; no game input or world writes");
    }
}
