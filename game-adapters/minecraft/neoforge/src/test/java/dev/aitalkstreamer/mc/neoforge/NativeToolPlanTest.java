package dev.aitalkstreamer.mc.neoforge;

import org.junit.jupiter.api.Test;
import java.util.ArrayList;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.neoforge.NativeToolPlan.*;

class NativeToolPlanTest {
    private List<Candidate> stock(){return new ArrayList<>(java.util.Collections.nCopies(36,new Candidate(false,1,-1)));}
    @Test void backpackCorrectTierBeatsIncorrectFastTool(){var s=stock();s.set(2,new Candidate(false,20,100));s.set(12,new Candidate(true,4,100));assertEquals(12,choose(s,2));}
    @Test void fasterBackpackToolBeatsUsableHotbarTool(){var s=stock();s.set(4,new Candidate(true,2,50));s.set(20,new Candidate(true,4,60));assertEquals(20,choose(s,4));}
    @Test void selectedSlotWinsAnEqualSpeedTie(){var s=stock();s.set(0,new Candidate(true,4,100));s.set(7,new Candidate(true,4,2));assertEquals(7,choose(s,7));}
    @Test void equalSpeedHotbarAvoidsAnUnnecessarySwap(){var s=stock();s.set(5,new Candidate(true,4,2));s.set(9,new Candidate(true,4,100));assertEquals(5,choose(s,0));}
    @Test void longerLivedEquivalentBackpackToolWins(){var s=stock();s.set(10,new Candidate(true,4,2));s.set(18,new Candidate(true,4,120));assertEquals(18,choose(s,0));}
    @Test void finalDurabilityPointIsReserved(){var s=stock();s.set(0,new Candidate(true,8,1));s.set(11,new Candidate(true,4,2));assertEquals(11,choose(s,0));}
    @Test void noCorrectTierReturnsUnavailable(){assertEquals(-1,choose(stock(),0));}
    @Test void nonDurableHandCanHarvestWhenTheLiveStatePermits(){var s=stock();s.set(3,new Candidate(true,1,-1));assertEquals(3,choose(s,3));}
    @Test void invalidModdedSpeedsCannotWin(){var s=stock();s.set(0,new Candidate(true,Float.NaN,100));s.set(1,new Candidate(true,Float.POSITIVE_INFINITY,100));s.set(2,new Candidate(true,-1,100));s.set(12,new Candidate(true,2,100));assertEquals(12,choose(s,0));}
    @Test void exhaustedAndMalformedDurabilityCannotWin(){var s=stock();s.set(0,new Candidate(true,8,0));s.set(1,new Candidate(true,8,-2));assertEquals(-1,choose(s,0));}
    @Test void wrongInventorySizeIsRejected(){assertThrows(RuntimeException.class,()->choose(List.of(),0));}
    @Test void invalidSelectedSlotIsRejected(){assertThrows(RuntimeException.class,()->choose(stock(),9));}
}
