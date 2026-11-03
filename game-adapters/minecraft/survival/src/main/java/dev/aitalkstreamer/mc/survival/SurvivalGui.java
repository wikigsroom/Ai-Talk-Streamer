package dev.aitalkstreamer.mc.survival;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.TaskGuiLease;
import net.minecraft.block.Blocks;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.ingame.CraftingScreen;
import net.minecraft.client.gui.screen.ingame.InventoryScreen;
import net.minecraft.client.gui.screen.ingame.SmokerScreen;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.client.network.ClientPlayerInteractionManager;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.recipe.RecipeEntry;
import net.minecraft.screen.CraftingScreenHandler;
import net.minecraft.screen.SmokerScreenHandler;
import net.minecraft.screen.ScreenHandler;
import net.minecraft.network.packet.s2c.play.InventoryS2CPacket;
import net.minecraft.item.ItemStack;
import java.util.*;
import net.minecraft.screen.slot.SlotActionType;
import net.minecraft.util.ActionResult;
import net.minecraft.util.Hand;
import net.minecraft.util.hit.BlockHitResult;
import net.minecraft.util.math.BlockPos;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Typed sinks for task-opened inventory, crafting and single-batch smoking. */
public final class SurvivalGui {
    private static Binding binding;
    private static final class Binding {
        final SurvivalAuthority.Session owner;
        final TaskGuiLease lease;
        BlockPos table;
        Object smokerEntity;
        FurnaceSnapshot furnaceSnapshot;
        StorageSite storageSite;
        ContainerSnapshot storageSnapshot;
        Binding(SurvivalAuthority.Session owner) {
            this.owner = owner; lease = new TaskGuiLease(() -> System.nanoTime() / 1_000_000, owner::current);
        }
    }
    private SurvivalGui() { }
    private static MinecraftClient client() {
        MinecraftClient client = MinecraftClient.getInstance();
        require(client.isOnThread(), "GAME_WRONG_THREAD");
        require(client.world != null && client.player != null && client.player.isAlive() && client.interactionManager != null,
                "GAME_WORLD_UNAVAILABLE");
        require(client.isWindowFocused() && !client.isPaused(), "GAME_GUI_BLOCKED"); return client;
    }
    private static Binding owner() {
        var session = SurvivalAuthority.session();
        if (binding == null || binding.owner != session) {
            require(binding == null || !binding.owner.current(), "GAME_GUI_OWNER_CONFLICT");
            Binding created = new Binding(session); binding = created;
            SurvivalAuthority.owned(() -> { created.lease.clear(); if (binding == created) binding = null; });
        }
        return binding;
    }
    private static boolean permits(Binding own, MinecraftClient client) {
        if (own == null || !own.owner.current()) return false;
        var screen = client.currentScreen; var handler = client.player.currentScreenHandler;
        String kind;
        if (screen != null && screen.getClass() == InventoryScreen.class
                && ((InventoryScreen) screen).getScreenHandler() == handler && handler == client.player.playerScreenHandler) kind = "inventory";
        else if (screen != null && screen.getClass() == CraftingScreen.class && handler instanceof CraftingScreenHandler
                && ((CraftingScreen) screen).getScreenHandler() == handler && own.table != null
                && client.world.getBlockState(own.table).isOf(Blocks.CRAFTING_TABLE)
                && client.player.getBlockPos().getSquaredDistance(own.table) <= 64) kind = "crafting_table";
        else if (screen instanceof net.minecraft.client.gui.screen.ingame.HandledScreen<?> handled
                && handled.getScreenHandler()==handler && furnaceKind(screen,handler)!=null && own.table != null && own.smokerEntity != null
                && client.world.getBlockEntity(own.table) == own.smokerEntity
                && client.world.getBlockState(own.table).isOf(furnaceKind(screen,handler).block())
                && client.player.getBlockPos().getSquaredDistance(own.table) <= 64) kind = furnaceKind(screen,handler).id();
        else if (screen != null && screen.getClass()==net.minecraft.client.gui.screen.ingame.GenericContainerScreen.class
                && handler.getClass()==net.minecraft.screen.GenericContainerScreenHandler.class
                && ((net.minecraft.client.gui.screen.ingame.GenericContainerScreen)screen).getScreenHandler()==handler
                && own.storageSite!=null && own.storageSite.valid(client)
                && handler.slots.size()==own.storageSite.slots()+36) kind="storage";
        else return false;
        return own.lease.permits(kind, client.world, client.player, screen, handler, handler.syncId);
    }
    private static CookingWorkstation furnaceKind(Object screen,ScreenHandler handler) {
        for(var kind:CookingWorkstation.values()) if(kind.screen(screen) && kind.handler(handler)) return kind;return null;
    }
    public static boolean furnaceOpen() {
        var own=binding;var c=MinecraftClient.getInstance();return own!=null && own.owner.current() && c.isOnThread()
                && c.world!=null && c.player!=null && c.isWindowFocused() && !c.isPaused()
                && furnaceKind(c.currentScreen,c.player.currentScreenHandler)!=null && permits(own,c);
    }
    record FurnaceSnapshot(ScreenHandler handler,List<ItemStack> contents,ItemStack cursor,int revision) { }
    record ContainerSnapshot(ScreenHandler handler,List<ItemStack> contents,ItemStack cursor,int revision) { }
    /** Both halves of a double chest retain their block states and actual block-entity identities. */
    private record StorageSite(BlockPos position,net.minecraft.block.BlockState state,Object entity,
                               BlockPos partner,net.minecraft.block.BlockState partnerState,Object partnerEntity,int slots) {
        static StorageSite capture(MinecraftClient client,BlockPos position) {
            require(ControlledStorage.expects(position),"GAME_STORAGE_CONTEXT_CHANGED");
            var state=client.world.getBlockState(position);var entity=client.world.getBlockEntity(position);
            require(entity!=null && storageBlock(state),"GAME_STORAGE_UNSUPPORTED");
            BlockPos partner=null;net.minecraft.block.BlockState other=null;Object otherEntity=null;int slots=27;
            if(!state.isOf(Blocks.BARREL) && state.get(net.minecraft.block.ChestBlock.CHEST_TYPE)!=net.minecraft.block.enums.ChestType.SINGLE) {
                partner=position.offset(net.minecraft.block.ChestBlock.getFacing(state));other=client.world.getBlockState(partner);otherEntity=client.world.getBlockEntity(partner);
                require(other.getBlock()==state.getBlock() && other.get(net.minecraft.block.ChestBlock.CHEST_TYPE)!=net.minecraft.block.enums.ChestType.SINGLE
                        && other.get(net.minecraft.block.ChestBlock.CHEST_TYPE)!=state.get(net.minecraft.block.ChestBlock.CHEST_TYPE)
                        && other.get(net.minecraft.block.ChestBlock.FACING)==state.get(net.minecraft.block.ChestBlock.FACING)
                        && partner.offset(net.minecraft.block.ChestBlock.getFacing(other)).equals(position) && otherEntity!=null,"GAME_STORAGE_CONTEXT_CHANGED");slots=54;
            }
            return new StorageSite(position.toImmutable(),state,entity,partner,other,otherEntity,slots);
        }
        boolean valid(MinecraftClient client) {
            var current=client.world.getBlockState(position);
            return ControlledStorage.expects(position) && client.player.getBlockPos().getSquaredDistance(position)<=64
                    && client.world.getBlockEntity(position)==entity
                    && (state.isOf(Blocks.BARREL)?current.isOf(Blocks.BARREL):current.equals(state))
                    && (partner==null || client.world.getBlockEntity(partner)==partnerEntity && client.world.getBlockState(partner).equals(partnerState));
        }
    }
    private static boolean storageBlock(net.minecraft.block.BlockState state){return state.isOf(Blocks.CHEST)||state.isOf(Blocks.TRAPPED_CHEST)||state.isOf(Blocks.BARREL);}
    /** Captured from the original full server packet; local menu prediction is never a baseline. */
    static void synchronizedInventory(InventoryS2CPacket packet) {
        var own=binding;var client=MinecraftClient.getInstance();
        if(own==null || !own.owner.current() || !client.isOnThread() || client.player==null || client.world==null
                || packet.getSyncId()!=client.player.currentScreenHandler.syncId || !permits(own,client)) return;
        if(furnaceKind(client.currentScreen,client.player.currentScreenHandler)!=null && packet.getContents().size()==39)
            own.furnaceSnapshot=new FurnaceSnapshot(client.player.currentScreenHandler,packet.getContents().stream().map(ItemStack::copy).toList(),packet.getCursorStack().copy(),packet.getRevision());
        else if(own.storageSite!=null && packet.getContents().size()==own.storageSite.slots()+36)
            own.storageSnapshot=new ContainerSnapshot(client.player.currentScreenHandler,packet.getContents().stream().map(ItemStack::copy).toList(),packet.getCursorStack().copy(),packet.getRevision());
    }
    static ContainerSnapshot storageSnapshot(BlockPos target) {
        var handler=ownedHandler();var own=owner();var value=own.storageSnapshot;
        require(own.storageSite!=null && own.storageSite.position().equals(target),"GAME_STORAGE_CONTEXT_CHANGED");
        return value!=null && value.handler()==handler?value:null;
    }
    static boolean storageOpening(){var own=binding;return own!=null && own.owner.current() && own.storageSite!=null && own.lease.exists();}
    static boolean storageReady(){
        SurvivalAuthority.requireScope();var c=client();var own=owner();
        require(own.storageSite!=null && own.lease.remaining()>0,"GAME_STORAGE_SERVER_TIMEOUT");
        if(c.currentScreen==null && c.player.currentScreenHandler==c.player.playerScreenHandler)return false;
        require(permits(own,c) && "storage".equals(own.lease.kind()),"GAME_STORAGE_CONTEXT_CHANGED");return true;
    }
    static FurnaceSnapshot furnaceSnapshot() {
        var handler=ownedHandler();var own=owner();var value=own.furnaceSnapshot;
        return value!=null && value.handler()==handler?value:null;
    }
    /** A fact check outside a task scope does not acquire the current task's write authority. */
    public static boolean allows(JsonObject task) {
        MinecraftClient client = MinecraftClient.getInstance(); Binding own = binding;
        if (!client.isOnThread() || client.player == null || client.world == null || !client.player.isAlive()
                || !client.isWindowFocused() || client.isPaused() || own == null || !own.owner.current()) return false;
        var context = own.owner.context();
        return context.task().equals(str(task, "task_id")) && context.world().equals(str(task, "world_session_id"))
                && context.epoch() == num(task, "control_epoch") && permits(own, client);
    }
    static net.minecraft.screen.ScreenHandler ownedHandler() {
        SurvivalAuthority.requireScope(); var client = client(); require(permits(owner(), client), "GAME_GUI_NOT_OWNED");
        return client.player.currentScreenHandler;
    }
    public static void screen(MinecraftClient requestedClient, Screen requested) {
        // During revoked tree cleanup, leave the GUI to the operator. No close packet or screen write.
        if (!SurvivalAuthority.inScope()) {
            SurvivalAuthority.requireOwnerScope(); require(requested == null, "GAME_GUI_REVOKED"); return;
        }
        SurvivalAuthority.write(() -> {
            ConfirmedCraftTask.guardGuiWrite();
            ControlledCookingTask.guardGuiWrite();
            ControlledEatingTask.guardGuiWrite();
            ControlledEquipment.guardGuiWrite();
            ControlledShield.guardGuiWrite();
            ControlledStorage.guardGuiWrite();
            MinecraftClient client = client(); require(client == requestedClient, "GAME_GUI_CONTEXT"); Binding own = owner();
            if (requested == null) { closeCurrent(own, client); return; }
            require(requested.getClass() == InventoryScreen.class && client.currentScreen == null
                    && client.player.currentScreenHandler == client.player.playerScreenHandler
                    && ((InventoryScreen) requested).getScreenHandler() == client.player.playerScreenHandler,
                    "GAME_GUI_UNSUPPORTED");
            require(client.player.currentScreenHandler.getCursorStack().isEmpty(), "GAME_GUI_CURSOR_NOT_EMPTY");
            own.lease.expect("inventory", client.world, client.player, client.player.currentScreenHandler, client.player.currentScreenHandler.syncId);
            try {
                client.setScreen(requested); require(client.currentScreen == requested && permits(own, client), "GAME_GUI_OPEN_FAILED");
            } catch (RuntimeException | Error failure) { own.lease.clear(); throw failure; }
        });
    }
    public static void close(ClientPlayerEntity player) {
        if (!SurvivalAuthority.inScope()) { SurvivalAuthority.requireOwnerScope(); return; }
        SurvivalAuthority.write(() -> { ConfirmedCraftTask.guardGuiWrite(); ControlledCookingTask.guardGuiWrite(); ControlledEatingTask.guardGuiWrite(); ControlledEquipment.guardGuiWrite(); ControlledStorage.guardGuiWrite(); MinecraftClient client = client(); require(client.player == player, "GAME_GUI_CONTEXT"); closeCurrent(owner(), client); });
    }
    private static void closeCurrent(Binding own, MinecraftClient client) {
        require(client.player.currentScreenHandler.getCursorStack().isEmpty(), "GAME_GUI_CURSOR_NOT_EMPTY");
        if (client.currentScreen != null) require(permits(own, client), "GAME_GUI_NOT_OWNED");
        else require(client.player.currentScreenHandler == client.player.playerScreenHandler, "GAME_GUI_NOT_OWNED");
        client.player.closeHandledScreen(); own.lease.clear(); own.table = null; own.smokerEntity = null;own.furnaceSnapshot=null;own.storageSite=null;own.storageSnapshot=null;
    }
    public static ActionResult block(ClientPlayerInteractionManager manager, ClientPlayerEntity player, Hand hand, BlockHitResult hit) {
        return SurvivalAuthority.effect(() -> {
            if (ControlledEquipment.busy() || ControlledShield.busy() || ControlledStorage.blocksInventory()) return ActionResult.PASS;
            MinecraftClient client = client(); require(client.interactionManager == manager && client.player == player, "GAME_GUI_CONTEXT");
            boolean table = !player.isSneaking() && workstation(client, hit) != null;
            Binding own = table ? owner() : null;
            if (table && !expectTable(own, client, hit)) return ActionResult.PASS;
            if(!table)ControlledMaterialUse.beforeBlock(hand);
            ActionResult result;
            try { result = manager.interactBlock(player, hand, hit); }
            catch (RuntimeException | Error error) { if (own != null) own.lease.clear(); throw error; }
            if (own != null && !result.isAccepted()) own.lease.clear();
            return result;
        });
    }
    private static boolean expectTable(Binding own, MinecraftClient client, BlockHitResult hit) {
        var player = client.player;
        require(client.currentScreen == null && player.currentScreenHandler == player.playerScreenHandler, "GAME_GUI_NOT_OWNED");
        if (own.lease.pending()) { require(hit.getBlockPos().equals(own.table), "GAME_GUI_OPEN_PENDING"); return false; }
        require(!own.lease.exists(), "GAME_GUI_EXPECTATION_EXPIRED");
        String kind = workstation(client, hit); require(kind != null, "GAME_GUI_UNSUPPORTED");
        own.table = hit.getBlockPos().toImmutable();
        own.storageSite=kind.equals("storage")?StorageSite.capture(client,own.table):null;own.storageSnapshot=null;
        own.smokerEntity = !kind.equals("crafting_table") && !kind.equals("storage") ? client.world.getBlockEntity(own.table) : null;
        own.furnaceSnapshot=null;
        require(kind.equals("crafting_table") || kind.equals("storage") || own.smokerEntity != null, "GAME_GUI_CONTEXT");
        own.lease.expect(kind, client.world, player, player.currentScreenHandler, player.currentScreenHandler.syncId); return true;
    }
    private static String workstation(MinecraftClient client, BlockHitResult hit) {
        var block = client.world.getBlockState(hit.getBlockPos());
        if(block.isOf(Blocks.CRAFTING_TABLE)) return "crafting_table";
        for(var kind:CookingWorkstation.values()) if(block.isOf(kind.block())) return kind.id();
        if(ControlledStorage.expects(hit.getBlockPos())) {require(storageBlock(block),"GAME_STORAGE_UNSUPPORTED");return "storage";}return null;
    }
    /** MC's synthetic use-key reaches vanilla interactBlock internally, outside transformed third-party bytecode. */
    public static boolean beforeUse() {
        SurvivalAuthority.requireScope(); MinecraftClient client = client();
        if(ControlledStorage.blocksInventory())return false;
        if (client.currentScreen != null) { require(permits(owner(), client), "GAME_GUI_NOT_OWNED"); return false; }
        if (!client.player.isSneaking() && client.crosshairTarget instanceof BlockHitResult hit
                && workstation(client, hit) != null)
            return SurvivalAuthority.effect(() -> expectTable(owner(), client, hit));
        if(client.crosshairTarget instanceof BlockHitResult hit && hit.getType()==net.minecraft.util.hit.HitResult.Type.BLOCK)ControlledMaterialUse.beforeBlockHands();
        return true;
    }
    private static Binding slotContext(MinecraftClient client, int sync) {
        require(client.player.currentScreenHandler.syncId == sync, "GAME_GUI_SYNC_CHANGED");
        if (client.currentScreen == null && client.player.currentScreenHandler == client.player.playerScreenHandler) return null;
        Binding own = owner(); require(permits(own, client), "GAME_GUI_NOT_OWNED"); return own;
    }
    public static void slot(ClientPlayerInteractionManager manager, int sync, int slot, int button, SlotActionType action, PlayerEntity player) {
        SurvivalAuthority.write(() -> {
            ConfirmedCraftTask.guardGuiWrite();
            ControlledCookingTask.guardGuiWrite();
            ControlledEatingTask.guardGuiWrite();
            ControlledEquipment.guardGuiWrite();
            ControlledShield.guardGuiWrite();
            ControlledStorage.guardGuiWrite();
            MinecraftClient client = client(); require(client.interactionManager == manager && player == client.player, "GAME_GUI_CONTEXT");
            Binding own = slotContext(client, sync);
            require(slot >= 0 && slot < client.player.currentScreenHandler.slots.size() || slot == -999, "GAME_GUI_SLOT_INVALID");
            boolean valid = switch (action) {
                case PICKUP -> button == 0 || button == 1;
                case QUICK_MOVE, THROW, PICKUP_ALL -> slot >= 0 && (button == 0 || button == 1);
                case SWAP -> slot >= 0 && (button >= 0 && button < 9 || button == 40);
                default -> false;
            };
            require(valid, "GAME_GUI_ACTION_UNSUPPORTED");
            ControlledMaterialUse.beforeDrop(client.player.currentScreenHandler,slot,button,action);
            manager.clickSlot(sync, slot, button, action, player);
            if (own != null) own.lease.progress();
        });
    }
    public static void recipe(ClientPlayerInteractionManager manager, int sync, RecipeEntry<?> recipe, boolean all) {
        SurvivalAuthority.write(() -> {
            ConfirmedCraftTask.guardGuiWrite();
            ControlledCookingTask.guardGuiWrite();
            ControlledEatingTask.guardGuiWrite();
            ControlledEquipment.guardGuiWrite();
            ControlledShield.guardGuiWrite();
            ControlledStorage.guardGuiWrite();
            MinecraftClient client = client(); require(client.interactionManager == manager && client.getNetworkHandler() != null, "GAME_GUI_CONTEXT");
            Binding own = slotContext(client, sync);
            var current = client.getNetworkHandler().getRecipeManager().get(recipe.id());
            require(current.isPresent() && current.get().value() == recipe.value(), "GAME_CRAFT_RECIPE_CHANGED");
            manager.clickRecipe(sync, recipe, all); if (own != null) own.lease.progress();
        });
    }
    /** Natural completion closes only our own empty-cursor GUI while the original permit is live. */
    static boolean backtrackReady() {
        SurvivalAuthority.requireScope();var client=client();var handler=client.player.currentScreenHandler;
        if(client.player.isUsingItem() || !handler.getCursorStack().isEmpty())return false;
        var own=binding;
        if(client.currentScreen==null)return handler==client.player.playerScreenHandler && (own==null || !own.lease.pending());
        if(!permits(own,client))return false;
        int slots=client.currentScreen.getClass()==InventoryScreen.class?5:client.currentScreen.getClass()==CraftingScreen.class?10:furnaceKind(client.currentScreen,handler)!=null?3:own.storageSite!=null?0:-1;
        if(slots<0)return false;
        if(furnaceKind(client.currentScreen,handler)!=null) {
            var snapshot=own.furnaceSnapshot;
            if(snapshot==null || snapshot.handler()!=handler || !snapshot.cursor().isEmpty())return false;
            for(int i=0;i<3;i++)if(!snapshot.contents().get(i).isEmpty())return false;
        }
        if(own.storageSite!=null) {
            var snapshot=own.storageSnapshot;
            if(ControlledStorage.busy() || snapshot==null || snapshot.handler()!=handler || !snapshot.cursor().isEmpty()
                    || snapshot.contents().size()!=handler.slots.size())return false;
            for(int i=0;i<handler.slots.size();i++)if(!ItemStack.areEqual(handler.getSlot(i).getStack(),snapshot.contents().get(i)))return false;
        }
        for(int i=0;i<slots;i++)if(!handler.getSlot(i).getStack().isEmpty())return false;
        return true;
    }
    public static void finishOwned() {
        SurvivalAuthority.requireScope(); require(!ControlledCookingTask.busy() && !ControlledEatingTask.busy() && !ControlledEquipment.busy() && !ControlledStorage.busy(), "GAME_RESOURCE_CLEANUP_REQUIRED"); Binding own = binding; if (own == null) return;
        MinecraftClient client = client();
        if (client.currentScreen != null) SurvivalAuthority.write(() -> closeCurrent(own, client));
        else { require(!own.lease.pending(), "GAME_GUI_OPEN_PENDING"); own.lease.clear(); }
    }
}
