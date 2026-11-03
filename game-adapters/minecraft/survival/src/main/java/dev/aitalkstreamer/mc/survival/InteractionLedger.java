package dev.aitalkstreamer.mc.survival;

import java.util.EnumSet;
import java.util.Objects;
import java.util.function.Supplier;

/** One root's ongoing interactions; a throwing operation may already have started. */
final class InteractionLedger {
    enum Kind { BREAKING, USING }
    private final EnumSet<Kind> issued = EnumSet.noneOf(Kind.class);
    <T> T issue(Kind kind, Supplier<T> action) {
        Objects.requireNonNull(action); issued.add(Objects.requireNonNull(kind));
        return action.get();
    }
    boolean owns(Kind kind) { return issued.contains(kind); }
    void stop(Kind kind, boolean authorized, Runnable action) {
        Objects.requireNonNull(action);
        if (!issued.contains(kind)) return;
        if (authorized) action.run();
        issued.remove(kind);
    }
    void discard() { issued.clear(); }
}
