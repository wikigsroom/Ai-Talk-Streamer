package dev.aitalkstreamer.mc.survival;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.client.network.ClientPlayerInteractionManager;
import net.minecraft.entity.Entity;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.util.ActionResult;
import net.minecraft.util.Hand;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Direction;
import static dev.aitalkstreamer.mc.core.Json.require;

/** Direct upstream effects use actual game identities and reach, under the original root's permit. */
public final class SurvivalActions {
    private static Binding binding;
    private static final class Binding {
        final SurvivalAuthority.Session owner;
        final InteractionLedger ledger = new InteractionLedger();
        final AttackPacer attacks = new AttackPacer();
        final ClientPlayerInteractionManager manager;
        final ClientPlayerEntity player;
        Binding(SurvivalAuthority.Session owner, MinecraftClient client) {
            this.owner=owner; manager=client.interactionManager; player=client.player;
        }
    }
    private SurvivalActions() { }
    private static MinecraftClient context() {
        MinecraftClient client=MinecraftClient.getInstance();
        require(client.isOnThread(),"GAME_WRONG_THREAD");
        require(client.world!=null && client.player!=null && client.player.isAlive()
                && client.getNetworkHandler()!=null && client.interactionManager!=null,"GAME_WORLD_UNAVAILABLE");
        require(client.isWindowFocused() && !client.isPaused(),"GAME_GUI_BLOCKED");
        return client;
    }
    private static MinecraftClient gameplay() {
        MinecraftClient client=context();
        require(client.currentScreen==null && client.player.currentScreenHandler==client.player.playerScreenHandler,"GAME_GUI_BLOCKED");
        return client;
    }
    private static void player(MinecraftClient client, Entity player) {
        require(client.player==player,"GAME_ACTION_PLAYER_CHANGED");
    }
    private static void manager(MinecraftClient client, ClientPlayerInteractionManager manager) {
        require(client.interactionManager==manager,"GAME_ACTION_MANAGER_CHANGED");
    }
    private static void hand(Hand hand) { require(hand!=null,"GAME_ACTION_HAND_INVALID"); }
    private static Binding owner(MinecraftClient client) {
        var session=SurvivalAuthority.session();
        if (binding==null || binding.owner!=session) {
            require(binding==null || !binding.owner.current(),"GAME_ACTION_OWNER_CONFLICT");
            Binding created=new Binding(session,client); binding=created;
            SurvivalAuthority.owned(()->{ created.ledger.discard(); if (binding==created) binding=null; });
        }
        require(binding.player==client.player && binding.manager==client.interactionManager,"GAME_ACTION_CONTEXT_CHANGED");
        return binding;
    }
    private static void block(MinecraftClient client, BlockPos position, Direction face) {
        require(position!=null && face!=null,"GAME_ACTION_BLOCK_INVALID");
        require(client.world.isInBuildLimit(position) && client.world.getWorldBorder().contains(position)
                && client.world.isChunkLoaded(position),"GAME_ACTION_BLOCK_UNAVAILABLE");
        require(client.player.canInteractWithBlockAt(position,0.0),"GAME_ACTION_BLOCK_OUT_OF_REACH");
    }
    private static void entity(MinecraftClient client, Entity target) {
        require(target!=null && target!=client.player && !(target instanceof PlayerEntity)
                && target.getWorld()==client.world && client.world.getEntityById(target.getId())==target
                && target.isAlive() && !target.isRemoved(),"GAME_ACTION_ENTITY_CHANGED");
        require(client.player.canInteractWithEntity(target,0.0) && client.player.canSee(target),"GAME_ACTION_ENTITY_OUT_OF_REACH");
    }
    /** Upstream pursuit uses vanilla reach and sight; an expected moving/out-of-range target is not a fatal write. */
    public static boolean entityInReach(Entity target) {
        SurvivalAuthority.requireScope(); var client=gameplay();
        return !ControlledEquipment.busy() && !ControlledStorage.blocksInventory() && target!=null && target!=client.player && !(target instanceof PlayerEntity)
                && target.getWorld()==client.world && client.world.getEntityById(target.getId())==target
                && target.isAlive() && !target.isRemoved() && target.isAttackable()
                && client.player.canInteractWithEntity(target,0.0) && client.player.canSee(target);
    }
    private static float attackCooldown(MinecraftClient client, Entity target) {
        return target instanceof net.minecraft.entity.projectile.FireballEntity ? 1 : client.player.getAttackCooldownProgress(0);
    }
    public static boolean readyToAttack(Entity target) {
        if (!entityInReach(target)) return false;
        var client=gameplay(); return !ControlledShield.attacksBlocked() && ControlledDefenseTask.attackAllowed(target)
                && owner(client).attacks.ready(client.player.age,attackCooldown(client,target));
    }
    /** Called only by the bridge for a key still owned by this root's input ledger. */
    public static void vanilla(dev.aitalkstreamer.mc.core.HeldActionRouter.Action action, Runnable effect) {
        java.util.Objects.requireNonNull(action);java.util.Objects.requireNonNull(effect);
        SurvivalAuthority.write(()->{
            if (ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledStorage.blocksInventory()) return;
            if (ControlledShield.busy() && action != dev.aitalkstreamer.mc.core.HeldActionRouter.Action.ATTACK) return;
            // This is the one GUI-use preflight for both the first click and subsequent held uses.
            if (action == dev.aitalkstreamer.mc.core.HeldActionRouter.Action.USE && !SurvivalGui.beforeUse()) return;
            var client=gameplay();
            if (client.crosshairTarget instanceof net.minecraft.util.hit.EntityHitResult hit) {
                entity(client,hit.getEntity());
                if (action != dev.aitalkstreamer.mc.core.HeldActionRouter.Action.USE)
                    require(hit.getEntity().isAttackable(),"GAME_ACTION_ENTITY_NOT_ATTACKABLE");
                if (action == dev.aitalkstreamer.mc.core.HeldActionRouter.Action.ATTACK) {
                    if (!ControlledDefenseTask.attackAllowed(hit.getEntity())) return;
                    owner(client).attacks.issue(client.player.age,attackCooldown(client,hit.getEntity()),()->{
                        if (ControlledShield.beforeAttack()) effect.run();
                    });
                    return;
                }
            } else if (client.crosshairTarget instanceof net.minecraft.util.hit.BlockHitResult hit
                    && hit.getType() == net.minecraft.util.hit.HitResult.Type.BLOCK) {
                block(client,hit.getBlockPos(),hit.getSide());
            }
            var kind=action == dev.aitalkstreamer.mc.core.HeldActionRouter.Action.USE
                    ? InteractionLedger.Kind.USING : InteractionLedger.Kind.BREAKING;
            owner(client).ledger.issue(kind,()->{effect.run();return null;});
        });
    }
    public static void yaw(Entity requested, float value) {
        SurvivalAuthority.write(()->{ var client=gameplay(); player(client,requested);
            require(Float.isFinite(value),"GAME_ACTION_ROTATION_INVALID"); requested.setYaw(value); });
    }
    public static void yaw(ClientPlayerEntity requested, float value) { yaw((Entity)requested,value); }
    public static void pitch(Entity requested, float value) {
        SurvivalAuthority.write(()->{ var client=gameplay(); player(client,requested);
            require(Float.isFinite(value) && value>=-90 && value<=90,"GAME_ACTION_ROTATION_INVALID"); requested.setPitch(value); });
    }
    public static void pitch(ClientPlayerEntity requested, float value) { pitch((Entity)requested,value); }
    public static void sprint(ClientPlayerEntity requested, boolean sprinting) {
        SurvivalAuthority.write(()->{ var client=gameplay(); player(client,requested); requested.setSprinting(sprinting); });
    }
    public static void swing(ClientPlayerEntity requested, Hand hand) {
        SurvivalAuthority.write(()->{ if (ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledShield.issued()) return; var client=gameplay(); player(client,requested); hand(hand); requested.swingHand(hand); });
    }
    public static boolean attackBlock(ClientPlayerInteractionManager requested, BlockPos position, Direction face) {
        return SurvivalAuthority.effect(()->{ if (ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledShield.busy()) return false; var client=gameplay(); manager(client,requested); block(client,position,face);
            return owner(client).ledger.issue(InteractionLedger.Kind.BREAKING,()->requested.attackBlock(position,face)); });
    }
    public static boolean breakProgress(ClientPlayerInteractionManager requested, BlockPos position, Direction face) {
        return SurvivalAuthority.effect(()->{ if (ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledShield.busy()) return false; var client=gameplay(); manager(client,requested); block(client,position,face);
            return owner(client).ledger.issue(InteractionLedger.Kind.BREAKING,()->requested.updateBlockBreakingProgress(position,face)); });
    }
    public static void attackEntity(ClientPlayerInteractionManager requested, PlayerEntity requestedPlayer, Entity target) {
        SurvivalAuthority.write(()->{ if (ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledStorage.blocksInventory()) return; var client=gameplay(); manager(client,requested); player(client,requestedPlayer); entity(client,target);
            require(target.isAttackable(),"GAME_ACTION_ENTITY_NOT_ATTACKABLE");
            if (!ControlledDefenseTask.attackAllowed(target)) return;
            owner(client).attacks.issue(client.player.age,attackCooldown(client,target),()->{
                if (ControlledShield.beforeAttack()) requested.attackEntity(requestedPlayer,target);
            }); });
    }
    public static ActionResult interactEntity(ClientPlayerInteractionManager requested, PlayerEntity requestedPlayer, Entity target, Hand hand) {
        return SurvivalAuthority.effect(()->{ if (ControlledStorage.blocksInventory() || ControlledEquipment.busy() || ControlledShield.busy()) return ActionResult.PASS; var client=gameplay(); manager(client,requested); player(client,requestedPlayer);
            entity(client,target); hand(hand); return requested.interactEntity(requestedPlayer,target,hand); });
    }
    public static ActionResult interactItem(ClientPlayerInteractionManager requested, PlayerEntity requestedPlayer, Hand hand) {
        return SurvivalAuthority.effect(()->{ if (ControlledStorage.blocksInventory() || ControlledEquipment.busy() || !ControlledShield.allowItemUse(hand)) return ActionResult.PASS; ControlledEatingTask.guardItemUse(); var client=gameplay(); manager(client,requested); player(client,requestedPlayer); hand(hand);
            return owner(client).ledger.issue(InteractionLedger.Kind.USING,()->requested.interactItem(requestedPlayer,hand)); });
    }
    private static void stop(InteractionLedger.Kind kind, ClientPlayerInteractionManager requested, PlayerEntity requestedPlayer) {
        // Revoked cleanup drops only this root's claim. The physical operator's current action is not cancelled.
        if (!SurvivalAuthority.inScope()) {
            SurvivalAuthority.requireOwnerScope(); Binding own=binding;
            if (own!=null) own.ledger.stop(kind,false,()->{});
            return;
        }
        SurvivalAuthority.write(()->{ var client=context(); manager(client,requested); player(client,requestedPlayer);
            Binding own=binding;
            if (own==null) return;
            require(own.owner==SurvivalAuthority.session() && own.manager==requested && own.player==requestedPlayer,"GAME_ACTION_OWNER_CONFLICT");
            own.ledger.stop(kind,true,()->{
                if (kind==InteractionLedger.Kind.BREAKING) { if (requested.isBreakingBlock()) requested.cancelBlockBreaking(); }
                else if (client.player.isUsingItem()) requested.stopUsingItem(requestedPlayer);
            });
        });
    }
    public static void cancelBreaking(ClientPlayerInteractionManager requested) {
        if (!SurvivalAuthority.inScope()) { stop(InteractionLedger.Kind.BREAKING,requested,null); return; }
        stop(InteractionLedger.Kind.BREAKING,requested,context().player);
    }
    public static void stopUsing(ClientPlayerInteractionManager requested, PlayerEntity requestedPlayer) {
        if (SurvivalAuthority.inScope() && ControlledShield.issued()) {
            var client=context(); manager(client,requested); player(client,requestedPlayer);
            ControlledShield.stopForOtherUse(); return;
        }
        stop(InteractionLedger.Kind.USING,requested,requestedPlayer);
    }
    static void stopShieldUse(ClientPlayerInteractionManager requested, PlayerEntity requestedPlayer) {
        SurvivalAuthority.write(()->{
            ControlledShield.guardShieldStop(); var client=context(); manager(client,requested); player(client,requestedPlayer);
            // The original pending shield request owns this stop even after its local animation ended.
            requested.stopUsingItem(requestedPlayer);
            owner(client).ledger.stop(InteractionLedger.Kind.USING,false,()->{});
        });
    }
    static void stopFoodUse(ClientPlayerInteractionManager requested, PlayerEntity requestedPlayer) {
        SurvivalAuthority.write(()->{
            ControlledEatingTask.guardFoodStop(); var client=context(); manager(client,requested); player(client,requestedPlayer);
            var own=owner(client);
            // This owned food request can outlive the local animation or an emergency's
            // generic USING claim. Send the native stop before the ordered inventory read.
            requested.stopUsingItem(requestedPlayer);
            own.ledger.stop(InteractionLedger.Kind.USING,false,()->{});
        });
    }
    public static void finishOwned() {
        SurvivalAuthority.requireScope(); Binding own=binding; if (own==null) return;
        Throwable failure=null;
        try { cancelBreaking(own.manager); } catch (RuntimeException|Error error) { failure=error; }
        try { stopUsing(own.manager,own.player); } catch (RuntimeException|Error error) {
            if (failure==null) failure=error; else if (failure!=error) failure.addSuppressed(error);
        }
        if (failure instanceof RuntimeException error) throw error;
        if (failure instanceof Error error) throw error;
    }
}
