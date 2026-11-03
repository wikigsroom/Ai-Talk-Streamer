package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Original-root calculation jobs; only their bounded result queue enters the client thread. */
public final class SurvivalAsync {
    private static final Map<SurvivalAuthority.Session, State> STATES = new IdentityHashMap<>();
    private record Work(State state,long generation) { }
    private record Result(long generation,Runnable action) { }
    private static final ThreadLocal<Work> WORK = new ThreadLocal<>();
    private static final int JOB_LIMIT = 8, RESULT_LIMIT = 64;
    private static final class State {
        final SurvivalAuthority.Session session;
        final ConcurrentLinkedQueue<Result> results = new ConcurrentLinkedQueue<>();
        final AtomicInteger jobs = new AtomicInteger(), pending = new AtomicInteger();
        final AtomicReference<Throwable> failure = new AtomicReference<>();
        volatile boolean closed;
        volatile long generation;
        State(SurvivalAuthority.Session session) { this.session = session; }
        boolean current() { return !closed && session.current(); }
        boolean current(long expected) {return generation==expected && current();}
        void offer(long expected,Runnable action) {
            // Never hold the result monitor while entering the native arbiter: client
            // cancellation can already hold that arbiter while it closes this queue.
            if (!current(expected)) return;
            synchronized (this) {
                if (closed || generation!=expected) return;
                if (pending.get() >= RESULT_LIMIT) throw new IllegalStateException("GAME_ASYNC_RESULT_LIMIT");
                pending.incrementAndGet(); results.add(new Result(expected,action));
            }
        }
        synchronized void close() { closed = true; results.clear(); pending.set(0); failure.set(null); }
        synchronized void invalidate() {
            if(failure.get()!=null)throw new IllegalStateException("GAME_SURVIVAL_ASYNC_FAILED",failure.get());
            generation=Math.incrementExact(generation);results.clear();pending.set(0);
        }
    }
    private SurvivalAsync() { }
    static boolean inCalculation() { return WORK.get() != null; }
    static void prepare() {
        var session = SurvivalAuthority.session();
        synchronized (STATES) {
            if (STATES.containsKey(session)) return;
            var state = new State(session);
            SurvivalAuthority.owned(() -> {
                state.close(); synchronized (STATES) { STATES.remove(session, state); }
            });
            STATES.put(session, state);
        }
    }
    private static State state(SurvivalAuthority.Session session) { synchronized (STATES) { return STATES.get(session); } }
    static void failed(SurvivalAuthority.Session session, Throwable error) {
        State state = state(session);
        if (state != null && state.current()) { state.failure.compareAndSet(null, error); session.revoke(); }
    }
    static void throwFailure(SurvivalAuthority.Session session) {
        State state = state(session); Throwable error = state == null ? null : state.failure.get();
        if (error != null) throw new IllegalStateException("GAME_SURVIVAL_ASYNC_FAILED", error);
    }
    /** Discard the cancelled branch's calculations without renewing its root, lease or concurrent-job budget. */
    static void invalidate() {
        SurvivalAuthority.requireScope();var session=SurvivalAuthority.session();throwFailure(session);
        State state=state(session);if(state!=null)state.invalidate();
    }
    static boolean quiescent() {
        SurvivalAuthority.requireScope();var session=SurvivalAuthority.session();throwFailure(session);
        State state=state(session);return state==null || state.jobs.get()==0 && state.pending.get()==0;
    }
    private static void failed(State state,long expected,Throwable error) {
        if(!state.current(expected))return;
        synchronized(state) {
            if(state.closed || state.generation!=expected)return;
            state.failure.compareAndSet(null,error);
        }
        state.session.revoke();
    }
    /** Replaces only the reviewed PathingBehavior calculation submission. */
    public static void execute(Executor executor, Runnable calculation) {
        Objects.requireNonNull(executor); Objects.requireNonNull(calculation);
        prepare(); State state = state(SurvivalAuthority.session());
        if (state.jobs.incrementAndGet() > JOB_LIMIT) { state.jobs.decrementAndGet(); throw new IllegalStateException("GAME_ASYNC_JOB_LIMIT"); }
        AtomicBoolean began = new AtomicBoolean();long generation=state.generation;
        try {
            executor.execute(() -> {
                if (!began.compareAndSet(false, true)) return;
                Work previous = WORK.get();
                try {
                    if (!state.current(generation)) return;
                    if (state.session.onOwnerThread() || WORK.get() != null) throw new IllegalStateException("GAME_ASYNC_EXECUTOR_THREAD");
                    WORK.set(new Work(state,generation));
                    SurvivalAuthority.withoutScope(calculation);
                } catch (RuntimeException | Error error) { failed(state,generation,error); }
                finally { if (previous == null) WORK.remove(); else WORK.set(previous); state.jobs.decrementAndGet(); }
            });
        } catch (RuntimeException | Error error) {
            if (began.compareAndSet(false, true)) state.jobs.decrementAndGet();
            throw error;
        }
    }
    /** Called after calculate() by the compiled worker; no game-thread permission exists here. */
    public static void commit(Runnable result) {
        Work work = WORK.get();
        if (work == null) throw new IllegalStateException("GAME_PATH_RESULT_WITHOUT_ORIGIN");
        work.state().offer(work.generation(),Objects.requireNonNull(result));
    }
    public static void drain() {
        var session = SurvivalAuthority.session(); throwFailure(session);
        State state = state(session); if (state == null) return;
        for (int i = 0; i < RESULT_LIMIT && session.current(); i++) {
            Result result;
            synchronized (state) { result = state.results.poll(); if (result != null) state.pending.decrementAndGet(); }
            if (result == null) break;
            if(state.current(result.generation()))result.action().run();throwFailure(session);
        }
    }
}
