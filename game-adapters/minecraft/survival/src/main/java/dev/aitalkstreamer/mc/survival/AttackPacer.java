package dev.aitalkstreamer.mc.survival;

import java.util.Objects;

/** Player-age tick, not target count: one attempted attack even when an upstream strategy loops. */
final class AttackPacer {
    private boolean issued;
    private int lastTick;
    boolean ready(int tick, float cooldown) {
        return Float.isFinite(cooldown) && cooldown >= 1 && (!issued || tick != lastTick);
    }
    boolean issue(int tick, float cooldown, Runnable effect) {
        Objects.requireNonNull(effect);
        if (!ready(tick, cooldown)) return false;
        issued = true; lastTick = tick;
        effect.run(); return true;
    }
}
