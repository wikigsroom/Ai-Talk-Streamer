package dev.aitalkstreamer.mc.neoforge;

/** A water crossing must reach an observed dry bank within the bounded local search. */
public final class NativeWaterRoute {
    public static final int MAX_WATER_TICKS=160;
    private NativeWaterRoute() { }
    public static boolean admissible(NativeWalkPlanner.Point start,NativeWalkPlanner.Point goal,
                                     boolean dryBank,NativeWalkPlanner.Route route) {
        if(!dryBank || start.equals(goal) || Math.abs(goal.x()-start.x())>8 || Math.abs(goal.z()-start.z())>8
                || Math.abs(goal.y()-start.y())>4 || !route.reachesGoal() || route.points().size()>32
                || route.points().size()<2 || !route.points().getFirst().equals(start)
                || !route.points().getLast().equals(goal))return false;
        return route.points().stream().allMatch(p->Math.abs(p.x()-start.x())<=8 && Math.abs(p.z()-start.z())<=8
                && Math.abs(p.y()-start.y())<=4);
    }
}
