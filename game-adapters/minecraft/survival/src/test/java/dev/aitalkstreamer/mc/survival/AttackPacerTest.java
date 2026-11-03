package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

class AttackPacerTest {
    @Test void severalCandidatesAndVanillaCallbacksShareOneAttackPerPlayerTick() {
        var pacer=new AttackPacer();var writes=new AtomicInteger();
        assertTrue(pacer.issue(20,1,writes::incrementAndGet));
        assertFalse(pacer.issue(20,1,writes::incrementAndGet));assertFalse(pacer.ready(20,1));assertEquals(1,writes.get());
    }
    @Test void aNewTickStillRequiresActualAttackCooldown() {
        var pacer=new AttackPacer();var writes=new AtomicInteger();pacer.issue(20,1,writes::incrementAndGet);
        assertFalse(pacer.issue(21,.99f,writes::incrementAndGet));assertTrue(pacer.issue(40,1,writes::incrementAndGet));assertEquals(2,writes.get());
    }
    @Test void anExceptionDoesNotAllowAutomaticReplayInTheSameTick() {
        var pacer=new AttackPacer();var writes=new AtomicInteger();
        assertThrows(IllegalStateException.class,()->pacer.issue(20,1,()->{writes.incrementAndGet();throw new IllegalStateException("game");}));
        assertFalse(pacer.issue(20,1,writes::incrementAndGet));assertEquals(1,writes.get());
    }
    @Test void invalidCooldownIsNotAnAttackGrant() {
        var pacer=new AttackPacer();for(float value:new float[]{Float.NaN,Float.POSITIVE_INFINITY,-1,0})assertFalse(pacer.ready(1,value));
        assertTrue(pacer.ready(1,1));
    }
    @Test void tickCounterRolloverDoesNotFreezeFutureAttacks() {
        var pacer=new AttackPacer();assertTrue(pacer.issue(Integer.MAX_VALUE,1,()->{}));assertTrue(pacer.issue(Integer.MIN_VALUE,1,()->{}));
    }
}
