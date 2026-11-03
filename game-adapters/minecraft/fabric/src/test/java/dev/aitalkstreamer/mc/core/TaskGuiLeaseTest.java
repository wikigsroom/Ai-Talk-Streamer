package dev.aitalkstreamer.mc.core;

import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class TaskGuiLeaseTest {
    final AtomicLong now = new AtomicLong(1000);
    final AtomicBoolean current = new AtomicBoolean(true);
    final Object world = new Object(), player = new Object(), inventory = new Object(), screen = new Object(), table = new Object();
    final TaskGuiLease lease = new TaskGuiLease(now::get, current::get);
    void expect(String kind) { lease.expect(kind, world, player, inventory, 0); }
    boolean inventory(Object view, Object handler, int sync) { return lease.permits("inventory", world, player, view, handler, sync); }
    boolean crafting(Object view, Object handler, int sync) { return lease.permits("crafting_table", world, player, view, handler, sync); }
    void openInventory() { expect("inventory"); assertTrue(inventory(screen, inventory, 0)); }
    @Test void storageRequiresAnExpectedNewContainerAndCannotInheritAnotherHandler() {
        expect("storage");assertFalse(lease.permits("storage",world,player,screen,inventory,0));
        assertTrue(lease.permits("storage",world,player,screen,table,7));
        assertFalse(lease.permits("storage",world,player,new Object(),table,7));
        assertFalse(lease.permits("storage",world,player,screen,new Object(),7));
        assertFalse(lease.permits("storage",new Object(),player,screen,table,7));
    }
    @Test void storageProgressNeverExtendsTheOriginalFifteenSecondOpeningBudget() {
        expect("storage");assertTrue(lease.permits("storage",world,player,screen,table,7));
        for(int i=0;i<7;i++){now.addAndGet(2000);lease.progress();}
        now.addAndGet(1000);assertFalse(lease.permits("storage",world,player,screen,table,7));
        lease.clear();expect("storage");current.set(false);assertFalse(lease.permits("storage",world,player,new Object(),new Object(),8));
    }
    @Test void smokerWaitsForOneCookingOperationButCannotInheritAnotherContainer() {
        expect("smoker"); assertFalse(crafting(screen, table, 7));
        assertTrue(lease.permits("smoker",world,player,screen,table,7)); now.addAndGet(5000);
        assertTrue(lease.permits("smoker",world,player,screen,table,7));
        assertFalse(lease.permits("smoker",world,player,new Object(),table,7));
        now.addAndGet(5000); assertFalse(lease.permits("smoker",world,player,screen,table,7));
    }
    @Test void smokerProgressCannotExtendTheOriginalFifteenSecondAbsoluteLimit() {
        expect("smoker"); assertTrue(lease.permits("smoker",world,player,screen,table,7));
        now.addAndGet(9000); lease.progress(); now.addAndGet(5999); assertEquals(1,lease.remaining());
        now.incrementAndGet(); assertFalse(lease.permits("smoker",world,player,screen,table,7));
    }
    @Test void smokerRevocationRejectsLateBindingsAndForgettingOwnershipDoesNotCloseIt() {
        expect("smoker"); current.set(false); assertFalse(lease.permits("smoker",world,player,screen,table,7));
        lease.clear(); current.set(true); assertFalse(lease.permits("smoker",world,player,screen,table,7));
    }
    @Test void noGuiIsAllowedWithoutAnExplicitExpectedOpening() { assertFalse(inventory(screen, inventory, 0)); assertFalse(crafting(screen, table, 7)); }
    @Test void inventoryBindsOnlyTheExistingPlayerHandlerAndItsExactScreen() {
        expect("inventory"); assertFalse(inventory(screen, new Object(), 0)); assertFalse(inventory(screen, inventory, 1));
        assertTrue(inventory(screen, inventory, 0)); assertFalse(inventory(new Object(), inventory, 0));
    }
    @Test void craftingRequiresANewHandlerAndNewPositiveSyncId() {
        expect("crafting_table"); assertTrue(lease.pending()); assertFalse(crafting(screen, inventory, 7)); assertFalse(crafting(screen, table, 0));
        assertTrue(crafting(screen, table, 7)); assertFalse(lease.pending()); assertFalse(crafting(screen, new Object(), 7)); assertFalse(crafting(screen, table, 8));
    }
    @Test void matchingTypeAndSyncNeverAuthorizeAnotherScreen() {
        expect("crafting_table"); assertTrue(crafting(screen, table, 7)); assertFalse(crafting(new Object(), table, 7));
    }
    @Test void worldAndPlayerAreComparedByObjectIdentity() {
        openInventory(); assertFalse(lease.permits("inventory", new Object(), player, screen, inventory, 0));
        assertFalse(lease.permits("inventory", world, new Object(), screen, inventory, 0));
    }
    @Test void anInventoryExpectationCannotAdoptATableOrAnUnknownMenu() {
        expect("inventory"); assertFalse(crafting(screen, table, 7)); assertFalse(lease.permits("menu", world, player, screen, inventory, 0));
    }
    @Test void openingDeadlineRejectsTheFirstLateServerResponse() {
        expect("crafting_table"); now.addAndGet(TaskGuiLease.OPEN_WITHIN_MS); assertFalse(crafting(screen, table, 7));
        assertEquals(0, lease.remaining()); assertThrows(Json.Rejected.class, () -> expect("crafting_table"));
    }
    @Test void observationAloneCannotRenewIdleTime() {
        openInventory(); now.addAndGet(TaskGuiLease.IDLE_MS - 1); assertTrue(inventory(screen, inventory, 0));
        now.incrementAndGet(); assertFalse(inventory(screen, inventory, 0));
    }
    @Test void successfulProgressRenewsIdleTimeWithinTheAbsoluteBudget() {
        openInventory(); now.addAndGet(2000); lease.progress(); now.addAndGet(2000); assertTrue(inventory(screen, inventory, 0));
        assertEquals(1000, lease.remaining());
    }
    @Test void repeatedProgressCannotExtendTheAbsoluteDeadline() {
        openInventory();
        for (int i = 0; i < 7; i++) { now.addAndGet(2000); lease.progress(); }
        assertEquals(1000, lease.remaining()); now.addAndGet(1000); assertFalse(inventory(screen, inventory, 0));
    }
    @Test void revocationPreventsGuiUseAndProgressImmediately() {
        openInventory(); current.set(false); assertFalse(inventory(screen, inventory, 0)); assertEquals(0, lease.remaining());
        assertThrows(Json.Rejected.class, lease::progress);
    }
    @Test void revokedOwnerCannotArmANewOpening() { current.set(false); assertThrows(Json.Rejected.class, () -> expect("inventory")); }
    @Test void forgettingOwnershipDoesNotActOnTheScreenAndAllowsAnExplicitNewOpening() {
        openInventory(); lease.clear(); assertFalse(inventory(screen, inventory, 0)); expect("inventory"); assertTrue(inventory(new Object(), inventory, 0));
    }
    @Test void anotherThreadCannotObserveOrUseTheLease() throws Exception {
        openInventory(); AtomicReference<Throwable> error = new AtomicReference<>();
        Thread worker = new Thread(() -> { try { inventory(screen, inventory, 0); } catch (Throwable failure) { error.set(failure); } });
        worker.start(); worker.join(); assertInstanceOf(Json.Rejected.class, error.get());
    }

    @Test void furnaceAndBlastFurnaceCannotInheritOneAnothersMenu() {
        for(String kind:new String[]{"furnace","blast_furnace"}) {
            var own=new TaskGuiLease(now::get,current::get);own.expect(kind,world,player,inventory,0);
            assertFalse(own.permits(kind.equals("furnace")?"blast_furnace":"furnace",world,player,screen,table,7));
            assertTrue(own.permits(kind,world,player,screen,table,7));assertFalse(own.permits(kind,world,player,new Object(),table,7));
        }
    }
    @Test void furnaceWaitsForItsDeclaredFiniteConversionWindowWithoutObservationRenewal() {
        expect("furnace");assertTrue(lease.permits("furnace",world,player,screen,table,7));now.addAndGet(13000);
        assertTrue(lease.permits("furnace",world,player,screen,table,7));now.addAndGet(52000);
        assertFalse(lease.permits("furnace",world,player,screen,table,7));
    }
    @Test void furnaceProgressCannotExtendItsAbsoluteSeventyFiveSecondLimit() {
        expect("blast_furnace");assertTrue(lease.permits("blast_furnace",world,player,screen,table,7));now.addAndGet(60000);lease.progress();
        now.addAndGet(14999);assertEquals(1,lease.remaining());now.incrementAndGet();assertFalse(lease.permits("blast_furnace",world,player,screen,table,7));
    }
    @Test void furnaceOpeningStillRequiresTheOriginalLiveOwnerAndPromptServerResponse() {
        expect("furnace");now.addAndGet(TaskGuiLease.OPEN_WITHIN_MS);assertFalse(lease.permits("furnace",world,player,screen,table,7));
        lease.clear();expect("blast_furnace");current.set(false);assertFalse(lease.permits("blast_furnace",world,player,screen,table,7));
    }

}
