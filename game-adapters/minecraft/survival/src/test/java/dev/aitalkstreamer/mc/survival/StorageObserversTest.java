package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class StorageObserversTest {
    final StorageObservers<String,Integer> observers=new StorageObservers<>();
    @Test void stashFiltersUseTheConfirmedOriginalPosition(){var ledger=new StorageLedger<String>();observers.watch(new Object(),pos->pos==7,ledger::credit);observers.confirmed(8,"iron",4);assertEquals(6,ledger.need(List.of("iron"),6));observers.confirmed(7,"iron",4);assertEquals(2,ledger.need(List.of("iron"),6));}
    @Test void stoppedOuterTasksCannotReceiveAnotherContainersLaterTransfer(){var owner=new Object();var ledger=new StorageLedger<String>();observers.watch(owner,pos->true,ledger::credit);observers.unwatch(owner);observers.confirmed(7,"iron",4);assertEquals(6,ledger.need(List.of("iron"),6));}
    @Test void resumingAnOuterTaskDoesNotDuplicateItsSubscription(){var owner=new Object();var ledger=new StorageLedger<String>();observers.watch(owner,pos->true,ledger::credit);observers.watch(owner,pos->true,ledger::credit);observers.confirmed(7,"iron",4);assertEquals(2,ledger.need(List.of("iron"),6));}
    @Test void rootCleanupRemovesAllCreditsBeforeTheNextTask(){var calls=new AtomicInteger();observers.watch(new Object(),pos->true,(item,n)->calls.addAndGet(n));observers.clear();observers.confirmed(7,"iron",4);assertEquals(0,calls.get());}
}
