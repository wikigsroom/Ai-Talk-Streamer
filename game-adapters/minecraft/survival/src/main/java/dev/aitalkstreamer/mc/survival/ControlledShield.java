package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasksystem.TaskChain;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.item.ShieldItem;
import net.minecraft.util.Hand;
import static dev.aitalkstreamer.mc.core.Json.require;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** Native offhand shield use under the accepted root; never empties the main hand or cursor. */
public final class ControlledShield {
    private static ControlledShield active;
    private final SurvivalAuthority.Session owner;
    private final Object world, player, connection, manager, handler;
    private final ShieldCycle cycle = new ShieldCycle(now());
    private ItemStack shield = ItemStack.EMPTY;
    private boolean issuing;

    private ControlledShield() {
        owner = SurvivalAuthority.session(); var client = MinecraftClient.getInstance();
        world = client.world; player = client.player; connection = client.getNetworkHandler();
        manager = client.interactionManager; handler = client.player.playerScreenHandler;
        SurvivalAuthority.owned(() -> { cycle.close(); if (active == this) active = null; });
    }
    private static boolean current() { return active != null && active.owner.current(); }
    public static boolean busy() { return current() && active.cycle.busy(); }
    static boolean issued() { return current() && active.cycle.issued(); }
    public static boolean threatDemanded() { return current() && active.cycle.demanded(ShieldCycle.Source.THREAT); }
    public static boolean meleeDemanded() { return current() && active.cycle.demanded(ShieldCycle.Source.MELEE); }
    public static void requestThreat() { request(ShieldCycle.Source.THREAT); }
    public static void requestMelee() { request(ShieldCycle.Source.MELEE); }
    public static void withdrawThreat() { withdraw(ShieldCycle.Source.THREAT); }
    public static void withdrawMelee() { withdraw(ShieldCycle.Source.MELEE); }
    private static void request(ShieldCycle.Source source) {
        SurvivalAuthority.requireScope(); require(current() && active.owner == SurvivalAuthority.session(), "GAME_SHIELD_NO_TICK");
        active.cycle.request(source);
        // Food retains its original child, server read and restoration even when its chain loses priority.
        ControlledEatingTask.interrupt();
    }
    private static void withdraw(ShieldCycle.Source source) {
        if (!SurvivalAuthority.inScope()) { SurvivalAuthority.requireOwnerScope(); return; }
        if (current()) { require(active.owner == SurvivalAuthority.session(), "GAME_SHIELD_OWNER_CONFLICT"); active.cycle.withdraw(source); }
    }
    public static void beginTick() {
        SurvivalAuthority.requireScope();
        if (!current()) active = new ControlledShield();
        require(active.owner == SurvivalAuthority.session(), "GAME_SHIELD_OWNER_CONFLICT");
        if (active.cycle.issued()) active.context();
        try { active.cycle.begin(now()); }
        catch (LocalTaskFailure failure) { active.stopOwned(); throw failure; }
    }
    public static void endTick() {
        SurvivalAuthority.requireScope(); var own = active; require(current() && own.owner == SurvivalAuthority.session(), "GAME_SHIELD_NO_TICK");
        if (own.cycle.issued()) own.context();
        ShieldCycle.Action action;
        try { action = own.cycle.finish(now(), own::available, own.usingShield()); }
        catch (LocalTaskFailure failure) { own.stopOwned(); throw failure; }
        switch (action) {
            case START -> own.start();
            case KEEP -> SurvivalInputs.key(MinecraftClient.getInstance().options.useKey, true);
            case STOP -> own.stopOwned();
            default -> { }
        }
    }
    private void context() {
        SurvivalAuthority.requireScope(); var client = MinecraftClient.getInstance();
        if (owner != SurvivalAuthority.session() || !client.isOnThread() || client.world != world || client.player != player
                || client.getNetworkHandler() != connection || client.interactionManager != manager
                || !client.player.isAlive() || !client.isWindowFocused() || client.isPaused()
                || client.currentScreen != null || client.player.currentScreenHandler != handler
                || !client.player.playerScreenHandler.getCursorStack().isEmpty()) throw new LocalTaskFailure(SHIELD_CONTEXT_CHANGED);
    }
    private boolean available() {
        var client = MinecraftClient.getInstance();
        if (ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledCookingTask.blocksInventory() || ControlledEatingTask.busy()
                || client.currentScreen != null || client.player.currentScreenHandler != handler || client.player.isUsingItem()
                || !client.player.playerScreenHandler.getCursorStack().isEmpty()) return false;
        context();
        if (client.player.isSpectator() || client.player.getAbilities().creativeMode) return false;
        for (int i = 0; i < 5; i++) if (!client.player.playerScreenHandler.getSlot(i).getStack().isEmpty()) return false;
        var value = client.player.getOffHandStack();
        return value.isOf(Items.SHIELD) && value.getItem().getClass() == ShieldItem.class && value.getCount() == 1
                && !client.player.getItemCooldownManager().isCoolingDown(value.getItem());
    }
    private static ItemStack identity(ItemStack value) { var result = value.copyWithCount(1); result.setDamage(0); return result; }
    private boolean sameShield(ItemStack value) {
        return !shield.isEmpty() && value.isOf(Items.SHIELD) && value.getCount() == 1
                && ItemStack.areItemsAndComponentsEqual(identity(value), identity(shield));
    }
    private boolean usingShield() {
        var client = MinecraftClient.getInstance();
        return client.player.isUsingItem() && client.player.getActiveHand() == Hand.OFF_HAND
                && sameShield(client.player.getActiveItem()) && sameShield(client.player.getOffHandStack())
                && !client.player.getItemCooldownManager().isCoolingDown(Items.SHIELD);
    }
    private void start() {
        context(); var client = MinecraftClient.getInstance(); shield = client.player.getOffHandStack().copy();
        SurvivalActions.cancelBreaking(client.interactionManager);
        SurvivalInputs.key(client.options.useKey, true); issuing = true;
        try { cycle.accepted(SurvivalActions.interactItem(client.interactionManager, client.player, Hand.OFF_HAND).isAccepted(), usingShield()); }
        finally { issuing = false; }
    }
    private void stopOwned() {
        if (!cycle.issued()) return;
        context(); var client = MinecraftClient.getInstance();
        // An old shield request cannot stop an unrelated active item, including an operator's item.
        if (client.player.isUsingItem() && (client.player.getActiveHand() != Hand.OFF_HAND || !sameShield(client.player.getActiveItem())))
            throw new LocalTaskFailure(SHIELD_CONTEXT_CHANGED);
        SurvivalInputs.key(client.options.useKey, false);
        SurvivalActions.stopShieldUse(client.interactionManager, client.player);
        cycle.stopped(); shield = ItemStack.EMPTY;
    }
    static boolean allowItemUse(Hand hand) { return !busy() || active.issuing && hand == Hand.OFF_HAND; }
    static void guardShieldStop() { require(issued() && active.owner == SurvivalAuthority.session() && !active.issuing, "GAME_SHIELD_STOP_NOT_OWNED"); active.context(); }
    static void guardGuiWrite() { require(!issued(), "GAME_SHIELD_GUI_BUSY"); }
    static boolean attacksBlocked() { return current() && active.cycle.attacksBlocked(); }
    static boolean beforeAttack() {
        SurvivalAuthority.requireScope(); if (!current()) return true;
        if (!active.cycle.beforeAttack()) return false;
        active.stopOwned(); return true;
    }
    static void stopForOtherUse() {
        SurvivalAuthority.requireScope(); if (!current()) return;
        active.cycle.suppress(); active.stopOwned();
    }
    public static boolean defers(TaskChain chain) { return busy() && chain instanceof adris.altoclef.chains.UserTaskChain; }
    static void finishOwned() { stopForOtherUse(); }
    private static long now() { return System.nanoTime() / 1_000_000; }
}
