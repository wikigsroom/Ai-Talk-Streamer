package dev.aitalkstreamer.mc.survival;

import baritone.api.event.listener.IGameEventListener;
import java.lang.reflect.*;
import java.util.*;

/** Explicit per-start event ownership; input objects retain their immutable constructor binding. */
public final class SurvivalCallbacks {
    public interface RootResettable { void atsClearRootEvents(); }
    private static final Map<Object, Binding> EVENTS = new IdentityHashMap<>();
    public static final class Binding {
        private final Object subject;
        private final SurvivalAuthority.Session session;
        private Binding(Object subject, SurvivalAuthority.Session session) { this.subject = subject; this.session = session; }
        private boolean thread(Object expected) { return subject == expected && session.onOwnerThread(); }
        private boolean run(Object expected, Runnable action) {
            if (!thread(expected) || !session.current()) return false;
            try { SurvivalAuthority.run(session, () -> { SurvivalAsync.drain(); action.run(); }); }
            catch (RuntimeException | Error error) { SurvivalAsync.failed(session, error); }
            return true;
        }
    }
    private SurvivalCallbacks() { }
    public static Binding capture(Object subject) {
        Objects.requireNonNull(subject); SurvivalAsync.prepare();
        return new Binding(subject, SurvivalAuthority.session());
    }
    /** Called once in the accepted root, before starting the actual Baritone task. */
    public static void bindEvents(Object subject) {
        Binding binding = capture(subject);
        synchronized (EVENTS) {
            Binding previous = EVENTS.get(subject);
            if (previous != null) {
                if (previous.session == binding.session) return;
                throw new IllegalStateException("GAME_CALLBACK_OWNER_BUSY");
            }
            SurvivalAuthority.owned(() -> { synchronized (EVENTS) { EVENTS.remove(subject, binding); } });
            EVENTS.put(subject, binding);
        }
    }
    public static void event(Object subject, Runnable action) {
        Binding binding; synchronized (EVENTS) { binding = EVENTS.get(subject); }
        if (binding != null) binding.run(subject, action);
    }
    public static void input(Object subject, Binding binding, Runnable action, Runnable neutralize) {
        if (binding == null || !binding.thread(subject)) return;
        if (!binding.run(subject, action) || !binding.session.current()) neutralize.run();
    }
    public static void observe(Runnable action) {
        // World/chunk/render housekeeping gets no ambient task permission.
        SurvivalAuthority.withoutScope(action);
    }
    public static void clearRootEvents(RootResettable target) {
        SurvivalAuthority.requireOwnerScope(); Objects.requireNonNull(target).atsClearRootEvents();
    }
    /** Startup listeners persist; listeners created by a task retire with their original root. */
    public static void register(List<IGameEventListener> listeners, IGameEventListener listener) {
        Objects.requireNonNull(listener);
        if (!SurvivalAuthority.hasScope()) {
            if (SurvivalAsync.inCalculation()) throw new SurvivalAuthority.Denied();
            listeners.add(listener); return;
        }
        var original = SurvivalAuthority.session();
        IGameEventListener proxy = (IGameEventListener) Proxy.newProxyInstance(IGameEventListener.class.getClassLoader(),
                new Class<?>[]{IGameEventListener.class}, (self, method, args) -> {
                    if (method.getDeclaringClass() == Object.class) return switch (method.getName()) {
                        case "equals" -> self == args[0]; case "hashCode" -> System.identityHashCode(self);
                        case "toString" -> "TaskScopedBaritoneListener"; default -> throw new IllegalStateException();
                    };
                    if (original.onOwnerThread() && original.current()) SurvivalAuthority.run(original, () -> {
                        try { method.invoke(listener, args); }
                        catch (InvocationTargetException error) {
                            if (error.getCause() instanceof RuntimeException failure) throw failure;
                            if (error.getCause() instanceof Error failure) throw failure;
                            throw new IllegalStateException("GAME_CALLBACK_LISTENER_FAILED", error.getCause());
                        } catch (ReflectiveOperationException error) { throw new IllegalStateException("GAME_CALLBACK_LISTENER_FAILED", error); }
                    });
                    return null;
                });
        SurvivalAuthority.owned(() -> listeners.remove(proxy)); listeners.add(proxy);
    }
}
