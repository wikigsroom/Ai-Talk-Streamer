package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import org.junit.jupiter.api.Test;
import static dev.aitalkstreamer.mc.neoforge.NativeSmeltPlan.*;
import static org.junit.jupiter.api.Assertions.*;

class NativeSmeltPlanTest {
    List<Stock> stock(Stock... items){var rows=new ArrayList<>(Collections.nCopies(36,new Stock(0,false,0)));for(int i=0;i<items.length;i++)rows.set(i,items[i]);return rows;}
    Plan plan(List<Stock> rows,int count){return allocate(rows,200,1,64,"minecraft:charcoal",7,count);}
    @Test void fuelDurationSplitsAConversionIntoFiniteBatches(){var p=plan(stock(new Stock(4,true,0),new Stock(4,false,300)),4);assertEquals(4,p.batches().size());assertEquals(4,p.requiredFrom(0)[0]);assertEquals(4,p.requiredFrom(0)[1]);}
    @Test void oneLongFuelSupportsFourInputsWithoutDiscardingItsResidualHeat(){var p=plan(stock(new Stock(4,true,0),new Stock(1,false,1600)),4);assertEquals(1,p.batches().size());assertEquals(4,p.batches().getFirst().inputs());}
    @Test void inputThatAlsoBurnsCannotConsumeAReservedRawUnit(){assertThrows(RuntimeException.class,()->plan(stock(new Stock(2,true,300)),2));}
    @Test void sameRawAndFuelStackReservesBothUnits(){var p=plan(stock(new Stock(2,true,300)),1);assertEquals(2,p.requiredFrom(0)[0]);assertEquals(p.batches().getFirst().rawSlot(),p.batches().getFirst().fuelSlot());}
    @Test void separateFuelPreservesScarceRawInputs(){var p=plan(stock(new Stock(2,true,300),new Stock(2,false,300)),2);assertEquals(2,p.requiredFrom(0)[0]);assertEquals(2,p.requiredFrom(0)[1]);}
    @Test void rawSurplusCanFuelAnotherComponentStackWithoutDoubleCounting(){var p=plan(stock(new Stock(1,true,300),new Stock(2,true,300)),1);assertEquals(2,Arrays.stream(p.requiredFrom(0)).sum());}
    @Test void fewerRawUnitsThanRequestedRejectsTheEntirePlan(){assertThrows(RuntimeException.class,()->plan(stock(new Stock(1,true,0),new Stock(10,false,1600)),2));}
    @Test void requestedIncrementRoundsToTheActualPerInputOutput(){var p=allocate(stock(new Stock(2,true,0),new Stock(1,false,1600)),200,4,64,"minecraft:test",5,5);assertEquals(2,p.target().batches());assertEquals(13,p.target().targetTotal());}
    @Test void outputStackLimitBoundsEachConversionBatch(){var p=allocate(stock(new Stock(3,true,0),new Stock(3,false,1600)),200,2,4,"minecraft:test",0,6);assertEquals(2,p.batches().size());assertEquals(2,p.batches().getFirst().inputs());}
    @Test void reservationsExcludeOnlyAlreadyFinishedBatches(){var p=plan(stock(new Stock(3,true,0),new Stock(3,false,300)),3);assertEquals(2,p.requiredFrom(1)[0]);assertEquals(2,p.requiredFrom(1)[1]);assertEquals(0,Arrays.stream(p.requiredFrom(3)).sum());}
    @Test void actualSlowRecipesRespectBothBatchAndWholeTaskDeadlines(){var p=allocate(stock(new Stock(2,true,0),new Stock(2,false,1600)),1200,1,64,"minecraft:test",0,2);assertEquals(2,p.batches().size());assertTrue(p.budgetMillis()<=MAX_TOTAL_MS);assertThrows(RuntimeException.class,()->allocate(stock(new Stock(5,true,0),new Stock(5,false,1600)),1200,1,64,"minecraft:test",0,5));}
    @Test void zeroFuelOrUnsupportedCookingDurationCannotAuthorizeClicks(){assertThrows(RuntimeException.class,()->plan(stock(new Stock(1,true,0)),1));assertThrows(RuntimeException.class,()->allocate(stock(new Stock(1,true,0)),1201,1,64,"minecraft:test",0,1));}
    @Test void sourceStockAndBatchListRemainImmutable(){var rows=stock(new Stock(1,true,0),new Stock(1,false,300));var p=plan(rows,1);rows.clear();assertEquals(1,p.batches().size());assertThrows(UnsupportedOperationException.class,()->p.batches().clear());}
}
