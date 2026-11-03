package dev.aitalkstreamer.mc.neoforge;

import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.NAVIGATION_NO_PROGRESS;

/** A predicted hole is insufficient: both a post-send server update and the live world must be clear. */
final class NativeStepReceipt {
    private final Point target;
    private final BooleanSupplier current;
    private final LongSupplier clock;
    private final long sentAt;
    private boolean clear, closed;
    private int packets;
    NativeStepReceipt(Point target, BooleanSupplier current, LongSupplier clock) {
        this.target=target;this.current=current;this.clock=clock;sentAt=clock.getAsLong();
    }
    void packet(Point at, boolean serverClear) {
        if (closed || !current.getAsBoolean() || !target.equals(at)) return;
        packets++;clear=serverClear;
    }
    boolean confirmed(boolean actualClear) {
        if (closed || !current.getAsBoolean() || clock.getAsLong()-sentAt>15000) throw new LocalTaskFailure(NAVIGATION_NO_PROGRESS);
        return packets>0 && clear && actualClear;
    }
    int packets() { return packets; }
    void close() { closed=true;clear=false; }
}
