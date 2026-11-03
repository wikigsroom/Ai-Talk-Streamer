package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import dev.aitalkstreamer.mc.core.Json;
import java.util.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Inventory protocol cases, without a Minecraft world or server. */
class StorageExchangeTest {
    final AtomicLong now=new AtomicLong();final AtomicBoolean owner=new AtomicBoolean(true);
    StorageExchange.State before=empty(63).slot(0,new Stack(1,8)),actual=before;
    StorageExchange exchange;int revision=10;final List<StorageExchange.Step> clicks=new ArrayList<>();
    static StorageExchange.State empty(int slots){return new StorageExchange.State(Collections.nCopies(slots,Stack.EMPTY),Stack.EMPTY);}
    void start(int amount){exchange=new StorageExchange(StorageExchange.plan(before,0,27,amount,64),now::get,owner::get);}
    boolean advance(){return exchange.advance(actual,revision,s->{assertEquals(-1,exchange.revision(revision));clicks.add(s);actual=s.after();});}
    void ack(){exchange.confirm(actual,++revision);}
    @Test void exactWholeStackWaitsForBothFullServerAcks(){start(8);assertFalse(advance());assertFalse(advance());assertEquals(1,clicks.size());ack();assertFalse(advance());assertFalse(advance());ack();assertTrue(advance());assertEquals(new Stack(1,8),actual.slots().get(27));assertEquals(Stack.EMPTY,actual.cursor());}
    @Test void partialPickupReturnsAllRemainingItemsBeforeCompletion(){start(3);while(!advance())ack();assertEquals(new Stack(1,5),actual.slots().get(0));assertEquals(new Stack(1,3),actual.slots().get(27));assertEquals(Stack.EMPTY,actual.cursor());assertEquals(5,clicks.size());}
    @Test void depositingAnExactSubsetKeepsExistingCompatibleDestinationItems(){var s=empty(90).slot(54,new Stack(3,64)).slot(12,new Stack(3,20));var steps=StorageExchange.plan(s,54,12,4,64);var last=steps.getLast().after();assertEquals(new Stack(3,60),last.slots().get(54));assertEquals(new Stack(3,24),last.slots().get(12));assertEquals(Stack.EMPTY,last.cursor());}
    @Test void allOrdinaryStackAmountsConserveEverySlotAndCursorAcrossBothDirections(){
        for(int size:List.of(63,90))for(boolean deposit:List.of(false,true))for(int count=1;count<=64;count++)for(int amount=1;amount<=count;amount++){
            int container=size-36,source=deposit?container:0,destination=deposit?1:container;
            var s=empty(size).slot(source,new Stack(1,count)).slot(destination,amount==64?Stack.EMPTY:new Stack(1,64-amount)).slot(5,new Stack(2,9));
            for(var step:StorageExchange.plan(s,source,destination,amount,64)) {
                assertEquals(s,step.before());var held=s.cursor();var slot=s.slots().get(step.slot());StorageExchange.State expected;
                if(held.equals(Stack.EMPTY))expected=s.slot(step.slot(),Stack.EMPTY).cursor(slot);
                else {
                    int moved=step.button()==1?1:Math.min(held.count(),64-slot.count());
                    var rest=held.count()==moved?Stack.EMPTY:new Stack(held.type(),held.count()-moved);
                    expected=s.slot(step.slot(),new Stack(held.type(),slot.count()+moved)).cursor(rest);
                }
                assertEquals(expected,step.after());s=expected;
            }
            assertEquals(new Stack(1,64),s.slots().get(destination));assertEquals(Stack.EMPTY,s.cursor());assertEquals(new Stack(2,9),s.slots().get(5));
            assertEquals(count-amount,s.slots().get(source).count());
        }
    }
    @Test void componentMismatchCannotMergeIntoAnotherStack(){assertThrows(Json.Rejected.class,()->StorageExchange.plan(before.slot(27,new Stack(2,1)),0,27,1,64));}
    @Test void fullDestinationDoesNotCreateAnyClicks(){assertThrows(Json.Rejected.class,()->StorageExchange.plan(before.slot(27,new Stack(1,64)),0,27,1,64));}
    @Test void containerToContainerAndPlayerToPlayerAreRejected(){assertThrows(Json.Rejected.class,()->StorageExchange.plan(before,0,1,1,64));assertThrows(Json.Rejected.class,()->StorageExchange.plan(before.slot(27,new Stack(1,2)),27,28,1,64));}
    @Test void aBusyCursorCannotStartAMove(){assertThrows(Json.Rejected.class,()->StorageExchange.plan(before.cursor(new Stack(2,1)),0,27,1,64));}
    @Test void emptySourceOrOversizedAmountIsRejected(){assertThrows(Json.Rejected.class,()->StorageExchange.plan(before,1,27,1,64));assertThrows(Json.Rejected.class,()->StorageExchange.plan(before,0,27,9,64));assertThrows(Json.Rejected.class,()->StorageExchange.plan(before,0,27,0,64));}
    @Test void arbitraryScreensCannotBorrowTheOrdinaryStorageProtocol(){for(int size:List.of(0,39,46,64,89,91))assertThrows(Json.Rejected.class,()->empty(size));}
    @Test void singleFullPacketCannotConfirmMoreThanOneClick(){start(8);advance();ack();advance();assertFalse(advance());assertEquals(2,clicks.size());now.set(1500);assertThrows(Json.Rejected.class,this::advance);}
    @Test void localPredictionAloneNeverCompletes(){start(8);advance();for(int i=0;i<10;i++)assertFalse(advance());assertEquals(1,clicks.size());}
    @Test void sameOrOlderRevisionCannotConfirmTheClick(){start(8);advance();exchange.confirm(actual,revision);exchange.confirm(actual,revision-1);assertFalse(advance());assertEquals(1,clicks.size());ack();advance();assertEquals(2,clicks.size());}
    @Test void revisionWrapIsAcceptedOnlyWhenItMovesForward(){revision=32767;start(8);advance();revision=0;exchange.confirm(actual,revision);advance();assertEquals(2,clicks.size());}
    @Test void unrelatedServerSlotChangesStopTheTransaction(){start(8);advance();exchange.confirm(actual.slot(20,new Stack(7,1)),++revision);assertThrows(Json.Rejected.class,this::advance);assertEquals(1,clicks.size());}
    @Test void unexpectedCursorContentsAreNotCountedAsProgress(){start(8);advance();exchange.confirm(actual.cursor(new Stack(2,8)),++revision);assertThrows(Json.Rejected.class,this::advance);}
    @Test void aDifferentSizedContainerPacketCannotConfirmTheOriginal(){start(8);advance();exchange.confirm(empty(90).cursor(new Stack(1,8)),++revision);assertThrows(Json.Rejected.class,this::advance);}
    @Test void changingLocalInventoryAfterAnAckBlocksTheNextClick(){start(8);advance();ack();actual=actual.slot(30,new Stack(2,1));assertThrows(Json.Rejected.class,this::advance);assertEquals(1,clicks.size());}
    @Test void latePacketsCannotRenewTheClickDeadline(){start(8);advance();now.set(1500);ack();assertThrows(Json.Rejected.class,this::advance);assertEquals(1,clicks.size());}
    @Test void intermediateAcksNeverExtendTheOriginalTransferDeadline(){start(7);advance();for(int i=0;i<8;i++){now.addAndGet(1400);ack();advance();}now.set(12000);ack();assertThrows(Json.Rejected.class,this::advance);}
    @Test void missingResyncHookFailsBeforeAnyNextClick(){start(8);assertThrows(Json.Rejected.class,()->exchange.advance(actual,revision,s->{}));assertThrows(Json.Rejected.class,this::advance);}
    @Test void aHookCannotBeInvokedOutsideTheControlledClick(){start(8);assertThrows(Json.Rejected.class,()->exchange.revision(10));}
    @Test void revokedOwnershipDiscardsLateConfirmationWithoutRestoringInventory(){start(3);advance();var held=actual;owner.set(false);ack();assertThrows(Json.Rejected.class,this::advance);assertEquals(held,actual);assertEquals(1,clicks.size());}
    @Test void closingAnUncertainMoveNeverAddsReturnOrDropClicks(){start(3);advance();var held=actual;exchange.close();ack();assertThrows(Json.Rejected.class,this::advance);assertEquals(held,actual);assertEquals(1,clicks.size());}
    @Test void theFirstClickIsTheSourceAndNeverAnAssumedEmptyContainerSlot(){before=before.slot(1,new Stack(4,5));actual=before;start(3);advance();assertEquals(0,clicks.getFirst().slot());assertEquals(new Stack(4,5),actual.slots().get(1));}
    @Test void synchronousCallbacksCannotConfirmBeforeTheNativeClickReturns(){start(8);exchange.advance(actual,revision,s->{exchange.revision(revision);actual=s.after();exchange.confirm(actual,11);});assertFalse(advance());assertEquals(0,clicks.size());}
    @Test void foreignThreadsCannotSubmitServerPackets()throws Exception{start(8);advance();var error=new AtomicReference<Throwable>();var t=new Thread(()->{try{exchange.confirm(actual,11);}catch(Throwable e){error.set(e);}});t.start();t.join();assertInstanceOf(Json.Rejected.class,error.get());assertFalse(advance());}
}
