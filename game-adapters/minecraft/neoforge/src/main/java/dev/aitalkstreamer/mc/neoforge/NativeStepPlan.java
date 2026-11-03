package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Read-only, single upward stair. No placement, support removal or speculative world writes. */
public final class NativeStepPlan {
    public enum Cell { CLEAR, CUT, BLOCKED }
    public interface Terrain {
        boolean destination(Point point);
        boolean support(Point point);
        Cell clearance(Point point);
    }
    public record Step(Point from, Point to, List<Point> cuts) {
        public Step { cuts = List.copyOf(cuts); }
    }
    private NativeStepPlan() { }
    public static Step choose(Terrain terrain, Point start, Point goal) {
        Objects.requireNonNull(terrain); Objects.requireNonNull(start); Objects.requireNonNull(goal);
        long rise = (long)goal.y() - start.y();
        if (rise < 1 || rise > 8 || Math.abs((long)goal.x()-start.x()) > 24
                || Math.abs((long)goal.z()-start.z()) > 24) return null;
        boolean standingGoal=terrain.destination(goal);
        // A single adjacent rise may itself need excavation. Its two body
        // cells and retained support are inspected now; a distant solid target
        // cannot authorize an imagined tunnel or an unknown future landing.
        boolean excavatingGoal=!standingGoal && rise==1
                && Math.abs((long)goal.x()-start.x())+Math.abs((long)goal.z()-start.z())==1
                && terrain.support(new Point(goal.x(),goal.y()-1,goal.z()));
        if(excavatingGoal) {
            Cell feet=terrain.clearance(goal),head=terrain.clearance(new Point(goal.x(),goal.y()+1,goal.z()));
            excavatingGoal=feet!=Cell.BLOCKED && head!=Cell.BLOCKED && (feet==Cell.CUT || head==Cell.CUT);
        }
        if ((!standingGoal && !excavatingGoal) || terrain.clearance(new Point(start.x(),start.y()+1,start.z())) != Cell.CLEAR) return null;
        Step best = null;
        for (int[] d : new int[][]{{1,0},{-1,0},{0,1},{0,-1}}) {
            Point next = new Point(start.x()+d[0], start.y()+1, start.z()+d[1]);
            if(excavatingGoal && !next.equals(goal))continue;
            if (!terrain.support(new Point(next.x(),start.y(),next.z()))) continue;
            var cuts = new ArrayList<Point>(); boolean blocked = false;
            for (Point cell : List.of(new Point(start.x(),start.y()+2,start.z()),
                    new Point(next.x(),next.y()+1,next.z()), next)) {
                Cell value = terrain.clearance(cell);
                if (value == Cell.BLOCKED) { blocked = true; break; }
                if (value == Cell.CUT) cuts.add(cell);
            }
            // An entity or transient collision cannot authorize digging an otherwise clear passage.
            if (blocked || cuts.isEmpty()) continue;
            var candidate = new Step(start,next,cuts);
            if (best == null || next.distanceSquared(goal) < best.to().distanceSquared(goal)
                    || next.distanceSquared(goal) == best.to().distanceSquared(goal) && cuts.size() < best.cuts().size()) best = candidate;
        }
        return best;
    }
}
