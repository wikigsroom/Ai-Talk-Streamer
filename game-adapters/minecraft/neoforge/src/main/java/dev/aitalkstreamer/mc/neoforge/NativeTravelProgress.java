package dev.aitalkstreamer.mc.neoforge;

import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Progress toward an admitted waypoint; jumping or circling alone cannot renew it. */
public final class NativeTravelProgress {
    public static final double MIN_ADVANCE = .20;
    private Point target;
    private double surfaceY, best = Double.POSITIVE_INFINITY;
    private int advances;

    public void reset() { target = null; best = Double.POSITIVE_INFINITY; advances = 0; }
    public boolean observe(Point next, double floorY, double x, double y, double z) {
        if (next == null || !Double.isFinite(floorY) || !Double.isFinite(x)
                || !Double.isFinite(y) || !Double.isFinite(z)) return false;
        double dx = next.x() + .5 - x, dy = floorY - y, dz = next.z() + .5 - z;
        double remaining = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (!next.equals(target) || floorY != surfaceY) {
            target = next; surfaceY = floorY; best = remaining;
            return false; // Changing a route is not physical progress.
        }
        if (best - remaining < MIN_ADVANCE) return false;
        best = remaining; advances++; return true;
    }
    public Point target() { return target; }
    public double bestDistance() { return best; }
    public int advances() { return advances; }
}
