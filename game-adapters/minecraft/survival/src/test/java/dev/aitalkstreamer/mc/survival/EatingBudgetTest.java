package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Server facts and original deadlines; no running game or fabricated playback acceptance. */
class EatingBudgetTest {
    final EatingBudget budget=new EatingBudget(0);
    void begin() { budget.begin(0,10,4);budget.issue(1); }
    @Test void consumptionRequiresBothInventoryAndTheExpectedFoodLevel() {
        begin();budget.inventory(2,true);assertFalse(budget.resolved(2));budget.health(3,13);assertFalse(budget.resolved(3));
        budget.health(4,14);assertTrue(budget.resolved(4));budget.restored(5);assertFalse(budget.full());
    }
    @Test void healthBeforeTheInventoryProofCannotCompleteTheBiteAlone() {
        begin();budget.health(2,14);assertFalse(budget.resolved(3));budget.inventory(4,true);assertTrue(budget.resolved(5));
    }
    @Test void healthFromBeforeIssueIsNotEvidenceForThisBite() {
        budget.begin(0,10,4);budget.health(1,20);budget.issue(2);budget.inventory(3,true);assertFalse(budget.resolved(4));
    }
    @Test void aConfirmedZeroEffectCanFinishAndPermitABoundedNewAttempt() {
        begin();budget.inventory(2,false);assertTrue(budget.resolved(3));budget.restored(4);
        budget.begin(5,10,4);budget.issue(6);budget.inventory(7,true);assertFalse(budget.resolved(8));
    }
    @Test void interruptionBeforeIssueCanResolveZeroButCannotClaimConsumption() {
        budget.begin(0,10,4);assertThrows(IllegalStateException.class,()->budget.inventory(1,true));
        budget.inventory(2,false);budget.restored(3);assertFalse(budget.full());
    }
    @Test void theSameAttemptCannotIssueTwiceOrReplaceItsConfirmedOutcome() {
        begin();assertThrows(IllegalStateException.class,()->budget.issue(2));budget.inventory(3,true);
        assertThrows(IllegalStateException.class,()->budget.inventory(4,false));
    }
    @Test void anUnresolvedBiteCannotRestoreOrStartAReplacementBite() {
        begin();assertThrows(IllegalStateException.class,()->budget.restored(2));
        assertThrows(LocalTaskFailure.class,()->budget.begin(3,10,4));
    }
    @Test void theBiteDeadlineSurvivesInterruptionAndRejectsLateFoodPackets() {
        begin();budget.inventory(9000,true);budget.check(9999);
        assertThrows(LocalTaskFailure.class,()->budget.health(10000,20));
        assertThrows(LocalTaskFailure.class,()->budget.resolved(10001));
    }
    @Test void aNewBiteCannotResetTheAbsoluteEpisodeDeadline() {
        budget.begin(119000,10,4);budget.issue(119001);budget.inventory(119002,false);budget.restored(119003);
        budget.begin(119004,10,4);assertThrows(LocalTaskFailure.class,()->budget.check(120000));
    }
    @Test void twentyConfirmedZeroEffectsStillHaveAFiniteEpisodeLimit() {
        for(int i=0;i<20;i++){budget.begin(i*5,10,4);budget.issue(i*5+1);budget.inventory(i*5+2,false);budget.restored(i*5+3);}
        assertThrows(LocalTaskFailure.class,()->budget.begin(100,10,4));
    }
    @Test void onlyConsumedInventoryAndServerFullHungerCloseTheEpisode() {
        budget.begin(0,19,4);budget.issue(1);budget.inventory(2,true);budget.health(3,20);budget.restored(4);
        assertTrue(budget.full());assertThrows(LocalTaskFailure.class,()->budget.begin(5,10,4));
    }
    @Test void regressingClockAndInvalidFoodFactsDoNotStartAValidAttempt() {
        assertThrows(IllegalArgumentException.class,()->budget.begin(0,20,4));
        assertThrows(IllegalArgumentException.class,()->budget.begin(0,10,0));
        budget.check(10);assertThrows(IllegalArgumentException.class,()->budget.check(9));
    }
}
