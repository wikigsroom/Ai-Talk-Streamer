package dev.aitalkstreamer.mc.survival;

import baritone.api.event.listener.IGameEventListener;
import baritone.api.event.listener.AbstractGameEventListener;
import baritone.api.event.events.PathEvent;
import adris.altoclef.eventbus.EventBus;
import dev.aitalkstreamer.mc.core.ControlArbiter;
import org.junit.jupiter.api.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;

/** Actual callback authority and native arbiter; all effects here are explicit CPU fixtures. */
class SurvivalCallbacksTest {
    private final AtomicLong now = new AtomicLong(10000);
    private final ControlArbiter control = new ControlArbiter(now::get, () -> {});
    private SurvivalAuthority.Session session;
    private final Object bus = new Object(), input = new Object();
    private final AtomicInteger effects = new AtomicInteger(), neutralized = new AtomicInteger();
    @BeforeEach void setup() {
        control.world("world");control.attach("controller");control.release(control.epoch(),()->{});control.observe(1);
        control.beginAuto("controller","world",control.epoch(),true);
        control.grant("controller",control.lease(),control.epoch(),1,control.heartbeat(),10000);open();
    }
    private void open() {
        var p=control.permit();session=SurvivalAuthority.open(new SurvivalAuthority.Context("task",p.controller(),p.lease(),p.world(),p.epoch()),new ArbiterBoundary(control,p,"task"));
    }
    private void bind() { SurvivalAuthority.run(session,()->SurvivalCallbacks.bindEvents(bus)); }
    private void effect() { SurvivalAuthority.write(effects::incrementAndGet); }
    private SurvivalCallbacks.Binding inputBinding() { var value=new AtomicReference<SurvivalCallbacks.Binding>();SurvivalAuthority.run(session,()->value.set(SurvivalCallbacks.capture(input)));return value.get(); }
    @AfterEach void cleanup() { session.close(()->{},()->{}); }
    @Test void unboundEventCannotAcquireTheActiveRoot() { SurvivalCallbacks.event(bus,this::effect);assertEquals(0,effects.get()); }
    @Test void boundEventEntersTheOriginalScopeAndRestoresItsCaller() {
        bind();SurvivalCallbacks.event(bus,this::effect);assertEquals(1,effects.get());assertFalse(SurvivalAuthority.inScope());
    }
    @Test void workerEventCannotAcquireClientThreadPermission() throws InterruptedException {
        bind();Thread thread=new Thread(()->SurvivalCallbacks.event(bus,this::effect));thread.start();thread.join(3000);
        assertFalse(thread.isAlive());assertEquals(0,effects.get());
    }
    @Test void oldInputNeutralizesItsOwnObjectAndCannotBorrowTheNextTask() {
        var old=inputBinding();session.close(()->{},()->{});open();bind();
        SurvivalAuthority.run(session,()->SurvivalCallbacks.input(input,old,this::effect,neutralized::incrementAndGet));
        assertEquals(0,effects.get());assertEquals(1,neutralized.get());SurvivalCallbacks.event(bus,this::effect);assertEquals(1,effects.get());
    }
    @Test void inputBindingCannotBeUsedForAnotherObject() {
        var binding=inputBinding();SurvivalCallbacks.input(new Object(),binding,this::effect,neutralized::incrementAndGet);
        assertEquals(0,effects.get());assertEquals(0,neutralized.get());
    }
    @Test void wrongThreadCannotEvenNeutralizeTheInputObject() throws InterruptedException {
        var binding=inputBinding();Thread thread=new Thread(()->SurvivalCallbacks.input(input,binding,this::effect,neutralized::incrementAndGet));
        thread.start();thread.join(3000);assertFalse(thread.isAlive());assertEquals(0,effects.get());assertEquals(0,neutralized.get());
    }
    @Test void expiredLeaseSkipsEventsAndNeutralizesTheOldInput() {
        bind();var binding=inputBinding();now.set(21000);
        SurvivalCallbacks.event(bus,this::effect);SurvivalCallbacks.input(input,binding,this::effect,neutralized::incrementAndGet);
        assertEquals(0,effects.get());assertEquals(1,neutralized.get());
    }
    @Test void eventFailureRevokesTheRootAndIsAvailableToTheTaskRunner() {
        bind();SurvivalCallbacks.event(bus,()->{throw new IllegalArgumentException("fixture");});assertFalse(session.current());
        var error=assertThrows(IllegalStateException.class,()->SurvivalAsync.throwFailure(session));
        assertEquals("GAME_SURVIVAL_ASYNC_FAILED",error.getMessage());assertInstanceOf(IllegalArgumentException.class,error.getCause());
    }
    @Test void failedInputTickAlsoNeutralizesItsPreviousValues() {
        var binding=inputBinding();SurvivalCallbacks.input(input,binding,()->{throw new IllegalStateException("fixture");},neutralized::incrementAndGet);
        assertFalse(session.current());assertEquals(1,neutralized.get());
    }
    @Test void processObservationDoesNotBorrowThePublisherScopeEvenOnFailure() {
        SurvivalAuthority.run(session,()->{
            assertThrows(IllegalArgumentException.class,()->SurvivalCallbacks.observe(()->{
                assertFalse(SurvivalAuthority.inScope());assertThrows(SurvivalAuthority.Denied.class,this::effect);throw new IllegalArgumentException("fixture");
            }));assertTrue(SurvivalAuthority.inScope());effect();
        });assertEquals(1,effects.get());
    }
    @Test void taskListenerRetiresAtCloseAndItsRetainedProxyCannotBorrowTheNextRoot() {
        List<IGameEventListener> listeners=new ArrayList<>();
        SurvivalAuthority.run(session,()->SurvivalCallbacks.register(listeners,new AbstractGameEventListener(){@Override public void onPathEvent(PathEvent event){effect();}}));
        var old=listeners.getFirst();old.onPathEvent(PathEvent.AT_GOAL);assertEquals(1,effects.get());
        session.close(()->{},()->{});assertTrue(listeners.isEmpty());open();
        SurvivalAuthority.run(session,()->old.onPathEvent(PathEvent.AT_GOAL));assertEquals(1,effects.get());
    }
    @Test void processListenerRemainsRegisteredAfterTaskClose() {
        List<IGameEventListener> listeners=new ArrayList<>();IGameEventListener listener=new AbstractGameEventListener(){};
        SurvivalCallbacks.register(listeners,listener);session.close(()->{},()->{});assertEquals(List.of(listener),listeners);
    }
    @Test void taskOwnedCleanupOrWorkerCannotCreatePersistentProcessListeners() throws Exception {
        List<IGameEventListener> listeners=new ArrayList<>();
        record RegistrationEvent() { }
        Runnable rejectRegistration=()->{
            assertThrows(SurvivalAuthority.Denied.class,()->SurvivalCallbacks.register(listeners,new AbstractGameEventListener(){}));
            assertThrows(SurvivalAuthority.Denied.class,()->EventBus.subscribe(RegistrationEvent.class,event->effects.incrementAndGet()));
        };
        try(var worker=Executors.newSingleThreadExecutor()) {
            SurvivalAuthority.run(session,()->SurvivalAsync.execute(worker,rejectRegistration));
            worker.submit(()->{}).get(3,TimeUnit.SECONDS);
            assertDoesNotThrow(()->SurvivalAsync.throwFailure(session));
        }
        session.close(()->{},rejectRegistration);EventBus.publish(new RegistrationEvent());assertEquals(0,effects.get());
        assertTrue(listeners.isEmpty());
    }
    @Test void eventQueueResetRequiresTheOriginalOwnerScopeIncludingRevokedClose() {
        List<String> queue=new ArrayList<>(List.of("old"));SurvivalCallbacks.RootResettable target=queue::clear;
        assertThrows(SurvivalAuthority.Denied.class,()->SurvivalCallbacks.clearRootEvents(target));
        session.close(()->{},()->SurvivalCallbacks.clearRootEvents(target));assertTrue(queue.isEmpty());
    }
    @Test void closedEventBindingsDoNotAccumulateAcrossOneHundredRoots() throws ReflectiveOperationException {
        var field=SurvivalCallbacks.class.getDeclaredField("EVENTS");field.setAccessible(true);
        for(int i=0;i<100;i++) {bind();session.close(()->{},()->{});assertTrue(((Map<?,?>)field.get(null)).isEmpty());if(i<99)open();}
    }
}
