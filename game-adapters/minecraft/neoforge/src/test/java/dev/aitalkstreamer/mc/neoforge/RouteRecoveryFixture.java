package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Fresh route search over a changed corridor; no client, input or world mutation. */
public final class RouteRecoveryFixture {
    private static int checks;
    private static void check(boolean value) { checks++;if(!value)throw new AssertionError("ROUTE_RECOVERY_"+checks); }
    public static void main(String[] args) {
        var blocked=new HashSet<Point>();
        var terrain=new NativeWalkPlanner.Terrain() {
            public boolean stand(Point p) {
                return p.y()==75 && p.x()>=0 && p.x()<=5 && Math.abs(p.z())<=2 && !blocked.contains(p);
            }
            public boolean step(Point from,Point to) { return stand(from) && stand(to); }
        };
        var start=new Point(0,75,0);var goal=new Point(5,75,0);
        var old=NativeWalkPlanner.find(terrain,start,goal,0,1024);
        check(old.reachesGoal());check(old.points().get(1).equals(new Point(1,75,0)));
        blocked.add(new Point(1,75,0));
        check(!terrain.step(start,old.points().get(1)));
        var replacement=NativeWalkPlanner.find(terrain,start,goal,0,1024);
        check(replacement.reachesGoal());check(!replacement.points().contains(new Point(1,75,0)));
        check(replacement.expanded()<=1024);check(terrain.step(start,replacement.points().get(1)));
        for(int i=1;i<replacement.points().size();i++)check(terrain.step(replacement.points().get(i-1),replacement.points().get(i)));
        // A later closure must use a new terrain observation, not the old route/cache.
        Point second=replacement.points().get(1);blocked.add(second);
        var again=NativeWalkPlanner.find(terrain,start,goal,0,1024);
        check(again.reachesGoal());check(!again.points().contains(second));
        for(int z=-2;z<=2;z++)blocked.add(new Point(1,75,z));
        var closed=NativeWalkPlanner.find(terrain,start,goal,0,1024);
        check(!closed.reachesGoal());check(closed.points().stream().allMatch(p->p.x()==0));
        // A bounded search that has not reached this nearby goal grants no route completion.
        blocked.clear();var shortSearch=NativeWalkPlanner.find(terrain,start,goal,0,1);
        check(!shortSearch.reachesGoal());check(shortSearch.expanded()==1);
        var arrived=NativeWalkPlanner.find(terrain,start,start,0,1024);
        check(arrived.reachesGoal() && arrived.points().equals(List.of(start)));
        System.out.println("PASS "+checks+" changed-corridor route checks; no actual movement or survival acceptance");
    }
}
