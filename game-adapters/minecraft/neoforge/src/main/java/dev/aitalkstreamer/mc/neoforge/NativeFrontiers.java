package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import java.util.function.Predicate;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Select only cells returned by the bounded collision search. No movement is issued here. */
public final class NativeFrontiers {
    private NativeFrontiers() { }
    public static List<Point> select(Point origin, List<Point> reachable, Predicate<Point> dry,
                                     Predicate<Point> stableSupport) {
        var selected = new LinkedHashSet<Point>();
        // Roofs and tree canopies can offer many horizontal cells while hiding
        // the useful way down. Preserve one real, dry descent before directions.
        reachable.stream().filter(p -> p.y() < origin.y() && dry.test(p) && stableSupport.test(p))
                .min(Comparator.comparingInt(Point::y).thenComparingDouble(origin::distanceSquared))
                .ifPresent(selected::add);
        for (int[] direction : new int[][]{{1,0},{-1,0},{0,1},{0,-1},{1,1},{1,-1},{-1,1},{-1,-1}}) {
            if (selected.size() >= 8) break;
            Point best = null; double score = .25;
            for (Point candidate : reachable) {
                if (selected.contains(candidate) || !dry.test(candidate)) continue;
                double value = ((candidate.x()-origin.x())*direction[0]+(candidate.z()-origin.z())*direction[1])
                        / Math.hypot(direction[0],direction[1]) - Math.abs(candidate.y()-origin.y())*.15;
                if (value > score) { score=value; best=candidate; }
            }
            if (best != null) selected.add(best);
        }
        return List.copyOf(selected);
    }
}
