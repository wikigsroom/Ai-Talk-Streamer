package dev.aitalkstreamer.mc.neoforge;

import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Adjacent dirt support at feet level or one below, never under the player or airborne. */
public final class NativeTerrainStep {
    private NativeTerrainStep() { }
    public static boolean admissible(Point feet, Point at, boolean grounded, double health, int food, boolean dry) {
        return feet != null && at != null && grounded && dry && Double.isFinite(health) && health >= 12
                && food >= 6 && food <= 20 && ((long)feet.y()-at.y()==0 || (long)feet.y()-at.y()==1)
                && Math.abs((long)at.x()-feet.x()) + Math.abs((long)at.z()-feet.z()) == 1;
    }
}
