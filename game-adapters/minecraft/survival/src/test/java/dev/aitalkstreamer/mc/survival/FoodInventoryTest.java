package dev.aitalkstreamer.mc.survival;

import java.util.*;
import java.util.stream.IntStream;
import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import dev.aitalkstreamer.mc.core.InventoryExchange.State;
import dev.aitalkstreamer.mc.core.Json;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Exact vanilla inventory outcomes, without a Minecraft client or synthetic effect proof. */
class FoodInventoryTest {
    final List<Integer> main = IntStream.range(0,36).map(i -> i < 9 ? i+36 : i).boxed().toList();
    final Stack bowl = new Stack(2,1);
    State state(int count) {
        var slots=new ArrayList<Stack>(Collections.nCopies(46,Stack.EMPTY)); slots.set(36,new Stack(1,count));
        slots.set(5,new Stack(4,1)); return new State(slots,Stack.EMPTY);
    }
    State consume(State state, Stack remainder) { return FoodInventory.consumed(state,36,remainder,64,main,45); }
    @Test void lastFoodDisappearsAndEveryUnrelatedSlotIsPreserved() {
        var before=state(1).slot(10,new Stack(7,12));var after=consume(before,Stack.EMPTY);
        assertEquals(before.slot(36,Stack.EMPTY),after);assertEquals(before.slot(36,Stack.EMPTY).slots(),after.slots());
    }
    @Test void oneFoodReturnsItsBowlInTheSameHandEvenWhenTheInventoryIsFull() {
        var before=full(state(1));assertEquals(before.slot(36,bowl),consume(before,bowl));
    }
    @Test void aStackConsumesOnlyOneAndLeavesAllComponentsEncodedByTheToken() {
        var before=state(8);assertEquals(before.slot(36,new Stack(1,7)),consume(before,Stack.EMPTY));
    }
    @Test void remainderMergesIntoOffhandBeforeAnExistingMainInventoryStack() {
        var before=state(4).slot(45,new Stack(2,62)).slot(37,new Stack(2,4));
        assertEquals(before.slot(36,new Stack(1,3)).slot(45,new Stack(2,63)),consume(before,bowl));
    }
    @Test void aFullOffhandFallsThroughToTheFirstCompatiblePlayerInventoryStack() {
        var before=state(4).slot(45,new Stack(2,64)).slot(37,new Stack(2,4)).slot(9,new Stack(2,5));
        assertEquals(before.slot(36,new Stack(1,3)).slot(37,new Stack(2,5)),consume(before,bowl));
    }
    @Test void incompatibleComponentsDoNotMergeAndTheFirstEmptyHotbarSlotWins() {
        var before=state(3).slot(45,new Stack(3,1)).slot(37,new Stack(3,2));
        assertEquals(before.slot(36,new Stack(1,2)).slot(38,bowl),consume(before,bowl));
    }
    @Test void aStackedRemainderWithoutRoomIsRejectedBeforeAUseCanBeIssued() {
        var before=full(state(2));assertThrows(Json.Rejected.class,()->consume(before,bowl));
        assertEquals(new Stack(1,2),before.slots().get(36));
    }
    @Test void aRemainderCanFillTheOffhandThenAnEmptyInventorySlot() {
        var before=state(3).slot(45,new Stack(2,63));
        var after=FoodInventory.consumed(before,36,new Stack(2,2),64,main,45);
        assertEquals(before.slot(36,new Stack(1,2)).slot(45,new Stack(2,64)).slot(37,bowl),after);
    }
    @Test void bothZeroAndOneConsumptionRestoreTheExactOriginalHeldEquipment() {
        var before=state(1).slot(36,new Stack(8,1)).slot(10,new Stack(1,2));
        var equipped=before.swap(10,36);assertEquals(before,equipped.swap(10,36));
        var after=consume(equipped,bowl).swap(10,36);
        assertEquals(before.slot(10,new Stack(1,1)).slot(37,bowl),after);
    }
    @Test void occupiedCraftingGridOrCursorIsNotAnEatingTransaction() {
        assertThrows(Json.Rejected.class,()->consume(state(1).slot(0,bowl),Stack.EMPTY));
        assertThrows(Json.Rejected.class,()->consume(new State(state(1).slots(),bowl),Stack.EMPTY));
    }
    @Test void incorrectHandlerMappingOrSelfReplacingFoodCannotBeModeled() {
        assertThrows(Json.Rejected.class,()->FoodInventory.consumed(state(2),36,bowl,64,Collections.nCopies(36,36),45));
        assertThrows(Json.Rejected.class,()->consume(state(2),new Stack(1,1)));
    }
    State full(State before) { for(int i:main)if(i!=36)before=before.slot(i,new Stack(9,64));return before; }
}
