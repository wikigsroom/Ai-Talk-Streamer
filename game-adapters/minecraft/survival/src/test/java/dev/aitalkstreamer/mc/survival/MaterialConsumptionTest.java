package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

/** Component eligibility belongs to exact slot sets; retained public totals remain item based. */
class MaterialConsumptionTest {
    ResourceMaterialsPlan.Stock s(int slot,String item,int count) {return new ResourceMaterialsPlan.Stock(slot,item,count);}
    Map<String,Integer> pair(List<ResourceMaterialsPlan.Stock> stock,Map<String,Integer> holds,Set<Integer> raw,Set<Integer> fuel) {
        return ResourceMaterialsPlan.singleUnits(stock,holds,Map.of("raw",raw,"fuel",fuel));
    }
    @Test void aRetainedOrdinaryCoalCanMoveToNamedCoalSoTheOrdinaryOneCanBurn() {
        var selected=pair(List.of(s(0,"coal",1),s(1,"coal",1),s(2,"raw",1)),Map.of("coal",1),Set.of(2),Set.of(0));
        assertEquals(Map.of("raw",2,"fuel",0),selected);
    }
    @Test void theOnlyRawUnitCannotAlsoBeFuel() {assertTrue(pair(List.of(s(0,"log",1)),Map.of(),Set.of(0),Set.of(0)).isEmpty());}
    @Test void twoUnitsInOneStackCanServeBothRoles() {assertEquals(Map.of("raw",0,"fuel",0),pair(List.of(s(0,"log",2)),Map.of(),Set.of(0),Set.of(0)));}
    @Test void aRetainedThirdUnitDoesNotBecomeAnIngredient() {assertTrue(pair(List.of(s(0,"log",2)),Map.of("log",1),Set.of(0),Set.of(0)).isEmpty());}
    @Test void retainingOnlyOneOfThreeUnitsAllowsTheOtherTwo() {assertEquals(2,pair(List.of(s(0,"log",3)),Map.of("log",1),Set.of(0),Set.of(0)).size());}
    @Test void flexibleFuelIsReassignedToKeepTheOnlyExactRawStack() {
        var result=pair(List.of(s(0,"a",1),s(1,"b",1)),Map.of(),Set.of(0),Set.of(0,1));assertEquals(Map.of("raw",0,"fuel",1),result);
    }
    @Test void futureAbsentOutputDoesNotReserveUnrelatedStock() {assertEquals(2,pair(List.of(s(0,"raw",1),s(1,"coal",1)),Map.of("iron",4),Set.of(0),Set.of(1)).size());}
    @Test void excludedCustomFuelNeverAppearsInTheSelection() {assertTrue(pair(List.of(s(0,"raw",1),s(1,"coal",64)),Map.of(),Set.of(0),Set.of()).isEmpty());}
    @Test void missingOneConsumerDoesNotReturnAPartialPermission() {assertTrue(pair(List.of(s(0,"raw",1)),Map.of(),Set.of(0),Set.of(1)).isEmpty());}
    @Test void usableFoodCanMoveItsReservationToAnIneligibleEqualItemStack() {
        assertEquals(Map.of(0,2),ResourceMaterialsPlan.usable(List.of(s(0,"bread",2),s(1,"bread",2)),Map.of("bread",2),Set.of(0)));
    }
    @Test void usableQuantitiesRespectEveryRetainedItemKind() {
        assertEquals(Map.of(0,1,1,2),ResourceMaterialsPlan.usable(List.of(s(0,"bread",3),s(1,"potato",4)),Map.of("bread",2,"potato",2),Set.of(0,1)));
    }
    @Test void entirelyReservedFoodHasNoUsableUnits() {assertTrue(ResourceMaterialsPlan.usable(List.of(s(0,"bread",3)),Map.of("bread",5),Set.of(0)).isEmpty());}
    @Test void emptyCandidateSetProducesNoConsumableStock() {assertTrue(ResourceMaterialsPlan.usable(List.of(s(0,"bread",3)),Map.of(),Set.of()).isEmpty());}
    @Test void selectionIsImmutableAndDoesNotMutateStockOrDesiredTotals() {
        var stock=new ArrayList<>(List.of(s(0,"coal",2)));var desired=new HashMap<>(Map.of("coal",1));
        var selected=ResourceMaterialsPlan.singleUnits(stock,desired,Map.of("fuel",Set.of(0)));
        assertThrows(UnsupportedOperationException.class,selected::clear);assertEquals(2,stock.getFirst().count());assertEquals(Map.of("coal",1),desired);
        assertEquals(selected,ResourceMaterialsPlan.singleUnits(stock,desired,Map.of("fuel",Set.of(0))));
    }
    @Test void duplicateSlotsInvalidCandidatesAndUnboundedConsumersAreRejected() {
        assertThrows(RuntimeException.class,()->pair(List.of(s(0,"a",1),s(0,"a",1)),Map.of(),Set.of(0),Set.of(0)));
        assertThrows(RuntimeException.class,()->pair(List.of(),Map.of(),Set.of(36),Set.of(0)));
        assertThrows(RuntimeException.class,()->ResourceMaterialsPlan.singleUnits(List.of(),Map.of(),Map.of()));
        assertThrows(RuntimeException.class,()->ResourceMaterialsPlan.singleUnits(List.of(),Map.of(),Map.of(" ",Set.of())));
        var many=new HashMap<String,Set<Integer>>();for(int i=0;i<65;i++)many.put("c"+i,Set.of());
        assertThrows(RuntimeException.class,()->ResourceMaterialsPlan.singleUnits(List.of(),Map.of(),many));
    }
    private Set<Integer> mask(int bits) {var s=new HashSet<Integer>();for(int i=0;i<3;i++)if((bits&(1<<i))!=0)s.add(i);return s;}
    private boolean retains(int[] counts,int a,int b,int keepA,int keepB) {
        var rest=counts.clone();rest[a]--;rest[b]--;return Arrays.stream(rest).allMatch(n->n>=0) && rest[0]+rest[1]>=keepA && rest[2]>=keepB;
    }
    @Test void allSmallJointSelectionsMatchIndependentPhysicalUnitEnumeration() {
        for(int x=0;x<=2;x++)for(int y=0;y<=2;y++)for(int z=0;z<=2;z++)for(int r=0;r<8;r++)for(int f=0;f<8;f++)for(int ha=0;ha<=2;ha++)for(int hb=0;hb<=2;hb++) {
            int[] counts={x,y,z};var raw=mask(r);var fuel=mask(f);int ka=Math.min(ha,x+y),kb=Math.min(hb,z);boolean possible=false;
            for(int a:raw)for(int b:fuel)possible|=retains(counts,a,b,ka,kb);
            var result=pair(List.of(s(0,"a",x),s(1,"a",y),s(2,"b",z)),Map.of("a",ha,"b",hb),raw,fuel);
            assertEquals(possible,!result.isEmpty(),()->Arrays.toString(counts)+raw+fuel+ka+":"+kb);
            if(possible) {assertTrue(raw.contains(result.get("raw")));assertTrue(fuel.contains(result.get("fuel")));assertTrue(retains(counts,result.get("raw"),result.get("fuel"),ka,kb));}
        }
    }
    @Test void allSmallUsableCountsMatchIndependentMaximumEnumeration() {
        for(int x=0;x<=2;x++)for(int y=0;y<=2;y++)for(int z=0;z<=2;z++)for(int bits=0;bits<8;bits++)for(int ha=0;ha<=2;ha++)for(int hb=0;hb<=2;hb++) {
            var candidates=mask(bits);int best=0;
            for(int a=0;a<=x;a++)for(int b=0;b<=y;b++)for(int c=0;c<=z;c++) {
                if(a>0&&!candidates.contains(0)||b>0&&!candidates.contains(1)||c>0&&!candidates.contains(2))continue;
                if(x+y-a-b>=Math.min(ha,x+y) && z-c>=Math.min(hb,z))best=Math.max(best,a+b+c);
            }
            var chosen=ResourceMaterialsPlan.usable(List.of(s(0,"a",x),s(1,"a",y),s(2,"b",z)),Map.of("a",ha,"b",hb),candidates);
            assertEquals(best,chosen.values().stream().mapToInt(Integer::intValue).sum());assertTrue(candidates.containsAll(chosen.keySet()));
        }
    }
}
