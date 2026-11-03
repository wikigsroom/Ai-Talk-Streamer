package dev.aitalkstreamer.mc.core;

import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class NativeContextTest {
    @Test void originalActualObjectsRemainValid() {
        Object w=new Object(),p=new Object(),n=new Object(),m=new Object();
        var context=new NativeContext(w,p,n,m); assertDoesNotThrow(()->context.require(w,p,n,m));
    }
    @Test void everyMissingInitialDependencyRejectsTheScope() {
        for (int index=0;index<4;index++) {
            Object[] values={new Object(),new Object(),new Object(),new Object()}; values[index]=null;
            assertEquals("GAME_INPUT_CONTEXT_UNAVAILABLE",assertThrows(IllegalStateException.class,
                    ()->new NativeContext(values[0],values[1],values[2],values[3])).getMessage());
        }
    }
    @Test void equalWorldNamesAndEqualPlayersConnectionsOrManagersAreDifferentContexts() {
        Object[] accepted={new String("world"),new String("player"),new String("connection"),new String("manager")};
        var context=new NativeContext(accepted[0],accepted[1],accepted[2],accepted[3]);
        for (int index=0;index<4;index++) {
            Object[] changed=accepted.clone(); changed[index]=new String((String)accepted[index]);
            assertEquals(accepted[index],changed[index]); assertNotSame(accepted[index],changed[index]);
            assertEquals("GAME_INPUT_CONTEXT_CHANGED",assertThrows(IllegalStateException.class,
                    ()->context.require(changed[0],changed[1],changed[2],changed[3])).getMessage());
        }
    }
    @Test void disconnectedOrReplacedActualObjectsCannotPassAnOldScope() {
        Object w=new Object(),p=new Object(),n=new Object(),m=new Object(); var context=new NativeContext(w,p,n,m);
        for (Object[] changed:new Object[][]{{null,p,n,m},{w,null,n,m},{w,p,null,m},{w,p,n,null}})
            assertThrows(IllegalStateException.class,()->context.require(changed[0],changed[1],changed[2],changed[3]));
    }
    @Test void aFreshValidArbiterPermitDoesNotAuthorizeWritesToAReplacementWorld() {
        var now=new AtomicLong(10000); var writes=new AtomicInteger();
        var control=new ControlArbiter(now::get,()->{});
        control.world("world"); control.attach("controller"); control.release(control.epoch(),()->{});
        control.observe(1); control.beginAuto("controller","world",control.epoch(),true);
        control.grant("controller",control.lease(),control.epoch(),1,control.heartbeat(),now.get());
        var permit=control.permit(); Object w=new Object(),p=new Object(),n=new Object(),m=new Object();
        var context=new NativeContext(w,p,n,m); assertTrue(control.allowed());
        assertThrows(IllegalStateException.class,()->control.actuate(permit,()->{
            context.require(new Object(),p,n,m); writes.incrementAndGet();
        }));
        assertEquals(0,writes.get()); assertTrue(control.allowed());
        control.actuate(permit,()->{ context.require(w,p,n,m); writes.incrementAndGet(); }); assertEquals(1,writes.get());
    }
    @Test void aContextChangeDoesNotPreventOriginalGenerationInputCleanup() {
        var releases=new AtomicInteger(); var fence=new InputLeaseFence(releases::incrementAndGet); var original=fence.ticket();
        Object w=new Object(),p=new Object(),n=new Object(),m=new Object(); var context=new NativeContext(w,p,n,m);
        assertThrows(IllegalStateException.class,()->context.require(null,null,null,null));
        original.release(); assertEquals(1,releases.get()); var later=fence.ticket();
        original.release(); assertEquals(1,releases.get()); assertDoesNotThrow(later::check);
    }
}
