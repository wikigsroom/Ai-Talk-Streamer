package dev.aitalkstreamer.mc.neoforge;

import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Ordinary gravity over a checked dry landing column, never a position/velocity write. */
public final class NativeDryDescent {
    private NativeDryDescent() { }
    public static boolean admissible(Point from, Point to, double health, boolean clearDryColumn) {
        return admissible(from,to,health,clearDryColumn,from.y());
    }
    public static boolean admissible(Point from, Point to, double health, boolean clearDryColumn, double actualFeetY) {
        double drop=actualFeetY-to.y();
        long horizontal=Math.abs((long)from.x()-to.x())+Math.abs((long)from.z()-to.z());
        return clearDryColumn && horizontal==1 && Double.isFinite(actualFeetY)
                && actualFeetY>=from.y() && actualFeetY<from.y()+1.0 && drop>2 && drop<=4
                && Double.isFinite(health) && health>=12;
    }
}
