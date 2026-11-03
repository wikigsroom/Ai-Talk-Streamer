package dev.aitalkstreamer.mc.neoforge;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.*;

class NativeWalkPlannerTest {
    private static Terrain flat(Set<Point> blocked) {
        return new Terrain() {
            public boolean stand(Point p) { return p.y() == 0 && !blocked.contains(p); }
            public boolean step(Point from, Point to) { return to.y() == 0; }
        };
    }
    @Test void actualRouteGoesAroundAnObstacleRatherThanCrossingIt() {
        var wall = Set.of(new Point(1, 0, 0), new Point(1, 0, 1), new Point(1, 0, -1));
        var result = find(flat(wall), new Point(0, 0, 0), new Point(3, 0, 0), 0, 256);
        assertTrue(result.reachesGoal()); assertEquals(new Point(3, 0, 0), result.points().getLast());
        assertTrue(result.points().size() > 4); assertTrue(Collections.disjoint(result.points(), wall));
    }
    @Test void unloadedBoundaryDoesNotBecomeAnInventedFullRoute() {
        var known = new Terrain() {
            public boolean stand(Point p) { return p.y() == 0 && p.x() >= 0 && p.x() <= 4 && p.z() == 0; }
            public boolean step(Point a, Point b) { return true; }
        };
        var result = find(known, new Point(0, 0, 0), new Point(10, 0, 0), 0, 64);
        assertFalse(result.reachesGoal()); assertEquals(new Point(4, 0, 0), result.points().getLast());
    }
    @Test void oneBlockRiseAndTwoBlockDescentNeedTheRealTerrainEdgeToPermitThem() {
        var points = Set.of(new Point(1, 1, 0), new Point(2, -1, 0));
        var terrain = new Terrain() {
            public boolean stand(Point p) { return points.contains(p); }
            public boolean step(Point a, Point b) { return a.z() == b.z() && b.x() == a.x() + 1; }
        };
        var result = find(terrain, new Point(0, 0, 0), new Point(2, -1, 0), 0, 32);
        assertTrue(result.reachesGoal()); assertEquals(List.of(new Point(0, 0, 0), new Point(1, 1, 0), new Point(2, -1, 0)), result.points());
    }
    @Test void aStandableCellDoesNotBypassBlockedHeadroomOnItsIncomingEdge() {
        var terrain = new Terrain() {
            public boolean stand(Point p) { return p.equals(new Point(1, 1, 0)); }
            public boolean step(Point a, Point b) { return false; }
        };
        assertTrue(find(terrain, new Point(0, 0, 0), new Point(1, 1, 0), 0, 8).points().isEmpty());
    }
    @Test void searchBudgetReturnsOnlyAProvenPartialPathAndImmutableOutput() {
        var result = find(flat(Set.of()), new Point(0, 0, 0), new Point(100, 0, 0), .5, 3);
        assertFalse(result.reachesGoal()); assertTrue(result.expanded() <= 3);
        assertFalse(result.points().isEmpty()); assertThrows(UnsupportedOperationException.class, () -> result.points().clear());
    }
    @Test void cardinalEdgesNeverCutADiagonalCornerOrJumpOverThreeBlocks() {
        var goal = new Point(1, 3, 1);
        var terrain = new Terrain() {
            public boolean stand(Point p) { return p.equals(goal); }
            public boolean step(Point a, Point b) { return true; }
        };
        assertTrue(find(terrain, new Point(0, 0, 0), goal, 0, 8).points().isEmpty());
    }
    @Test void aGoalAlreadyInsideItsRadiusDoesNotRequireSyntheticMovement() {
        var start = new Point(0, 0, 0);
        var result = find(flat(Set.of()), start, new Point(1, 0, 0), 1, 1);
        assertTrue(result.reachesGoal()); assertEquals(List.of(start), result.points()); assertEquals(0, result.expanded());
    }
    @Test void invalidBudgetOrNonfiniteRadiusNeverStartsSearch() {
        for (double radius : new double[]{Double.NaN, Double.POSITIVE_INFINITY, -1, 9})
            assertThrows(IllegalArgumentException.class, () -> find(flat(Set.of()), new Point(0, 0, 0), new Point(1, 0, 0), radius, 8));
        assertThrows(IllegalArgumentException.class, () -> find(flat(Set.of()), new Point(0, 0, 0), new Point(1, 0, 0), 1, 8193));
    }
}
