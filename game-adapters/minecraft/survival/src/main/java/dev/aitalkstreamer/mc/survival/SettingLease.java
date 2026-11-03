package dev.aitalkstreamer.mc.survival;

import java.util.Objects;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** Immutable setting values; actual post-set values account for native validation/clamping. */
final class SettingLease<T> {
    private final Supplier<T> read;
    private final Consumer<T> write;
    private boolean owned, known;
    private T original, installed;
    SettingLease(Supplier<T> read, Consumer<T> write) { this.read = read; this.write = write; }
    void check() {
        if (owned && (!known || !Objects.equals(read.get(), installed)))
            throw new IllegalStateException(known ? "GAME_OPTION_OWNER_CHANGED" : "GAME_OPTION_RESULT_UNKNOWN");
    }
    void replace(T next) {
        check(); T current = read.get();
        if (Objects.equals(current, next)) return;
        if (!owned) { original = current; owned = true; }
        known = false;
        try { write.accept(next); }
        catch (RuntimeException | Error failure) { observeAfterFailure(failure); throw failure; }
        installed = read.get(); known = true;
    }
    private void observeAfterFailure(Throwable failure) {
        try { installed = read.get(); known = true; }
        catch (RuntimeException | Error observation) { if (observation != failure) failure.addSuppressed(observation); }
    }
    void release() {
        if (!owned) return;
        if (!known) throw new IllegalStateException("GAME_OPTION_RESULT_UNKNOWN");
        T current = read.get();
        // Preserve an intervening manual/foreign change. A completed restore
        // whose callback threw is confirmed by its actual value on retry.
        if (!Objects.equals(current, installed) || Objects.equals(current, original)) { discard(); return; }
        known = false;
        try { write.accept(original); }
        catch (RuntimeException | Error failure) { observeAfterFailure(failure); throw failure; }
        installed = read.get(); known = true;
        if (!Objects.equals(installed, original)) throw new IllegalStateException("GAME_OPTION_RESTORE_UNCONFIRMED");
        discard();
    }
    void discard() { original = null; installed = null; owned = false; known = false; }
}
