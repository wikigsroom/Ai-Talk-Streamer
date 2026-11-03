package dev.aitalkstreamer.mc.survival;

import java.util.Objects;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
import java.util.function.Supplier;
import java.util.function.Consumer;

/** One accepted root and its original permit. This is not a sandbox for arbitrary mods. */
public final class SurvivalAuthority {
    public record Context(String task, String controller, String lease, String world, long epoch) {
        public Context {
            for (String value : new String[]{task, controller, lease, world})
                if (value == null || value.isBlank() || value.length() > 160) throw new IllegalArgumentException("Invalid survival context");
            if (epoch < 0) throw new IllegalArgumentException("Invalid survival epoch");
        }
    }
    public interface Boundary {
        boolean current(Context context);
        /** Check current(context) AND stillOpen inside the same native per-write arbiter. */
        void actuate(Context context, BooleanSupplier stillOpen, Runnable boundedWrite);
        /** Cleanup owns its original input generation and is allowed after revocation. */
        default void releaseOwnedInputs(Context context) { }
    }
    public static final class Denied extends IllegalStateException {
        public Denied() { super("GAME_SURVIVAL_SCOPE_REVOKED"); }
    }
    private static final AtomicReference<Session> OWNER = new AtomicReference<>();
    private static final ThreadLocal<Session> SCOPE = new ThreadLocal<>();
    private SurvivalAuthority() { }

    public static final class Session {
        private final Context context;
        private final Boundary boundary;
        private final Thread thread = Thread.currentThread();
        private final AtomicBoolean open = new AtomicBoolean(true);
        private final List<Runnable> subscriptions = new ArrayList<>();
        private Session(Context context, Boundary boundary) { this.context = context; this.boundary = boundary; }
        public Context context() { return context; }
        boolean onOwnerThread() { return thread == Thread.currentThread(); }
        public boolean current() { return open.get() && OWNER.get() == this && boundary.current(context); }
        public void revoke() { open.set(false); }
        /** Cleanup failure retains ownership, preventing a new root until a successful retry. */
        public void close(Runnable stopTree, Runnable releaseOwnedInputs) {
            requireThread(); revoke();
            if (OWNER.get() != this) return;
            Session previous = SCOPE.get();
            if (previous != null && previous != this) throw new Denied();
            SCOPE.set(this);
            Throwable failure = null;
            try {
                try { stopTree.run(); } catch (RuntimeException | Error error) { failure = error; }
                for (Runnable cleanup : List.copyOf(subscriptions)) {
                    try { cleanup.run(); subscriptions.remove(cleanup); }
                    catch (RuntimeException | Error error) { failure = append(failure, error); }
                }
                try { releaseOwnedInputs.run(); } catch (RuntimeException | Error error) {
                    failure = append(failure, error);
                }
                try { boundary.releaseOwnedInputs(context); }
                catch (RuntimeException | Error error) { failure = append(failure, error); }
                if (failure == null) OWNER.compareAndSet(this, null);
            } finally { if (previous == null) SCOPE.remove(); else SCOPE.set(previous); }
            if (failure instanceof RuntimeException error) throw error;
            if (failure instanceof Error error) throw error;
        }
        private void requireThread() { if (Thread.currentThread() != thread) throw new Denied(); }
    }
    public static Session open(Context context, Boundary boundary) {
        // A completion callback can start a new root after run() unwinds, never inside
        // a revoked root's still-present thread scope.
        if (SCOPE.get() != null) throw new Denied();
        Session session = new Session(Objects.requireNonNull(context), Objects.requireNonNull(boundary));
        if (!boundary.current(context) || !OWNER.compareAndSet(null, session)) throw new Denied();
        if (!session.current()) { session.revoke(); OWNER.compareAndSet(session, null); throw new Denied(); }
        return session;
    }
    public static boolean inScope() {
        Session session = SCOPE.get();
        return session != null && session.current() && session.thread == Thread.currentThread();
    }
    public static void requireScope() { if (!inScope()) throw new Denied(); }
    /** State-only cleanup may run in the revoked owner's close; it cannot authorize game effects. */
    public static void requireOwnerScope() {
        Session session = SCOPE.get();
        if (session == null || OWNER.get() != session || session.thread != Thread.currentThread()) throw new Denied();
    }
    static Session session() { requireScope(); return SCOPE.get(); }
    static boolean hasScope() { return SCOPE.get() != null; }
    static void owned(Runnable cleanup) {
        Session session = session();
        if (session.subscriptions.size() >= 1024) throw new IllegalStateException("GAME_TASK_RESOURCE_LIMIT");
        session.subscriptions.add(Objects.requireNonNull(cleanup));
    }
    static void withoutScope(Runnable action) {
        Session previous = SCOPE.get(); SCOPE.remove();
        try { action.run(); }
        finally { if (previous == null) SCOPE.remove(); else SCOPE.set(previous); }
    }
    public static void run(Session session, Runnable action) {
        Objects.requireNonNull(session); session.requireThread();
        Session previous = SCOPE.get();
        if ((previous != null && previous != session) || !session.current()) throw new Denied();
        SCOPE.set(session);
        try { action.run(); } finally { if (previous == null) SCOPE.remove(); else SCOPE.set(previous); }
    }
    /** Delayed work retains its root; it never acquires whichever root is current later. */
    public static Runnable capture(Runnable action) {
        requireScope(); Session original = SCOPE.get(); return () -> run(original, action);
    }
    /** Task-created subscriptions retain their original session and unregister at close. */
    public static <T> Consumer<T> subscriber(Consumer<T> action, Runnable unsubscribe) {
        Objects.requireNonNull(action); Objects.requireNonNull(unsubscribe);
        Session original = SCOPE.get();
        if (original == null && SurvivalAsync.inCalculation()) throw new Denied();
        if (original == null) return event -> {
            // Events can be published from a task tick. An observer registered outside
            // that task must not inherit the publisher's thread-local game permission.
            Session publisher = SCOPE.get();
            SCOPE.remove();
            try { action.accept(event); }
            finally { if (publisher == null) SCOPE.remove(); else SCOPE.set(publisher); }
        };
        requireScope();
        if (original.subscriptions.size() >= 1024) throw new IllegalStateException("GAME_TASK_SUBSCRIPTION_LIMIT");
        original.subscriptions.add(unsubscribe);
        return event -> {
            if (original.thread == Thread.currentThread() && original.current()) run(original, () -> action.accept(event));
        };
    }
    public static void write(Runnable boundedWrite) {
        requireScope(); Session session = SCOPE.get();
        session.boundary.actuate(session.context,
                () -> session.open.get() && OWNER.get() == session && Thread.currentThread() == session.thread, boundedWrite);
    }
    public static <T> T effect(Supplier<T> boundedWrite) {
        AtomicReference<T> result = new AtomicReference<>();
        write(() -> result.set(boundedWrite.get())); return result.get();
    }
    static Boundary boundary() { requireScope(); return SCOPE.get().boundary; }
    private static Throwable append(Throwable previous, Throwable failure) {
        if (previous == null) return failure;
        if (previous != failure) previous.addSuppressed(failure);
        return previous;
    }
    /** Raw commands, idle and Butler cannot create another input writer. */
    public static boolean rawCommandsAllowed() { return false; }
}
