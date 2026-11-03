package dev.aitalkstreamer.mc.core;

import java.util.Objects;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

/** Vanilla may continue a held synthetic key after the task tick has returned. */
public final class HeldActionRouter {
    public enum Action { ATTACK, BREAK, USE }
    public interface Boundary {
        boolean owns(Action action);
        void run(Action action, Runnable effect);
    }
    private final Boundary boundary;
    public HeldActionRouter(Boundary boundary) { this.boundary=Objects.requireNonNull(boundary); }
    public <T> T route(Action action, Supplier<T> effect, T rejected) {
        Objects.requireNonNull(action);Objects.requireNonNull(effect);
        if (!boundary.owns(action)) return effect.get();
        AtomicReference<T> result=new AtomicReference<>(rejected);
        boundary.run(action,()->result.set(effect.get()));
        return result.get();
    }
}
