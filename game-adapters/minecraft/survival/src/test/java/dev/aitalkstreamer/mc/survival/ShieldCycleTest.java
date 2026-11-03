package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import org.junit.jupiter.api.Test;
import static dev.aitalkstreamer.mc.survival.ShieldCycle.Action.*;
import static dev.aitalkstreamer.mc.survival.ShieldCycle.Source.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;
import static org.junit.jupiter.api.Assertions.*;

class ShieldCycleTest {
    ShieldCycle start() { var c = new ShieldCycle(0); c.begin(0); c.request(THREAT); assertEquals(START,c.finish(0,true,false)); c.accepted(true,true); return c; }
    @Test void idleTickDoesNotIssueUse() { var c=new ShieldCycle(0); c.begin(0); assertEquals(NONE,c.finish(0,true,false)); assertFalse(c.busy()); }
    @Test void offhandRequestIssuesExactlyOnceUntilItStops() { var c=start(); for(int i=1;i<20;i++){c.begin(i);c.request(THREAT);assertEquals(KEEP,c.finish(i,true,true));} }
    @Test void demandExpiresWhenTheUpstreamBranchStopsReevaluatingIt() { var c=start(); c.begin(50); assertEquals(STOP,c.finish(50,true,true)); assertTrue(c.issued()); c.stopped(); assertFalse(c.busy()); }
    @Test void withdrawingMeleeCannotReleaseAnActiveProjectileDemand() { var c=new ShieldCycle(0); c.begin(0);c.request(THREAT);c.request(MELEE);c.withdraw(MELEE);assertEquals(START,c.finish(0,true,false));assertTrue(c.demanded(THREAT)); }
    @Test void withdrawingThreatCannotReleaseMeleeDemand() { var c=new ShieldCycle(0);c.begin(0);c.request(THREAT);c.request(MELEE);c.withdraw(THREAT);assertEquals(START,c.finish(0,true,false));assertTrue(c.demanded(MELEE)); }
    @Test void equipmentOrFoodPendingDoesNotPredictShieldStart() { var c=new ShieldCycle(0);c.begin(0);c.request(THREAT);assertEquals(WAIT,c.finish(0,false,false));assertFalse(c.issued());assertTrue(c.busy()); }
    @Test void confirmedEquipmentCanSatisfyTheSamePendingRequest() { var c=new ShieldCycle(0);c.begin(0);c.request(THREAT);c.finish(0,false,false);c.begin(500);c.request(THREAT);assertEquals(START,c.finish(500,true,false)); }
    @Test void waitingSurvivesPriorityReselectionAndExpires() { var c=new ShieldCycle(0);for(int t=0;t<8000;t+=100){c.begin(t);c.request(THREAT);assertEquals(WAIT,c.finish(t,false,false));}c.begin(8000);c.request(THREAT);assertEquals(SHIELD_TIMEOUT,assertThrows(LocalTaskFailure.class,()->c.finish(8000,true,false)).reason); }
    @Test void aRejectedNativeUseIsNotReportedAsBlocking() { var c=start();assertEquals(SHIELD_USE_REJECTED,assertThrows(LocalTaskFailure.class,()->c.accepted(false,true)).reason);assertTrue(c.issued()); }
    @Test void anAcceptedUseWithoutTheActualOffhandAnimationIsNotBlocking() { var c=start();assertEquals(SHIELD_USE_REJECTED,assertThrows(LocalTaskFailure.class,()->c.accepted(true,false)).reason); }
    @Test void localShieldLossStopsBeforeAnyNewAttempt() { var c=start();c.begin(50);c.request(THREAT);assertEquals(STOP,c.finish(50,true,false));assertTrue(c.issued());c.stopped();c.begin(100);c.request(THREAT);assertEquals(START,c.finish(100,true,false)); }
    @Test void cooldownCannotIssueANewUseAfterShieldLoss() { var c=start();c.begin(50);c.request(THREAT);assertEquals(STOP,c.finish(50,false,false));c.stopped();c.begin(100);c.request(THREAT);assertEquals(WAIT,c.finish(100,false,false)); }
    @Test void sustainedHoldIsBoundedWithoutRefreshingItsDeadline() { var c=start();for(int t=100;t<10000;t+=100){c.begin(t);c.request(THREAT);c.finish(t,true,true);}assertEquals(SHIELD_TIMEOUT,assertThrows(LocalTaskFailure.class,()->c.begin(10000)).reason); }
    @Test void repeatedStopAndRestartCannotExtendTheOriginalEncounter() { var c=start();for(int t=1000;t<60000;t+=1000){c.stopped();c.begin(t);c.request(THREAT);assertEquals(START,c.finish(t,true,false));}c.stopped();assertEquals(SHIELD_TIMEOUT,assertThrows(LocalTaskFailure.class,()->c.begin(60000)).reason); }
    @Test void repeatedStartsAreBoundedEvenWhenTheServerKeepsCancelling() { var c=start();for(int t=1;t<64;t++){c.stopped();c.begin(t);c.request(THREAT);assertEquals(START,c.finish(t,true,false));}c.stopped();c.begin(64);c.request(THREAT);assertEquals(SHIELD_LIMIT,assertThrows(LocalTaskFailure.class,()->c.finish(64,true,false)).reason); }
    @Test void aShortPriorityGapDoesNotResetTheStartLimit() { var c=start();for(int t=1;t<64;t++){c.stopped();c.begin(t);c.request(MELEE);c.finish(t,true,false);}c.stopped();c.begin(100);assertEquals(NONE,c.finish(100,true,false));c.begin(200);c.request(THREAT);assertEquals(SHIELD_LIMIT,assertThrows(LocalTaskFailure.class,()->c.finish(200,true,false)).reason); }
    @Test void aReleasedQuietIntervalAllowsANewEncounter() { var c=start();c.stopped();c.begin(2000);c.request(THREAT);assertEquals(START,c.finish(2000,true,false)); }
    @Test void aQuietIntervalNeverResetsAnUnreleasedShield() { var c=start();assertEquals(SHIELD_TIMEOUT,assertThrows(LocalTaskFailure.class,()->c.begin(10000)).reason); }
    @Test void meleeAttackMutesOnlyItsOwnDemandForThisTick() { var c=new ShieldCycle(0);c.begin(0);c.request(MELEE);assertTrue(c.beforeAttack());c.request(MELEE);assertEquals(NONE,c.finish(0,true,false)); }
    @Test void aProjectileDemandBlocksTheAttackInsteadOfLoweringTheShield() { var c=new ShieldCycle(0);c.begin(0);c.request(THREAT);c.request(MELEE);assertFalse(c.beforeAttack());assertEquals(START,c.finish(0,true,false)); }
    @Test void aMeleeAttackCanResumeShieldingOnTheNextTick() { var c=new ShieldCycle(0);c.begin(0);c.request(MELEE);c.beforeAttack();c.finish(0,true,false);c.begin(50);c.request(MELEE);assertEquals(START,c.finish(50,true,false)); }
    @Test void anExplicitOwnedStopSuppressesLateUseDuringTheSameTick() { var c=start();c.begin(50);c.request(THREAT);c.suppress();assertEquals(STOP,c.finish(50,true,true));c.stopped();assertFalse(c.busy()); }
    @Test void revokedCleanupForgetsDemandAndCannotBeReused() { var c=start();c.close();assertFalse(c.busy());assertFalse(c.issued());assertThrows(IllegalStateException.class,()->c.begin(50));assertThrows(IllegalStateException.class,()->c.request(THREAT)); }
    @Test void nestedTickAndDoubleFinishAreRejected() { var c=new ShieldCycle(0);c.begin(0);assertThrows(IllegalStateException.class,()->c.begin(1));c.finish(1,true,false);assertThrows(IllegalStateException.class,()->c.finish(1,true,false)); }
    @Test void theOriginalMonotonicClockCannotBeRewound() { var c=new ShieldCycle(10);assertThrows(IllegalStateException.class,()->c.begin(9));assertThrows(IllegalArgumentException.class,()->new ShieldCycle(-1)); }
    @Test void pendingCancellationNeverManufacturesAUseToStop() { var c=new ShieldCycle(0);c.begin(0);c.request(THREAT);c.finish(0,false,false);c.begin(50);assertEquals(NONE,c.finish(50,true,false));assertFalse(c.issued()); }
    @Test void idleNativeAttacksOutsideTheUpstreamFrameRemainAvailable() { var c=new ShieldCycle(0);assertTrue(c.beforeAttack());c.begin(0);c.finish(0,true,false);assertTrue(c.beforeAttack()); }
    @Test void heldOrPendingDemandCannotBeLoweredByAnOutOfFrameAttack() { var c=start();assertFalse(c.beforeAttack());var waiting=new ShieldCycle(0);waiting.begin(0);waiting.request(MELEE);waiting.finish(0,false,false);assertFalse(waiting.beforeAttack()); }
    @Test void anIdleTickNeverInspectsOtherInventoryTransactions() { var c=new ShieldCycle(0);c.begin(0);assertEquals(NONE,c.finish(0,()->{fail("Idle shield code inspected an unrelated cursor or inventory");return false;},false)); }
    @Test void aHeldShieldOrAStopDoesNotProbeForANewEquipmentStart() { var c=start();c.begin(50);c.request(THREAT);assertEquals(KEEP,c.finish(50,()->{fail("An existing shield probed new-use admission");return false;},true));c.begin(100);assertEquals(STOP,c.finish(100,()->{fail("Shield stop probed unrelated equipment");return false;},true)); }
}
