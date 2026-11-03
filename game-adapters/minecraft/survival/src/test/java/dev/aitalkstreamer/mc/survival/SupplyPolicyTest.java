package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

class SupplyPolicyTest {
    private SupplyPolicy.Facts food(int units) { return new SupplyPolicy.Facts(units,0); }
    private SupplyPolicy policy() { return new SupplyPolicy(0,40,food(0)); }
    @Test void targetStockCannotCompleteUntilTheCookingChildIsClean() {
        var p=policy(); assertEquals(SupplyPolicy.Mode.COLLECT,p.observe(1000,food(40),false).mode());
        assertEquals(SupplyPolicy.Mode.FINISHED,p.observe(1001,food(40),true).mode());
    }
    @Test void waitingForChildCleanupDoesNotExtendTheAbsoluteSupplyDeadline() {
        var p=policy(); p.observe(40_000,food(40),false); p.observe(80_000,food(41),false);
        assertEquals(SUPPLY_TIMEOUT,p.observe(120_000,food(42),true).reason());
    }
    @Test void anObservedFoodReserveFinishesOnlyTheInternalAcquisition() {
        var p=policy(); assertEquals(SupplyPolicy.Mode.COLLECT,p.observe(1000,food(39)).mode());
        var done=p.observe(2000,food(40)); assertEquals(SupplyPolicy.Mode.FINISHED,done.mode());assertNull(done.reason());
    }
    @Test void existingFoodCountsTowardTheTotalRatherThanAnotherRequestedIncrement() {
        var p=new SupplyPolicy(0,40,food(32));assertEquals(SupplyPolicy.Mode.FINISHED,p.observe(1,food(40)).mode());
    }
    @Test void movementAndRepeatedObservationsCannotRenewTheNoProgressClock() {
        var p=policy();p.observe(44_999,new SupplyPolicy.Facts(0,100));
        assertEquals(SUPPLY_NO_PROGRESS,p.observe(45_000,new SupplyPolicy.Facts(0,1)).reason());
    }
    @Test void aNewObservedInventoryHighWaterMarkRenewsOnlyTheProgressWindow() {
        var p=policy();p.observe(44_000,food(5));assertEquals(SupplyPolicy.Mode.COLLECT,p.observe(88_999,food(5)).mode());
        assertEquals(SUPPLY_NO_PROGRESS,p.observe(89_000,food(5)).reason());
    }
    @Test void consumingDroppingAndReacquiringTheSameFoodDoesNotBecomeEndlessProgress() {
        var p=new SupplyPolicy(0,40,food(10));p.observe(20_000,food(0));p.observe(40_000,food(10));
        assertEquals(SUPPLY_NO_PROGRESS,p.observe(45_000,food(10)).reason());
    }
    @Test void steadyInventoryProgressDoesNotRenewTheAbsoluteDeadline() {
        var p=policy();p.observe(40_000,food(10));p.observe(80_000,food(20));p.observe(119_999,food(30));
        assertEquals(SUPPLY_TIMEOUT,p.observe(120_000,food(40)).reason());
    }
    @Test void anEmergencyInterruptionStillCountsAgainstTheOriginalDeadline() {
        var p=policy();p.observe(1000,food(1));assertEquals(SUPPLY_TIMEOUT,p.observe(120_000,food(1)).reason());
    }
    @Test void theOriginalAnchorBoundsFoodSearchEvenIfInventoryImproves() {
        var p=policy();assertEquals(SupplyPolicy.Mode.COLLECT,p.observe(1,new SupplyPolicy.Facts(1,96*96)).mode());
        assertEquals(SUPPLY_RANGE_LIMIT,p.observe(2,new SupplyPolicy.Facts(40,96*96+1)).reason());
    }
    @Test void aFailedAttemptCannotLaterBecomeCompleted() {
        var p=policy();var first=p.observe(45_000,food(0));assertSame(first,p.observe(45_001,food(100)));
    }
    @Test void aFinishedReserveIsNotReopenedByLaterConsumption() {
        var p=policy();var first=p.observe(1,food(40));assertSame(first,p.observe(200_000,food(0)));
    }
    @Test void invalidFoodTargetsFailWithAFixedPublicReason() {
        for(double target:new double[]{0,-1,257,1.5,Double.NaN,Double.POSITIVE_INFINITY})
            assertEquals(SUPPLY_CONFIG_INVALID,assertThrows(LocalTaskFailure.class,()->SupplyPolicy.validateTarget(target)).reason);
        assertEquals(1,SupplyPolicy.validateTarget(1));assertEquals(256,SupplyPolicy.validateTarget(256));
    }
    @Test void breadAndWheatTargetsRoundToFiniteWholeRecipes() {
        assertEquals(1,SupplyPolicy.breadTarget(1));assertEquals(1,SupplyPolicy.breadTarget(5));
        assertEquals(2,SupplyPolicy.breadTarget(6));assertEquals(8,SupplyPolicy.breadTarget(40));
        assertEquals(24,SupplyPolicy.wheatTarget(40));assertEquals(156,SupplyPolicy.wheatTarget(256));
    }
    @Test void invalidTargetsCannotReachTheRecipeHelpers() {
        assertThrows(LocalTaskFailure.class,()->SupplyPolicy.breadTarget(Double.NaN));
        assertThrows(LocalTaskFailure.class,()->SupplyPolicy.wheatTarget(100_000_000));
    }
    @Test void explicitCollectionOptOutIsPreservedAndContradictorySettingsAreRejected() {
        SupplyPolicy.validateSettings(0,0);SupplyPolicy.validateSettings(12,40);
        for(int[] pair:new int[][]{{0,40},{12,0},{41,40},{-1,40},{1,257}})
            assertEquals(SUPPLY_CONFIG_INVALID,assertThrows(LocalTaskFailure.class,()->SupplyPolicy.validateSettings(pair[0],pair[1])).reason);
    }
    @Test void protectedTaskFoodStillCountsAsStockAndCannotCauseACompletedSupplyLoop() {
        // The consumption score may be zero because the public task protects these stacks.
        assertFalse(SupplyPolicy.needsCollection(40,12,40,false));
        assertFalse(SupplyPolicy.needsCollection(40,12,40,true));
        assertFalse(SupplyPolicy.needsCollection(60,12,40,false));
    }
    @Test void aStartedSupplyKeepsItsTargetUntilFinishedButDoesNotRestartAtTheSameStock() {
        assertTrue(SupplyPolicy.needsCollection(11,12,40,false));
        assertFalse(SupplyPolicy.needsCollection(12,12,40,false));
        assertTrue(SupplyPolicy.needsCollection(12,12,40,true));
        assertTrue(SupplyPolicy.needsCollection(39,12,40,true));
        assertFalse(SupplyPolicy.needsCollection(40,12,40,true));
        assertFalse(SupplyPolicy.needsCollection(39,12,40,false));
    }
    @Test void anExplicitOptOutStopsACollectionRequestWithoutInventingNegativeStock() {
        assertFalse(SupplyPolicy.needsCollection(0,0,0,false));
        assertFalse(SupplyPolicy.needsCollection(0,0,0,true));
        assertThrows(IllegalArgumentException.class,()->SupplyPolicy.needsCollection(-1,12,40,false));
    }
    @Test void unknownOrInvalidInventoryAndDistanceAreNotInventedAsSafeFacts() {
        assertThrows(IllegalArgumentException.class,()->food(-1));
        assertThrows(IllegalArgumentException.class,()->new SupplyPolicy.Facts(0,Double.NaN));
        assertThrows(IllegalArgumentException.class,()->new SupplyPolicy.Facts(0,-1));
    }
    @Test void aRegressingClockCannotRenewAnAttempt() {
        var p=policy();p.observe(1000,food(1));assertThrows(IllegalArgumentException.class,()->p.observe(999,food(2)));
    }
}
