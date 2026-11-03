package dev.aitalkstreamer.mc.neoforge;

/** Model a knockback flight, landing, continued flight and fluid entry without a game world. */
public final class EscapeLandingFixture {
    private static int checks;
    private static void check(boolean value) {
        checks++; if (!value) throw new AssertionError("ESCAPE_LANDING_" + checks);
    }
    public static void main(String[] args) {
        for (int tick = 1; tick < 7; tick++)
            check(NativeEscapeLanding.observe(false, false, false, tick) == NativeEscapeLanding.State.WAITING);
        check(NativeEscapeLanding.observe(true, false, false, 7) == NativeEscapeLanding.State.READY);
        check(NativeEscapeLanding.observe(false, false, false, 20) == NativeEscapeLanding.State.WAITING);
        check(NativeEscapeLanding.observe(false, false, false, 21) == NativeEscapeLanding.State.TIMED_OUT);
        // A late landing cannot turn an expired wait into a success.
        check(NativeEscapeLanding.observe(true, false, false, 21) == NativeEscapeLanding.State.TIMED_OUT);
        check(NativeEscapeLanding.observe(true, true, false, 1) == NativeEscapeLanding.State.UNSUPPORTED);
        check(NativeEscapeLanding.observe(false, false, true, 1) == NativeEscapeLanding.State.UNSUPPORTED);
        check(NativeEscapeLanding.observe(true, false, false, -1) == NativeEscapeLanding.State.UNSUPPORTED);
        System.out.println("PASS " + checks + " escape landing observations; no world or input writes");
    }
}
