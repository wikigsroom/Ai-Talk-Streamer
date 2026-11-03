package dev.aitalkstreamer.mc.core;

import java.util.*;
import java.util.function.BiConsumer;
import java.util.function.Predicate;

/** Client-thread ownership only; physical state is sampled again when releasing. */
public final class InputLedger<K> {
    private final Set<K> held = new LinkedHashSet<>();
    private final BiConsumer<K, Boolean> restore;
    private final Predicate<K> physical;
    public InputLedger(BiConsumer<K, Boolean> restore, Predicate<K> physical) { this.restore = restore; this.physical = physical; }
    public void press(K key) { held.add(key); restore.accept(key, true); }
    public boolean owns(K key) { return held.contains(key); }
    /** A pulse may end while other keys remain held; never clear an unowned physical key. */
    public void release(K key) {
        if (!held.contains(key)) return;
        restore.accept(key, physical.test(key)); held.remove(key);
    }
    public void release() {
        Throwable failure = null;
        for (K key : List.copyOf(held)) {
            try { release(key); }
            catch (RuntimeException | Error error) { if (failure == null) failure = error; else failure.addSuppressed(error); }
        }
        if (failure instanceof RuntimeException error) throw error;
        if (failure instanceof Error error) throw error;
    }
    public boolean empty() { return held.isEmpty(); }
}
