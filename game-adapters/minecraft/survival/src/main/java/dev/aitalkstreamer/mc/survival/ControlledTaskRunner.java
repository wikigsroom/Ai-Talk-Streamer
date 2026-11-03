package dev.aitalkstreamer.mc.survival;

import java.util.List;
import java.util.Objects;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** Root lifecycle used by the real AltoClef driver; completion requests effect verification. */
public final class ControlledTaskRunner<T> {
    public interface Runtime<T> {
        void start(T task, Runnable finished);
        void tick();
        void stop();
        List<Runnable> cleanup();
        default void beforeComplete() { }
    }
    private final Runtime<T> runtime;
    private SurvivalAuthority.Session active;
    private Consumer<String> completed;
    private boolean signalled, closing;
    public ControlledTaskRunner(Runtime<T> runtime) { this.runtime = Objects.requireNonNull(runtime); }
    public boolean active() { return active != null; }
    public void start(SurvivalAuthority.Context context, SurvivalAuthority.Boundary boundary,
                      Supplier<T> prepare, Consumer<String> completed) {
        if (active != null || closing) throw new IllegalStateException("GAME_TASK_BUSY");
        Objects.requireNonNull(prepare); Objects.requireNonNull(completed);
        active = SurvivalAuthority.open(context, boundary); this.completed = completed; signalled = false;
        var original = active;
        try {
            SurvivalAuthority.run(original, () -> runtime.start(Objects.requireNonNull(prepare.get()), () -> {
                if (active == original && original.current() && SurvivalAuthority.inScope()) signalled = true;
            }));
        } catch (RuntimeException | Error error) {
            try { if (active == original) cancel(); } catch (RuntimeException | Error cleanup) { if (cleanup != error) error.addSuppressed(cleanup); }
            throw error;
        }
    }
    /** Immediate vanilla callbacks use the live original root, never a fresh control grant. */
    public void effect(Runnable effect) {
        Objects.requireNonNull(effect);var original=active;
        if (original == null || closing || signalled) throw new SurvivalAuthority.Denied();
        SurvivalAuthority.run(original,()->{
            if (active != original || closing || signalled) throw new SurvivalAuthority.Denied();
            SurvivalAuthority.write(effect);
        });
    }
    public void tick() {
        if (active == null || closing) return;
        var original = active;
        try {
            SurvivalAsync.throwFailure(original);
            if (!original.current()) { cancel(); return; }
            SurvivalAuthority.run(original, () -> { SurvivalAsync.drain(); runtime.tick();
                if (active == original && signalled) runtime.beforeComplete(); });
            if (active == original && signalled) {
                Consumer<String> callback = completed;
                cancel(); callback.accept("EXECUTION_FINISHED_REQUIRES_EFFECT_VERIFICATION");
            }
        } catch (RuntimeException | Error error) {
            try { if (active == original) cancel(); } catch (RuntimeException | Error cleanup) { if (cleanup != error) error.addSuppressed(cleanup); }
            throw error;
        }
    }
    public void cancel() {
        var original = active;
        if (original == null || closing) return;
        closing = true;
        try {
            original.close(runtime::stop, () -> runAll(runtime.cleanup()));
            active = null; completed = null; signalled = false;
        } finally { closing = false; }
    }
    private static void runAll(List<Runnable> actions) {
        Throwable failure = null;
        for (Runnable action : actions) {
            try { action.run(); }
            catch (RuntimeException | Error error) {
                if (failure == null) failure = error; else if (failure != error) failure.addSuppressed(error);
            }
        }
        if (failure instanceof RuntimeException error) throw error;
        if (failure instanceof Error error) throw error;
    }
}
