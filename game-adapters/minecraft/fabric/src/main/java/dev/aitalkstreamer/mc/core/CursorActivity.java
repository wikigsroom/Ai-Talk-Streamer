package dev.aitalkstreamer.mc.core;

import java.util.function.LongSupplier;

/** Tracks one window. Only one explicitly requested, short-lived warp is exempt. */
public final class CursorActivity {
    private static final long WARP_TTL_MS = 100;
    private final long window;
    private final LongSupplier clock;
    private boolean known, warp;
    private double x, y, warpX, warpY, travelled;
    private long warpDeadline;
    public CursorActivity(long window, LongSupplier clock) { this.window = window; this.clock = clock; }
    public void expectWarp(long window, double x, double y) {
        if (window != this.window || !Double.isFinite(x) || !Double.isFinite(y)) return;
        warp = true; warpX = x; warpY = y; warpDeadline = clock.getAsLong() + WARP_TTL_MS;
    }
    public boolean moved(long window, double x, double y) {
        if (window != this.window || !Double.isFinite(x) || !Double.isFinite(y)) return false;
        if (warp) {
            boolean expected = clock.getAsLong() <= warpDeadline && Math.abs(x - warpX) <= 0.01 && Math.abs(y - warpY) <= 0.01;
            warp = false;
            if (expected) { known = true; this.x = x; this.y = y; travelled = 0; return false; }
        }
        // The first unexplained event is conservative: there is no trusted baseline.
        if (!known) { known = true; this.x = x; this.y = y; return true; }
        travelled += Math.abs(x - this.x) + Math.abs(y - this.y); this.x = x; this.y = y;
        if (travelled > 0.5) { travelled = 0; return true; }
        return false;
    }
}
