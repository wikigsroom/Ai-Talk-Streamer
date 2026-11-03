package dev.aitalkstreamer.mc.survival;

import java.util.*;
import dev.aitalkstreamer.mc.core.InventoryExchange.State;
import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import dev.aitalkstreamer.mc.core.Json;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Real transfer plans, with explicit component tokens rather than a running Minecraft client. */
class EquipmentPlanTest {
    State inventory(){var slots=new ArrayList<Stack>(Collections.nCopies(46,Stack.EMPTY));slots.set(9,new Stack(1,1));slots.set(36,new Stack(2,64));return new State(slots,Stack.EMPTY);}
    @Test void mainHandSwapPreservesBothExactStacksAndDoesNotTouchOtherSlots(){
        var before=inventory().slot(45,new Stack(4,1));var step=EquipmentPlan.main(before,9,36).getFirst();
        assertEquals(before.swap(9,36),step.after());assertEquals(0,step.button());assertEquals(EquipmentPlan.Action.SWAP,step.action());
    }
    @Test void aHotbarStackCanBeSelectedWithoutMovingAnyInventory(){assertTrue(EquipmentPlan.main(inventory(),36,36).isEmpty());}
    @Test void offhandSwapUsesTheVanillaOffhandButtonAndPreservesItsPreviousItem(){
        var before=inventory().slot(45,new Stack(7,1));var step=EquipmentPlan.offhand(before,9).getFirst();
        assertEquals(40,step.button());assertEquals(before.swap(9,45),step.after());
    }
    @Test void replacingArmorReturnsTheOldPieceToTheExactOriginalInventorySlot(){
        var before=inventory().slot(6,new Stack(3,1));var steps=EquipmentPlan.armor(before,9,6);
        assertEquals(3,steps.size());assertEquals(before.swap(9,6),steps.getLast().after());
        assertEquals(new Stack(1,1),steps.getFirst().after().cursor());assertEquals(new Stack(3,1),steps.get(1).after().cursor());
        assertEquals(Stack.EMPTY,steps.getLast().after().cursor());
    }
    @Test void initiallyEmptyArmorNeedsOnlyTwoClicksAndLeavesNoCursorResidue(){
        var before=inventory();var steps=EquipmentPlan.armor(before,9,5);assertEquals(2,steps.size());assertEquals(before.swap(9,5),steps.getLast().after());
    }
    @Test void armorWithDifferentComponentsIsSwappedWithoutLosingEitherIdentity(){
        var before=inventory().slot(5,new Stack(8,1));assertEquals(before.swap(9,5),EquipmentPlan.armor(before,9,5).getLast().after());
    }
    @Test void aFullInventoryStillPreservesTheDisplacedArmorWithoutDropping(){
        var before=inventory().slot(7,new Stack(8,1));for(int i=10;i<=44;i++)before=before.slot(i,new Stack(9,64));
        assertEquals(before.swap(9,7),EquipmentPlan.armor(before,9,7).getLast().after());
    }
    @Test void occupiedCraftingOrCursorStateIsRejectedBeforeAnyMove(){
        assertThrows(Json.Rejected.class,()->EquipmentPlan.main(inventory().slot(0,new Stack(5,1)),9,36));
        assertThrows(Json.Rejected.class,()->EquipmentPlan.armor(new State(inventory().slots(),new Stack(3,1)),9,5));
    }
    @Test void armorNeverSplitsAMultiItemStackOrUsesAnInvalidEquipmentDestination(){
        assertThrows(Json.Rejected.class,()->EquipmentPlan.armor(inventory().slot(9,new Stack(1,2)),9,5));
        assertThrows(Json.Rejected.class,()->EquipmentPlan.armor(inventory(),9,45));
    }
    @Test void undefinedCursorAndContainerSlotsCannotBecomeEquipmentSources(){
        for(int slot:List.of(-999,-1,0,4,5,45,46))assertThrows(Json.Rejected.class,()->EquipmentPlan.main(inventory(),slot,36));
    }
}
