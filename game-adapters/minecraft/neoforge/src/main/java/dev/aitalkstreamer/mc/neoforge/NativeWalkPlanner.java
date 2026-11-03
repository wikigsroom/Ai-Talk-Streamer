package dev.aitalkstreamer.mc.neoforge;

import java.util.*;

/** Bounded, read-only search. The actual loaded world's collision adapter owns every edge decision. */
public final class NativeWalkPlanner {
    public record Point(int x, int y, int z) {
        public double distanceSquared(Point other) {
            double dx = (double) x - other.x, dy = (double) y - other.y, dz = (double) z - other.z;
            return dx * dx + dy * dy + dz * dz;
        }
    }
    public interface Terrain {
        boolean stand(Point point);
        boolean step(Point from, Point to);
    }
    public record Route(List<Point> points, boolean reachesGoal, int expanded) {
        public Route { points = List.copyOf(points); }
    }
    private record Entry(Point point, double cost, double estimate, long order) { }
    private NativeWalkPlanner() { }
    /** Known reachable cells only; observing this list never grants movement. */
    public static List<Point> reachable(Terrain terrain, Point start, int range, int budget) {
        Objects.requireNonNull(terrain); Objects.requireNonNull(start);
        if (range < 1 || range > 16 || budget < 1 || budget > 4096)
            throw new IllegalArgumentException("GAME_PATH_SEARCH_LIMIT");
        var queue = new ArrayDeque<Point>(); var seen = new LinkedHashSet<Point>();
        queue.add(start); seen.add(start); int expanded = 0;
        while (!queue.isEmpty() && expanded++ < budget) {
            Point at = queue.remove();
            for (int[] direction : new int[][]{{1,0},{-1,0},{0,1},{0,-1}})
                for (int rise : new int[]{0,1,-1,-2,-3,-4}) {
                    Point next = new Point(at.x + direction[0], at.y + rise, at.z + direction[1]);
                    if (Math.abs((long)next.x - start.x) > range || Math.abs((long)next.z - start.z) > range
                            || Math.abs((long)next.y - start.y) > 4 || seen.contains(next)) continue;
                    if (!terrain.stand(next) || !terrain.step(at,next)) continue;
                    seen.add(next); queue.add(next);
                }
        }
        seen.remove(start); return List.copyOf(seen);
    }
    public static Route find(Terrain terrain, Point start, Point goal, double radius, int budget) {
        Objects.requireNonNull(terrain); Objects.requireNonNull(start); Objects.requireNonNull(goal);
        if (!Double.isFinite(radius) || radius < 0 || radius > 8 || budget < 1 || budget > 8192)
            throw new IllegalArgumentException("GAME_PATH_SEARCH_LIMIT");
        if (start.distanceSquared(goal) <= radius * radius) return new Route(List.of(start), true, 0);
        var open = new PriorityQueue<Entry>(Comparator.comparingDouble(Entry::estimate).thenComparingLong(Entry::order));
        var costs = new HashMap<Point, Double>(); var parents = new HashMap<Point, Point>();
        var closed = new HashSet<Point>(); long order = 0;
        costs.put(start, 0.0); open.add(new Entry(start, 0, Math.sqrt(start.distanceSquared(goal)), order++));
        Point closest = start; double nearest = Math.sqrt(start.distanceSquared(goal)); int expanded = 0;
        int[][] directions = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
        while (!open.isEmpty() && expanded < budget) {
            Entry entry = open.remove(); Point at = entry.point;
            if (entry.cost > costs.getOrDefault(at, Double.POSITIVE_INFINITY) || !closed.add(at)) continue;
            expanded++;
            double distance = Math.sqrt(at.distanceSquared(goal));
            if (distance < nearest) { nearest = distance; closest = at; }
            if (distance <= radius) return route(at, parents, true, expanded);
            for (int[] direction : directions) for (int rise : new int[]{0, 1, -1, -2, -3, -4}) {
                Point next = new Point(at.x + direction[0], at.y + rise, at.z + direction[1]);
                // Replan another segment as the real player loads more terrain; never invent distant chunks.
                if (Math.abs((long) next.x - start.x) > 24 || Math.abs((long) next.z - start.z) > 24
                        || Math.abs((long) next.y - start.y) > 12 || closed.contains(next)) continue;
                if (!terrain.stand(next) || !terrain.step(at, next)) continue;
                double cost = entry.cost + 1 + Math.abs(rise) * .35;
                if (cost >= costs.getOrDefault(next, Double.POSITIVE_INFINITY)) continue;
                costs.put(next, cost); parents.put(next, at);
                open.add(new Entry(next, cost, cost + Math.sqrt(next.distanceSquared(goal)), order++));
            }
        }
        // A partial route is useful only when its endpoint actually approaches this goal.
        return closest.equals(start) ? new Route(List.of(), false, expanded) : route(closest, parents, false, expanded);
    }
    private static Route route(Point end, Map<Point, Point> parents, boolean complete, int expanded) {
        var result = new ArrayList<Point>();
        for (Point at = end; at != null; at = parents.get(at)) result.add(at);
        Collections.reverse(result); return new Route(result, complete, expanded);
    }
}
