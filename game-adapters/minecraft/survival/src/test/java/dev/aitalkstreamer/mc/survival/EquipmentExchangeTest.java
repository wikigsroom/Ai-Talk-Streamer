package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.concurrent.atomic.*;
import dev.aitalkstreamer.mc.core.InventoryExchange.State;
import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import dev.aitalkstreamer.mc.core.Json;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Pending clicks, authoritative full states, original deadlines and revocation. No real game. */
class EquipmentExchangeTest {
    final AtomicLong now=new AtomicLong();final AtomicBoolean owner=new AtomicBoolean(true);
    final EquipmentPlanTest fixture=new EquipmentPlanTest();final State before=fixture.inventory().slot(5,new Stack(4,1));
    State local=before;int revision=10;final List<EquipmentPlan.Step> clicks=new ArrayList<>();EquipmentExchange exchange;
    void start(List<EquipmentPlan.Step> plan){exchange=new EquipmentExchange(before,plan,now::get,owner::get);}
    boolean advance(){return exchange.advance(local,revision,step->{assertEquals(-1,exchange.revision(revision));clicks.add(step);local=step.after();});}
    void ack(){exchange.confirm(local,++revision);}
    @Test void aFullBaselineMustArriveBeforeTheFirstTransfer(){
        start(EquipmentPlan.main(before,9,36));assertFalse(advance());assertEquals(before,local);assertEquals(0,clicks.getFirst().slot());
        assertFalse(advance());assertEquals(1,clicks.size());ack();assertFalse(advance());assertEquals(2,clicks.size());
    }
    @Test void selectingOrRefreshingWithoutAMoveStillWaitsForTheAuthoritativeBaseline(){
        start(List.of());assertFalse(advance());assertEquals(before,local);ack();assertTrue(advance());assertEquals(1,clicks.size());
    }
    @Test void mainHandCompletionRequiresTheSwapServerAckAndExactActualState(){
        start(EquipmentPlan.main(before,9,36));advance();ack();advance();assertFalse(advance());ack();assertTrue(advance());assertEquals(before.swap(9,36),local);
    }
    @Test void armorClicksAreStrictlySerialAndRetainTheirCursorThroughEachAck(){
        start(EquipmentPlan.armor(before,9,5));advance();
        for(int i=0;i<3;i++){ack();assertFalse(advance());assertEquals(i+2,clicks.size());assertFalse(advance());}
        ack();assertTrue(advance());assertEquals(before.swap(9,5),local);assertEquals(Stack.EMPTY,local.cursor());
    }
    @Test void unrelatedServerChangesDoNotAuthorizeASecondClick(){
        start(EquipmentPlan.main(before,9,36));advance();exchange.confirm(local.slot(12,new Stack(8,1)),++revision);
        assertThrows(Json.Rejected.class,this::advance);assertEquals(1,clicks.size());
    }
    @Test void clientPredictionWithoutAFullPacketCannotFinishTheSwap(){
        start(EquipmentPlan.main(before,9,36));advance();ack();advance();assertEquals(before.swap(9,36),local);
        for(int i=0;i<5;i++)assertFalse(advance());assertEquals(2,clicks.size());
    }
    @Test void anExpiredClickCannotBeRescuedOrRepeatedByLatePackets(){
        start(EquipmentPlan.main(before,9,36));advance();now.set(1500);ack();assertThrows(Json.Rejected.class,this::advance);assertEquals(1,clicks.size());
    }
    @Test void waitingAfterAnAckDoesNotResetTheOriginalEightSecondLimit(){
        start(EquipmentPlan.main(before,9,36));advance();now.set(100);ack();now.set(7900);advance();
        now.set(8000);ack();assertThrows(LocalTaskFailure.class,this::advance);assertEquals(2,clicks.size());
    }
    @Test void revokedOwnershipRejectsLateAcksWithoutAnyInventoryRollback(){
        start(EquipmentPlan.armor(before,9,5));advance();ack();advance();var predicted=local;owner.set(false);ack();
        assertThrows(Json.Rejected.class,this::advance);assertEquals(predicted,local);assertEquals(2,clicks.size());
    }
    @Test void closingWithArmorOnTheCursorSendsNoReturnClick(){
        start(EquipmentPlan.armor(before,9,5));advance();ack();advance();var predicted=local;exchange.close();ack();
        assertThrows(Json.Rejected.class,this::advance);assertEquals(predicted,local);assertEquals(2,clicks.size());
    }
    @Test void aMissingNativeRevisionHookFailsInsteadOfPretendingTheClickWasSent(){
        start(List.of());assertThrows(Json.Rejected.class,()->exchange.advance(before,10,step->{}));assertThrows(Json.Rejected.class,this::advance);
    }
    @Test void packetsFromAnotherThreadCannotConfirmTheOwnersInventory()throws Exception{
        start(List.of());advance();var error=new AtomicReference<Throwable>();var thread=new Thread(()->{try{exchange.confirm(local,11);}catch(Throwable e){error.set(e);}});
        thread.start();thread.join();assertInstanceOf(Json.Rejected.class,error.get());assertFalse(advance());
    }
}
