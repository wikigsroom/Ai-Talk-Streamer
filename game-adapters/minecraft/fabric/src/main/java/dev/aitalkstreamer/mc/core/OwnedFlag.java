package dev.aitalkstreamer.mc.core;

import java.util.Objects;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/** One temporary scalar input change. Returning to the original value ends the claim. */
public final class OwnedFlag {
    private final BooleanSupplier read;
    private final Consumer<Boolean> write;
    private boolean owned, original, installed;
    public OwnedFlag(BooleanSupplier read, Consumer<Boolean> write) {
        this.read = Objects.requireNonNull(read); this.write = Objects.requireNonNull(write);
    }
    public void replace(boolean next) {
        boolean current = read.getAsBoolean();
        if (owned && current != installed) throw new IllegalStateException("GAME_INPUT_FLAG_OWNER_CHANGED");
        if (current == next) return;
        if (!owned) original = current;
        installed = next; owned = true;
        // Field assignment may have happened before a caller reports failure.
        write.accept(next);
        if (next == original) owned = false;
    }
    public void release() { release(() -> original); }
    public void release(BooleanSupplier restore) {
        if (!owned) return;
        if (read.getAsBoolean() == installed) write.accept(restore.getAsBoolean());
        owned = false;
    }
    public boolean owned() { return owned; }
}
