package dev.aitalkstreamer.mc.survival;

import adris.altoclef.eventbus.*;
import dev.aitalkstreamer.mc.core.ControlArbiter;
import org.junit.jupiter.api.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

/** Actual prepared upstream EventBus/Subscription plus the native arbiter. */
class ScopedEventBusTest {
    private final ControlArbiter control = new ControlArbiter(() -> 10000, () -> {});
    private SurvivalAuthority.Session session;
    private final AtomicInteger effects = new AtomicInteger();
    private final List<Subscription<?>> observers = new ArrayList<>();
    private record Event(int value) { }
    @BeforeEach void setup() {
        control.world("world"); control.attach("controller"); control.release(control.epoch(), () -> {}); control.observe(1);
        control.beginAuto("controller", "world", control.epoch(), true);
        control.grant("controller", control.lease(), control.epoch(), 1, control.heartbeat(), 10000); open();
    }
    private void open() {
        var permit = control.permit();
        session = SurvivalAuthority.open(new SurvivalAuthority.Context("task", permit.controller(), permit.lease(), permit.world(), permit.epoch()),
                new ArbiterBoundary(control, permit, "task"));
    }
    private static Object topics() {
        try { var field = EventBus.class.getDeclaredField("topics"); field.setAccessible(true); return field.get(null); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    @AfterEach void cleanup() {
        session.close(() -> {}, () -> {}); observers.forEach(EventBus::unsubscribe);
    }
    @Test void taskSubscriptionRunsInItsOriginalScopeWhenAnEventArrives() {
        SurvivalAuthority.run(session, () -> EventBus.subscribe(Event.class, e -> SurvivalAuthority.write(effects::incrementAndGet)));
        assertFalse(SurvivalAuthority.inScope()); EventBus.publish(new Event(1)); assertEquals(1, effects.get()); assertFalse(SurvivalAuthority.inScope());
    }
    @Test void closedTaskIsUnsubscribedAndItsDirectLateCallbackCannotBorrowTheNextRoot() {
        AtomicReference<Subscription<Event>> old = new AtomicReference<>();
        SurvivalAuthority.run(session, () -> old.set(EventBus.subscribe(Event.class, e -> SurvivalAuthority.write(effects::incrementAndGet))));
        session.close(() -> {}, () -> {}); assertTrue(old.get().shouldDelete()); open();
        SurvivalAuthority.run(session, () -> old.get().accept(new Event(1))); EventBus.publish(new Event(2)); assertEquals(0, effects.get());
        assertFalse(((Map<?, ?>) topics()).containsKey(Event.class));
    }
    @Test void processObserversRemainAfterTaskCloseAndRunWithoutHoldingTheTopicLock() {
        observers.add(EventBus.subscribe(Event.class, e -> {
            assertFalse(Thread.holdsLock(topics())); assertFalse(SurvivalAuthority.inScope());
            assertThrows(SurvivalAuthority.Denied.class, () -> SurvivalAuthority.write(() -> fail("observer borrowed task")));
            effects.incrementAndGet();
        }));
        SurvivalAuthority.run(session, () -> { EventBus.publish(new Event(1)); assertTrue(SurvivalAuthority.inScope()); });
        session.close(() -> {}, () -> {}); EventBus.publish(new Event(2)); assertEquals(2, effects.get());
    }
    @Test void subscribingDuringDispatchStartsWithTheNextEvent() {
        AtomicBoolean added = new AtomicBoolean();
        observers.add(EventBus.subscribe(Event.class, e -> {
            if (added.compareAndSet(false, true)) observers.add(EventBus.subscribe(Event.class, later -> effects.incrementAndGet()));
        }));
        EventBus.publish(new Event(1)); assertEquals(0, effects.get()); EventBus.publish(new Event(2)); assertEquals(1, effects.get());
    }
    @Test void nestedDispatchAndUnsubscribeDoNotModifyTheActiveSnapshot() {
        AtomicBoolean nested = new AtomicBoolean(); AtomicReference<Subscription<Event>> victim = new AtomicReference<>();
        observers.add(EventBus.subscribe(Event.class, e -> {
            EventBus.unsubscribe(victim.get());
            if (nested.compareAndSet(false, true)) EventBus.publish(new Event(2));
        }));
        victim.set(EventBus.subscribe(Event.class, e -> effects.incrementAndGet())); observers.add(victim.get());
        EventBus.publish(new Event(1)); assertEquals(0, effects.get());
    }
    @Test void aThrowingListenerDoesNotLeaveTheBusLockedOrRetainDeletedListeners() {
        var failing = EventBus.subscribe(Event.class, e -> { throw new IllegalStateException("fixture"); }); observers.add(failing);
        SurvivalAuthority.run(session, () -> {
            assertThrows(IllegalStateException.class, () -> EventBus.publish(new Event(1)));
            assertTrue(SurvivalAuthority.inScope()); SurvivalAuthority.write(effects::incrementAndGet);
        });
        EventBus.unsubscribe(failing);
        observers.add(EventBus.subscribe(Event.class, e -> effects.incrementAndGet())); EventBus.publish(new Event(2)); assertEquals(2, effects.get());
    }
    @Test void aWorkerEventDoesNotAcquireTheGameThreadPermission() throws InterruptedException {
        SurvivalAuthority.run(session, () -> EventBus.subscribe(Event.class, e -> SurvivalAuthority.write(effects::incrementAndGet)));
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread worker = new Thread(() -> { try { EventBus.publish(new Event(1)); } catch (Throwable error) { failure.set(error); } });
        worker.start(); worker.join(3000); assertFalse(worker.isAlive()); assertNull(failure.get()); assertEquals(0, effects.get());
        EventBus.publish(new Event(2)); assertEquals(1, effects.get());
    }
    @Test void repeatedTaskCloseRemovesItsSubscriptionsWithoutWaitingForAnotherEvent() {
        for (int i = 0; i < 100; i++) {
            SurvivalAuthority.run(session, () -> EventBus.subscribe(Event.class, e -> effects.incrementAndGet()));
            session.close(() -> {}, () -> {});
            assertFalse(((Map<?, ?>) topics()).containsKey(Event.class));
            if (i < 99) open();
        }
        assertEquals(0, effects.get());
    }
}
