package dev.aitalkstreamer.mc.neoforge;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.neoforge.NativeStepPlan.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

class NativeStepPlanTest {
    private final Point start = new Point(0,10,0), goal = new Point(4,14,0);
    private final Map<Point,Cell> cells = new HashMap<>();
    private final Set<Point> floors = new HashSet<>();
    private boolean destinationSafe=true;
    private final Terrain terrain = new Terrain() {
        public boolean destination(Point p) { return destinationSafe; }
        public boolean support(Point p) { return floors.contains(p); }
        public Cell clearance(Point p) { return cells.getOrDefault(p,Cell.CLEAR); }
    };
    private void east() { floors.add(new Point(1,10,0)); cells.put(new Point(1,11,0),Cell.CUT); }
    @Test void singleStairKeepsBothSupports() { east(); var step=choose(terrain,start,goal); assertEquals(new Point(1,11,0),step.to()); assertFalse(step.cuts().contains(new Point(1,10,0))); assertFalse(step.cuts().contains(new Point(0,9,0))); }
    @Test void overheadSweepIsClearedBeforeTheLanding() { east(); cells.put(new Point(0,12,0),Cell.CUT);cells.put(new Point(1,12,0),Cell.CUT);assertEquals(List.of(new Point(0,12,0),new Point(1,12,0),new Point(1,11,0)),choose(terrain,start,goal).cuts()); }
    @Test void missingSupportRefuses() { cells.put(new Point(1,11,0),Cell.CUT);assertNull(choose(terrain,start,goal)); }
    @Test void anUnstandableDestinationCannotAuthorizePartialExcavation() { east();destinationSafe=false;assertNull(choose(terrain,start,goal)); }
    @Test void unsafeCurrentHeadRefuses() { east();cells.put(new Point(0,11,0),Cell.BLOCKED);assertNull(choose(terrain,start,goal)); }
    @Test void currentHeadCannotBeMined() { east();cells.put(new Point(0,11,0),Cell.CUT);assertNull(choose(terrain,start,goal)); }
    @Test void blockedUpperSweepRefuses() { east();cells.put(new Point(0,12,0),Cell.BLOCKED);assertNull(choose(terrain,start,goal)); }
    @Test void blockedLandingHeadRefuses() { east();cells.put(new Point(1,12,0),Cell.BLOCKED);assertNull(choose(terrain,start,goal)); }
    @Test void blockedLandingBodyRefuses() { east();cells.put(new Point(1,11,0),Cell.BLOCKED);assertNull(choose(terrain,start,goal)); }
    @Test void clearCorridorDoesNotAuthorizeMining() { floors.add(new Point(1,10,0));assertNull(choose(terrain,start,goal)); }
    @Test void nearerUpwardDirectionWins() { east();floors.add(new Point(-1,10,0));cells.put(new Point(-1,11,0),Cell.CUT);assertEquals(1,choose(terrain,start,goal).to().x()); }
    @Test void fewerCutsBreakEqualDistanceTie() { east();cells.put(new Point(1,12,0),Cell.CUT);floors.add(new Point(-1,10,0));cells.put(new Point(-1,11,0),Cell.CUT);assertEquals(-1,choose(terrain,start,new Point(0,14,0)).to().x()); }
    @Test void deterministicDirectionBreaksEqualCostTie() { east();floors.add(new Point(-1,10,0));cells.put(new Point(-1,11,0),Cell.CUT);assertEquals(1,choose(terrain,start,new Point(0,14,0)).to().x()); }
    @Test void levelGoalCannotAuthorizeMining() { east();assertNull(choose(terrain,start,new Point(4,10,0))); }
    @Test void lowerGoalCannotAuthorizeMining() { east();assertNull(choose(terrain,start,new Point(4,9,0))); }
    @Test void excessiveRiseRefuses() { east();assertNull(choose(terrain,start,new Point(4,19,0))); }
    @Test void excessiveHorizontalDistanceRefuses() { east();assertNull(choose(terrain,start,new Point(25,14,0))); }
    @Test void boundaryDistanceAndRiseAreAllowed() { east();assertNotNull(choose(terrain,start,new Point(24,18,24))); }
    @Test void arithmeticDoesNotOverflowForDistantGoals() { east();assertNull(choose(terrain,start,new Point(Integer.MIN_VALUE,14,0))); }
    @Test void planIsImmutableAndReadOnly() { east();var before=Map.copyOf(cells);var step=choose(terrain,start,goal);assertThrows(UnsupportedOperationException.class,()->step.cuts().clear());assertEquals(before,cells); }
    @Test void unsupportedDirectionsAreSkipped() { east();cells.put(new Point(1,11,0),Cell.BLOCKED);floors.add(new Point(0,10,-1));cells.put(new Point(0,11,-1),Cell.CUT);assertEquals(new Point(0,11,-1),choose(terrain,start,goal).to()); }
}
