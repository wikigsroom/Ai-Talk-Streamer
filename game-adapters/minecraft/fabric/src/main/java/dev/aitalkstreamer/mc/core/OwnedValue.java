package dev.aitalkstreamer.mc.core;

import java.util.function.Consumer;
import java.util.function.Supplier;

/** Client-thread identity ownership for replacing a game's movement input object. */
public final class OwnedValue<T> {
    private final Supplier<T> read;
    private final Consumer<T> write;
    private boolean owned;
    private T original, installed;
    public OwnedValue(Supplier<T> read, Consumer<T> write) { this.read = read; this.write = write; }
    public void replace(T next) {
        T current = read.get();
        if (owned && current != installed) throw new IllegalStateException("GAME_INPUT_OWNER_CHANGED");
        if (!owned) { original = current; owned = true; }
        // Retain ownership even if a setter mutates then throws.
        installed = next; write.accept(next);
    }
    public void release() {
        if (!owned) return;
        if (read.get() == installed) write.accept(original);
        original = null; installed = null; owned = false;
    }
    public boolean owned() { return owned; }
    /** The exact installed object must still occupy its original slot. */
    public boolean owns(T value) { return owned && value == installed && read.get() == installed; }
}
