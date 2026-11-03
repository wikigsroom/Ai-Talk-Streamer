package dev.aitalkstreamer.mc.core;
import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;
class HeldActionRouterTest {
    @Test void physicalActionsRunExactlyOnceWithoutBorrowingAnAutomaticScope() {
        var effects=new AtomicInteger();
        var router=new HeldActionRouter(new HeldActionRouter.Boundary() {
            public boolean owns(HeldActionRouter.Action a) { return false; }
            public void run(HeldActionRouter.Action a,Runnable e) { fail("physical input cannot enter automatic boundary"); }
        });
        assertEquals(1,router.route(HeldActionRouter.Action.ATTACK,effects::incrementAndGet,-1));assertEquals(1,effects.get());
    }
    @Test void aRevokedOriginalPermitCannotBorrowAReplacementAutomaticGrant() {
        var now=new AtomicLong(10000);var control=new ControlArbiter(now::get,()->{});
        control.world("world");control.attach("controller");control.release(control.epoch(),()->{});control.observe(1);
        control.beginAuto("controller","world",control.epoch(),true);control.grant("controller",control.lease(),control.epoch(),1,control.heartbeat(),10000);
        var original=control.permit();var effects=new AtomicInteger();
        var router=new HeldActionRouter(new HeldActionRouter.Boundary() {
            public boolean owns(HeldActionRouter.Action a) { return true; }
            public void run(HeldActionRouter.Action a,Runnable e) { control.actuate(original,e); }
        });
        assertEquals(1,router.route(HeldActionRouter.Action.BREAK,effects::incrementAndGet,-1));
        control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY);control.release(control.epoch(),()->{});control.observe(2);
        control.beginAuto("controller","world",control.epoch(),true);control.grant("controller",control.lease(),control.epoch(),1,control.heartbeat(),10000);
        assertThrows(Json.Rejected.class,()->router.route(HeldActionRouter.Action.BREAK,effects::incrementAndGet,-1));assertEquals(1,effects.get());
    }
    @Test void aSuppressedRepeatedUseDoesNotReplayOrInventAnEffect() {
        var effects=new AtomicInteger();var router=new HeldActionRouter(new HeldActionRouter.Boundary() {
            public boolean owns(HeldActionRouter.Action a) { return true; }
            public void run(HeldActionRouter.Action a,Runnable e) { }
        });
        assertEquals(-1,router.route(HeldActionRouter.Action.USE,effects::incrementAndGet,-1));assertEquals(0,effects.get());
    }
    @Test void anOriginalGameExceptionIsNotTurnedIntoSuccessOrRetried() {
        var effects=new AtomicInteger();var error=new IllegalStateException("partial game effect");
        var router=new HeldActionRouter(new HeldActionRouter.Boundary() {
            public boolean owns(HeldActionRouter.Action a) { return true; }
            public void run(HeldActionRouter.Action a,Runnable e) { e.run(); }
        });
        assertSame(error,assertThrows(IllegalStateException.class,()->router.route(HeldActionRouter.Action.USE,()->{effects.incrementAndGet();throw error;},false)));
        assertEquals(1,effects.get());
    }
}
