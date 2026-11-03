package dev.aitalkstreamer.mc.core;

import java.util.Objects;
import java.util.function.BooleanSupplier;
import java.util.function.IntConsumer;
import java.util.function.IntSupplier;

/** Client-thread hotbar ownership; a failed network restoration remains retryable. */
public final class HotbarSelection {
    private final IntSupplier read;
    private final IntConsumer write, send;
    private final BooleanSupplier context;
    private boolean owned, failed, restoring, pendingLocal;
    private int original, installed, pending;

    public HotbarSelection(IntSupplier read, IntConsumer write, IntConsumer send, BooleanSupplier context) {
        this.read = Objects.requireNonNull(read); this.write = Objects.requireNonNull(write);
        this.send = Objects.requireNonNull(send); this.context = Objects.requireNonNull(context);
    }
    public void select(int slot) {
        if (slot < 0 || slot > 8) throw new IllegalArgumentException("GAME_ITEM_HOTBAR_INVALID");
        if (!context.getAsBoolean()) throw new IllegalStateException("GAME_ITEM_HOTBAR_CONTEXT_CHANGED");
        if (failed || restoring) throw new IllegalStateException("GAME_INPUT_RESTORE_PENDING");
        int current = read.getAsInt();
        if (owned && current != installed) throw new IllegalStateException("GAME_INPUT_OWNER_CHANGED");
        if (!owned) {
            if (current < 0 || current > 8) throw new IllegalStateException("GAME_ITEM_HOTBAR_INVALID");
            original = installed = current; owned = true;
        }
        // Retain both possible local values if a setter fails before or after mutation.
        pending = slot; pendingLocal = true;
        try {
            write.accept(slot); installed = slot; pendingLocal = false;
            send.accept(slot);
        } catch (RuntimeException | Error error) { failed = true; throw error; }
    }
    public void release() {
        if (!owned) return;
        if (!context.getAsBoolean()) { clear(); return; }
        int current = read.getAsInt();
        if (current == installed || pendingLocal && current == pending || restoring && current == original) {
            // If send throws after write succeeds, the next release must resend the
            // original value even though it is already visible in the local field.
            restoring = true;
            write.accept(original);
            send.accept(original);
        }
        // A different local selection belongs to another source and is preserved.
        clear();
    }
    private void clear() {
        owned = failed = restoring = pendingLocal = false;
        original = installed = pending = 0;
    }
    public boolean owned() { return owned; }
}
