package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.survival.ResourceAcquisitionPlan.*;

class ResourceBranchRecoveryTest {
    final ResourceAcquisitionPlan plan=new ResourceAcquisitionPlan();
    final Source oak=new Source(Kind.ITEM,"oak",Set.of("oak","birch")),birch=new Source(Kind.ITEM,"birch",Set.of("oak","birch"));
    final String exhausted="GAME_RESOURCE_MATERIAL_UNAVAILABLE";
    List<ResourceMaterialsPlan.Stock> stock(String item,int count) {return List.of(new ResourceMaterialsPlan.Stock(0,item,count));}
    void begin(Object owner,Source source,List<ResourceMaterialsPlan.Stock> stock) {plan.begin(owner,source,stock,stock,a->false);}
    Choice choose(List<Source> sources,List<ResourceMaterialsPlan.Stock> stock) {return plan.choose(new Object(),sources,stock,a->false);}
    @Test void onlyFixedPlanningAndSourceFailuresQualify() {
        for(String reason:List.of(exhausted,"GAME_RESOURCE_MATERIAL_CYCLE","GAME_RESOURCE_MATERIAL_NO_PROGRESS","GAME_RESOURCE_MATERIAL_UNCATALOGUED","GAME_RESOURCE_CRAFT_MATERIALS_UNAVAILABLE","GAME_CRAFT_RECIPE_UNAVAILABLE","GAME_CRAFT_RECIPE_AMBIGUOUS","GAME_CRAFT_MATERIALS_MISSING","GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE","GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED"))assertTrue(ResourceBranchRecovery.recoverable(reason),reason);
        for(String reason:List.of("GAME_CRAFT_SERVER_TIMEOUT","GAME_CRAFT_SERVER_DIVERGED","GAME_COOKING_STATE_CHANGED","GAME_RESOURCE_CRAFT_CONTEXT_CHANGED","GAME_RESOURCE_MATERIAL_SELECTION_LIMIT","GAME_MATERIAL_ALLOCATION_LIMIT","GAME_EXECUTOR_REVOKED","GAME_RESOURCE_MATERIAL_UNAVAILABLE private",""))assertFalse(ResourceBranchRecovery.recoverable(reason),reason);
        assertFalse(ResourceBranchRecovery.recoverable(null));
    }
    @Test void explicitSourceFailureSkipsToTheNextSourceAndRetainsTheCause() {
        var owner=new Object();begin(owner,oak,List.of());plan.failed(owner,List.of(),exhausted);
        assertEquals(birch,choose(List.of(oak,birch),List.of()).source());assertEquals(exhausted,plan.failures().getFirst().reason());
    }
    @Test void recoveryRemembersBothPreAndPostConsumptionFingerprints() {
        var owner=new Object();begin(owner,oak,stock("food",1));plan.failed(owner,List.of(),exhausted);
        assertNull(choose(List.of(oak),stock("food",1)).source());assertNull(choose(List.of(oak),List.of()).source());assertEquals(2,plan.failures().size());
    }
    @Test void partialMaterialGainDoesNotReclassifyAnExceptionalBranchAsSuccess() {
        var owner=new Object();begin(owner,oak,List.of());plan.failed(owner,stock("oak",2),exhausted);
        assertTrue(choose(List.of(oak),stock("oak",2)).blockedByFailure());assertEquals(2,plan.failures().size());
    }
    @Test void nestedFailedSubtreesCanBacktrackThroughMoreThanOneCollector() {
        var parent=new Object();var child=new Object();begin(parent,oak,List.of());plan.begin(child,birch,List.of(),List.of(),a->a==parent);
        plan.failed(child,List.of(),"GAME_RESOURCE_MATERIAL_CYCLE");plan.failed(parent,List.of(),"GAME_RESOURCE_MATERIAL_NO_PROGRESS");
        var third=new Source(Kind.CATALOGUE,"wood",Set.of("oak","birch"));assertEquals(third,choose(List.of(oak,birch,third),List.of()).source());assertEquals(2,plan.failures().size());
    }
    @Test void failedChildReleaseDoesNotReleaseAnotherActiveAncestor() {
        var parent=new Object();var child=new Object();begin(parent,oak,List.of());begin(child,birch,List.of());plan.failed(child,List.of(),exhausted);
        assertTrue(plan.choose(new Object(),List.of(oak),List.of(),a->a==parent).blockedByCycle());
        assertFalse(plan.choose(new Object(),List.of(birch),List.of(),a->true).blockedByCycle());
    }
    @Test void unsafeReasonsCannotMutateTheActiveClaimOrFailureHistory() {
        var owner=new Object();begin(owner,oak,List.of());assertThrows(RuntimeException.class,()->plan.failed(owner,List.of(),"GAME_CRAFT_SERVER_TIMEOUT"));
        assertTrue(plan.failures().isEmpty());assertTrue(plan.finish(owner,stock("oak",1)));
    }
    @Test void failureWithoutAnActiveSourceCannotInventHistory() {
        assertThrows(RuntimeException.class,()->plan.failed(new Object(),List.of(),exhausted));assertTrue(plan.failures().isEmpty());
    }
    @Test void failureCapacityIsCheckedBeforeCommittingEitherFingerprint() {
        for(int i=0;i<MAX_FAILURES;i++) {var owner=new Object();begin(owner,new Source(Kind.CATALOGUE,"s"+i,Set.of("oak")),List.of());plan.failed(owner,List.of(),exhausted);}
        var owner=new Object();begin(owner,birch,List.of());assertThrows(RuntimeException.class,()->plan.failed(owner,stock("food",1),exhausted));
        assertEquals(MAX_FAILURES,plan.failures().size());assertTrue(plan.finish(owner,stock("birch",1)));
    }
    @Test void changedRealStockPermitsReplanningWithoutErasingOldFailureEvidence() {
        var owner=new Object();begin(owner,oak,List.of());plan.failed(owner,List.of(),exhausted);
        assertEquals(oak,choose(List.of(oak),stock("pickaxe",1)).source());assertEquals(1,plan.failures().size());
    }
    @Test void immutableFailureFactsCannotRewriteSourceStockOrReason() {
        var owner=new Object();begin(owner,oak,stock("food",1));plan.failed(owner,List.of(),exhausted);
        var facts=plan.failures();assertThrows(UnsupportedOperationException.class,()->facts.clear());assertThrows(UnsupportedOperationException.class,()->facts.getFirst().stock().clear());
        assertEquals(exhausted,plan.failures().getFirst().reason());
    }
    @Test void successfulLaterAcquisitionClearsOnlyThatSourcesFailures() {
        var first=new Object();begin(first,oak,List.of());plan.failed(first,List.of(),exhausted);
        var other=new Object();begin(other,birch,List.of());plan.failed(other,List.of(),exhausted);
        var retry=new Object();begin(retry,oak,stock("pickaxe",1));assertTrue(plan.finish(retry,stock("oak",2)));
        assertEquals(oak,choose(List.of(oak),List.of()).source());assertTrue(choose(List.of(birch),List.of()).blockedByFailure());
    }
    @Test void rootCleanupAndReleaseKeepTheirDifferentLifetimes() {
        var owner=new Object();begin(owner,oak,List.of());plan.failed(owner,List.of(),exhausted);plan.release(owner);assertFalse(plan.failures().isEmpty());
        plan.clear();assertTrue(plan.failures().isEmpty());assertEquals(oak,choose(List.of(oak),List.of()).source());
    }
}
