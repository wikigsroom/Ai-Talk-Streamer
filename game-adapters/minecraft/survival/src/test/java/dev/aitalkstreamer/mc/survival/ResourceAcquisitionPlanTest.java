package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.survival.ResourceAcquisitionPlan.*;

class ResourceAcquisitionPlanTest {
    final ResourceAcquisitionPlan plan=new ResourceAcquisitionPlan();
    final Source oak=new Source(Kind.ITEM,"oak",Set.of("oak","birch"));
    final Source birch=new Source(Kind.ITEM,"birch",Set.of("oak","birch"));
    List<ResourceMaterialsPlan.Stock> stock(String item,int count) {return List.of(new ResourceMaterialsPlan.Stock(0,item,count));}
    final List<ResourceMaterialsPlan.Stock> empty=List.of();
    void begin(Object owner,Source source,List<ResourceMaterialsPlan.Stock> stock) {plan.begin(owner,source,stock,stock,ancestor->false);}
    Choice choose(List<Source> sources,List<ResourceMaterialsPlan.Stock> stock) {return plan.choose(new Object(),sources,stock,ancestor->false);}
    @Test void preservesDeterministicPreferenceAndDeduplicatesSources() {assertEquals(oak,choose(List.of(oak,oak,birch),empty).source());}
    @Test void unchangedActualAncestorBlocksTheRepeatedSource() {begin(new Object(),oak,empty);var c=plan.choose(new Object(),List.of(oak),empty,a->true);assertNull(c.source());assertTrue(c.blockedByCycle());assertFalse(c.blockedByFailure());}
    @Test void canChooseAnAlternativeAfterAnAncestorCycle() {begin(new Object(),oak,empty);var c=plan.choose(new Object(),List.of(oak,birch),empty,a->true);assertEquals(birch,c.source());assertTrue(c.blockedByCycle());}
    @Test void unrelatedBranchesDoNotCreateCycles() {begin(new Object(),oak,empty);assertEquals(oak,choose(List.of(oak),empty).source());}
    @Test void differentSourcesRemainAvailableOnTheSameAncestorPath() {begin(new Object(),oak,empty);assertEquals(birch,plan.choose(new Object(),List.of(birch),empty,a->true).source());}
    @Test void usefulInventoryProgressAllowsARepeatedAncestorSource() {begin(new Object(),oak,empty);assertEquals(oak,plan.choose(new Object(),List.of(oak),stock("pickaxe",1),a->true).source());}
    @Test void movingSlotsDoesNotInventProgressOrBreakACycle() {var before=stock("oak",1);begin(new Object(),oak,before);var moved=List.of(new ResourceMaterialsPlan.Stock(8,"oak",1));assertTrue(plan.choose(new Object(),List.of(oak),moved,a->true).blockedByCycle());}
    @Test void repeatedTicksRetainTheOriginalCycleContext() {var owner=new Object();begin(owner,oak,empty);plan.begin(owner,oak,empty,stock("pickaxe",1),a->false);assertTrue(plan.choose(new Object(),List.of(oak),empty,a->true).blockedByCycle());}
    @Test void anActiveOwnerCannotChangeItsSourceOrBaseline() {var owner=new Object();begin(owner,oak,empty);assertThrows(RuntimeException.class,()->plan.begin(owner,birch,empty,empty,a->false));assertThrows(RuntimeException.class,()->plan.begin(owner,oak,stock("oak",1),empty,a->false));}
    @Test void beginAlsoRejectsAnActualUnchangedAncestorCycle() {begin(new Object(),oak,empty);var error=assertThrows(dev.aitalkstreamer.mc.core.Json.Rejected.class,()->plan.begin(new Object(),oak,empty,empty,a->true));assertEquals("GAME_RESOURCE_MATERIAL_CYCLE",error.code);}
    @Test void targetMaterialGainCountsAsProgress() {var owner=new Object();begin(owner,oak,empty);assertTrue(plan.finish(owner,stock("oak",1)));assertEquals(oak,choose(List.of(oak),empty).source());}
    @Test void unrelatedInventoryGainDoesNotCountAsMaterialProgress() {var owner=new Object();begin(owner,oak,empty);assertFalse(plan.finish(owner,stock("food",1)));assertTrue(choose(List.of(oak),stock("food",1)).blockedByFailure());}
    @Test void materialConsumptionDoesNotCountAsProgress() {var owner=new Object();begin(owner,oak,stock("oak",2));assertFalse(plan.finish(owner,stock("oak",1)));}
    @Test void aBroadFactoryMayProduceAnotherAcceptedMaterial() {var owner=new Object();begin(owner,oak,empty);assertTrue(plan.finish(owner,stock("birch",1)));}
    @Test void exhaustedSourceIsSkippedInFavorOfAnotherSource() {var owner=new Object();begin(owner,oak,empty);plan.finish(owner,empty);var c=choose(List.of(oak,birch),empty);assertEquals(birch,c.source());assertTrue(c.blockedByFailure());}
    @Test void foodConsumptionCachesBothPreAndPostFailureStock() {var owner=new Object();var food=stock("food",1);begin(owner,oak,food);assertFalse(plan.finish(owner,empty));assertNull(choose(List.of(oak),food).source());assertNull(choose(List.of(oak),empty).source());}
    @Test void changedStockPermitsReplanningAFailedSource() {var owner=new Object();begin(owner,oak,empty);plan.finish(owner,empty);assertEquals(oak,choose(List.of(oak),stock("pickaxe",1)).source());}
    @Test void releasingOneOwnerPreservesOtherClaims() {var a=new Object();var b=new Object();begin(a,oak,empty);begin(b,birch,empty);plan.release(a);assertEquals(oak,plan.choose(new Object(),List.of(oak),empty,v->true).source());assertTrue(plan.choose(new Object(),List.of(birch),empty,v->true).blockedByCycle());}
    @Test void interruptionsDoNotEraseFailureHistory() {var owner=new Object();begin(owner,oak,empty);plan.finish(owner,empty);plan.release(owner);plan.release(owner);assertTrue(choose(List.of(oak),empty).blockedByFailure());}
    @Test void equalOwnersAreStillDistinctTaskIdentities() {Object a=new String("same"),b=new String("same");begin(a,oak,empty);begin(b,birch,empty);plan.release(a);assertTrue(plan.choose(new Object(),List.of(birch),empty,v->true).blockedByCycle());}
    @Test void activeDepthIsBoundedAndReleaseRestoresCapacity() {var owners=new ArrayList<Object>();for(int i=0;i<MAX_ACTIVE;i++){var owner=new Object();owners.add(owner);begin(owner,oak,empty);}assertThrows(RuntimeException.class,()->begin(new Object(),oak,empty));plan.release(owners.getFirst());begin(new Object(),oak,empty);}
    @Test void rememberedFailureFingerprintsHaveABoundedCapacity() {for(int i=0;i<MAX_FAILURES;i++){var source=new Source(Kind.CATALOGUE,"source"+i,Set.of("oak"));var owner=new Object();begin(owner,source,empty);assertFalse(plan.finish(owner,empty));}var owner=new Object();begin(owner,birch,empty);assertThrows(RuntimeException.class,()->plan.finish(owner,empty));}
    @Test void sourceOptionsAndInventorySnapshotsAreDefensive() {var options=new HashSet<>(Set.of("oak"));var source=new Source(Kind.ITEM,"oak",options);options.clear();assertEquals(Set.of("oak"),source.items());var stock=new ArrayList<>(stock("oak",1));var owner=new Object();begin(owner,source,stock);stock.clear();assertFalse(plan.finish(owner,stock("oak",1)));assertThrows(UnsupportedOperationException.class,()->source.items().clear());}
    @Test void invalidSourcesDuplicateSlotsAndUnboundedChoicesAreRejected() {assertThrows(RuntimeException.class,()->new Source(Kind.ITEM,"stone",Set.of("oak")));assertThrows(RuntimeException.class,()->new Source(Kind.CATALOGUE,"",Set.of("oak")));assertThrows(RuntimeException.class,()->choose(Collections.nCopies(MAX_SOURCES+1,oak),empty));assertThrows(RuntimeException.class,()->choose(List.of(oak),List.of(new ResourceMaterialsPlan.Stock(0,"oak",1),new ResourceMaterialsPlan.Stock(0,"birch",1))));}
    @Test void successfulRecoveryClearsTheSameSourcesOldFailures() {var owner=new Object();begin(owner,oak,empty);plan.finish(owner,empty);begin(owner,oak,stock("oak",1));assertTrue(plan.finish(owner,stock("oak",2)));assertEquals(oak,choose(List.of(oak),empty).source());}
    @Test void rootCleanupAndANewRootHaveIndependentState() {var owner=new Object();begin(owner,oak,empty);plan.finish(owner,empty);begin(new Object(),birch,empty);plan.clear();assertEquals(oak,choose(List.of(oak),empty).source());assertFalse(plan.choose(new Object(),List.of(birch),empty,v->true).blockedByCycle());assertEquals(oak,new ResourceAcquisitionPlan().choose(new Object(),List.of(oak),empty,v->true).source());}
}
