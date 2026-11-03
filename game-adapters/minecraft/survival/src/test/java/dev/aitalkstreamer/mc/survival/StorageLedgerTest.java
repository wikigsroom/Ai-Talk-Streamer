package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.Json;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class StorageLedgerTest {
    final StorageLedger<String> ledger=new StorageLedger<>();
    @Test void containerContentsDoNotExistInTheTaskDepositLedger(){assertEquals(12,ledger.need(List.of("iron"),12));}
    @Test void multipleConfirmedMovesAccumulateOnlyTheirTransferredAmount(){ledger.credit("iron",3);ledger.credit("iron",2);assertEquals(7,ledger.need(List.of("iron"),12));}
    @Test void matchingAlternativesCountTheSameConfirmedUnitOnlyOnce(){ledger.credit("oak",3);assertEquals(2,ledger.need(List.of("oak","oak","birch"),5));}
    @Test void unrelatedItemsNeverFillTheDesiredGoal(){ledger.credit("stone",12);assertEquals(12,ledger.need(List.of("iron"),12));}
    @Test void eachAlternativeGoalObservesTheAlreadyDepositedStock(){ledger.credit("oak",5);assertEquals(0,ledger.need(List.of("oak"),5));assertEquals(0,ledger.need(List.of("oak","birch"),5));}
    @Test void malformedOrUnboundedGoalsAreRejected(){assertThrows(Json.Rejected.class,()->ledger.need(List.of(),1));assertThrows(Json.Rejected.class,()->ledger.need(List.of("iron"),4097));assertThrows(Json.Rejected.class,()->ledger.credit("iron",0));assertThrows(Json.Rejected.class,()->ledger.credit("iron",100));}
    @Test void aFreshOriginalTaskCannotInheritAnotherTasksDeposits(){ledger.credit("iron",12);assertEquals(12,new StorageLedger<String>().need(List.of("iron"),12));}
}
