package dev.aitalkstreamer.mc.neoforge;

/** Only the actual grounded origin may use a low partial collision surface. */
public final class NativePartialFooting {
    private NativePartialFooting() { }
    /** A named path/farmland block must expose its exact, full-width 15/16 collision box. */
    public static double shallowSurfaceY(int cellY, boolean knownSurface, boolean singleBox,
            double minX, double minY, double minZ, double maxX, double maxY, double maxZ) {
        return knownSurface && singleBox && minX==0 && minY==0 && minZ==0
                && maxX==1 && maxY==15.0/16 && maxZ==1 ? cellY+maxY : Double.NaN;
    }
    public static boolean admissible(int cellY, double feetY, double bodyHeight,
            boolean grounded, boolean actualBodyClear, boolean supportBelow, boolean loadedDry) {
        double offset=feetY-cellY;
        return Double.isFinite(feetY) && Double.isFinite(bodyHeight)
                && Math.floor(feetY)==cellY && offset>0.000001 && offset<=0.5
                && bodyHeight>=1.7 && bodyHeight<=1.9
                && grounded && actualBodyClear && supportBelow && loadedDry;
    }
}
