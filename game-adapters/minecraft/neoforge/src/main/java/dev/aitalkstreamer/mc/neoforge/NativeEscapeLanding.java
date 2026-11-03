package dev.aitalkstreamer.mc.neoforge;

/** Bounded observation of ordinary physics; this policy grants no input or movement. */
final class NativeEscapeLanding {
    static final int MAX_TICKS = 20;
    enum State { WAITING, READY, UNSUPPORTED, TIMED_OUT }

    static State observe(boolean grounded, boolean water, boolean lava, int elapsedTicks) {
        if (water || lava || elapsedTicks < 0) return State.UNSUPPORTED;
        if (elapsedTicks > MAX_TICKS) return State.TIMED_OUT;
        return grounded ? State.READY : State.WAITING;
    }
}
