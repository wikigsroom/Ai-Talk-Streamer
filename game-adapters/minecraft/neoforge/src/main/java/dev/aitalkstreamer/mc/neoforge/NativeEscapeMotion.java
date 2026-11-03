package dev.aitalkstreamer.mc.neoforge;

/** Ordinary escape input eligibility only; this grants no terrain or control permission. */
final class NativeEscapeMotion {
    static float throttle(boolean threatened, boolean finalPoint, double distanceSquared) {
        if (threatened && distanceSquared >= 1) return 1;
        return finalPoint ? (distanceSquared < .36 ? .2f : .5f) : 1;
    }
    static boolean sprint(boolean threatened, boolean grounded, boolean wet, boolean lava,
                          boolean usingItem, boolean collided, int food, float forward,
                          float headingError, double rise) {
        return threatened && grounded && !wet && !lava && !usingItem && !collided && food > 6
                && Float.isFinite(forward) && forward >= .8f && Float.isFinite(headingError)
                && Math.abs(headingError) <= 25 && Double.isFinite(rise) && Math.abs(rise) <= .125;
    }
}
