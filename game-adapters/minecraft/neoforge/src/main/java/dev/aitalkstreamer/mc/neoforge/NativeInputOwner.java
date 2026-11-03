package dev.aitalkstreamer.mc.neoforge;

import com.mojang.blaze3d.platform.InputConstants;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.network.protocol.game.ServerboundSetCarriedItemPacket;
import net.minecraft.world.InteractionHand;
import net.minecraft.client.player.Input;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import org.lwjgl.glfw.GLFW;
import java.util.List;

/** Owns only this adapter's keys and selected slot, scoped to the actual original player. */
final class NativeInputOwner {
    private final Minecraft client;
    private final PhysicalKeys physicalKeys;
    private final InputLedger<KeyMapping> ledger;
    private final InputLeaseFence lifetimes;
    private NativeContext owner;
    private HotbarSelection selected;
    private OwnedValue<Input> movement;
    private Motion installedMotion;
    private boolean destroying;
    NativeInputOwner(Minecraft client, PhysicalKeys physicalKeys) {
        this.client = client; this.physicalKeys = physicalKeys;
        ledger = new InputLedger<>((key, physical) -> {
            key.setDown(physical);
            // An old task may release its own mapping, but cannot stop a replacement player's use.
            if (!physical && key == client.options.keyUse && sameOwner() && client.player.isUsingItem())
                client.gameMode.releaseUsingItem(client.player);
        }, this::physical);
        lifetimes = new InputLeaseFence(this::releaseOwned);
    }
    private void thread() { if (!client.isSameThread()) throw new IllegalStateException("GAME_WRONG_THREAD"); }
    private boolean sameOwner() {
        return owner != null && owner.world() == client.level && owner.player() == client.player
                && owner.connection() == client.getConnection() && owner.interactions() == client.gameMode;
    }
    private boolean physical(KeyMapping binding) {
        if (!client.isWindowActive()) { physicalKeys.lostFocus(); return false; }
        long window = client.getWindow().getWindow(); var key = binding.getKey();
        if (key.getType() == InputConstants.Type.MOUSE) return key.getValue() >= 0
                && GLFW.glfwGetMouseButton(window, key.getValue()) == GLFW.GLFW_PRESS;
        if (key.getType() == InputConstants.Type.KEYSYM) return key.getValue() >= 0 && InputConstants.isKeyDown(window, key.getValue());
        return physicalKeys.held(key.getValue(), code -> InputConstants.isKeyDown(window, code));
    }
    boolean physicallyActive() {
        thread(); return List.of(client.options.keyUp, client.options.keyDown, client.options.keyLeft, client.options.keyRight,
                client.options.keyJump, client.options.keyShift, client.options.keySprint, client.options.keyUse,
                client.options.keyAttack).stream().anyMatch(this::physical);
    }
    boolean ownsUse() { thread(); return ledger.owns(client.options.keyUse); }
    boolean allClear() { thread(); return ledger.empty() && movement == null && !destroying && selected == null; }
    com.google.gson.JsonObject proof() {
        thread(); return dev.aitalkstreamer.mc.core.Json.obj("movement_owned", movement != null,
                "synthetic_motion_attached", movement != null && movement.owns(installedMotion),
                "destroying", destroying, "selected_slot_owned", selected != null,
                "all_owned_inputs_clear", allClear());
    }
    Scope scope() {
        thread(); if (!ledger.empty() || selected != null || movement != null || destroying)
            throw new IllegalStateException("GAME_INPUT_RESTORE_PENDING");
        owner = new NativeContext(client.level, client.player, client.getConnection(), client.gameMode);
        return new Scope(lifetimes.ticket(), owner);
    }
    final class Scope {
        private final InputLeaseFence.Ticket ticket;
        private final NativeContext context;
        private Scope(InputLeaseFence.Ticket ticket, NativeContext context) { this.ticket = ticket; this.context = context; }
        private void live() {
            thread(); ticket.check(); context.require(client.level, client.player, client.getConnection(), client.gameMode);
            if (!client.player.isAlive() || !client.isWindowActive() || client.isPaused())
                throw new IllegalStateException("GAME_INPUT_CONTEXT_INACTIVE");
        }
        void current() { live(); if (client.screen != null) throw new IllegalStateException("GAME_INPUT_CONTEXT_INACTIVE"); }
        void currentMenu(net.minecraft.world.inventory.AbstractContainerMenu menu, net.minecraft.client.gui.screens.Screen screen) {
            live();
            if (client.player.containerMenu != menu || client.screen != screen)
                throw new IllegalStateException("GAME_CRAFT_HANDLER_CHANGED");
        }
        void click(net.minecraft.world.inventory.AbstractContainerMenu menu, net.minecraft.client.gui.screens.Screen screen,
                   int slot, int button, ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> {
                currentMenu(menu, screen);
                if (slot < 0 || slot >= menu.slots.size() || (button != 0 && button != 1))
                    throw new IllegalArgumentException("GAME_CRAFT_STEP_INVALID");
                client.gameMode.handleInventoryMouseClick(menu.containerId, slot, button,
                        net.minecraft.world.inventory.ClickType.PICKUP, client.player);
            });
        }
        void swapInventory(net.minecraft.world.inventory.InventoryMenu menu,int source,int hotbar,
                           ControlArbiter control,ControlArbiter.Permit permit){
            control.actuate(permit,()->{current();
                if(client.player.containerMenu!=menu || client.player.inventoryMenu!=menu || menu.getClass()!=net.minecraft.world.inventory.InventoryMenu.class
                        || source<9 || source>35 || hotbar<0 || hotbar>8 || !menu.getCarried().isEmpty())
                    throw new IllegalStateException("GAME_ITEM_HANDLER_INVALID");
                for(int i=0;i<5;i++)if(!menu.getSlot(i).getItem().isEmpty())throw new IllegalStateException("GAME_ITEM_GRID_NOT_EMPTY");
                client.gameMode.handleInventoryMouseClick(menu.containerId,source,hotbar,net.minecraft.world.inventory.ClickType.SWAP,client.player);
            });
        }
        void interact(net.minecraft.world.phys.BlockHitResult hit, ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { current();
                if (physical(client.options.keyUse)) throw new IllegalStateException("GAME_PHYSICAL_INPUT_ACTIVE");
                client.gameMode.useItemOn(client.player, InteractionHand.MAIN_HAND, hit);
            });
        }
        void closeMenu(net.minecraft.world.inventory.AbstractContainerMenu menu, net.minecraft.client.gui.screens.Screen screen,
                       ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { currentMenu(menu, screen); client.player.closeContainer(); });
        }
        void key(KeyMapping key, boolean down, ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { current();
                if (down) {
                    if (physical(key)) throw new IllegalStateException("GAME_PHYSICAL_INPUT_ACTIVE");
                    ledger.press(key);
                } else ledger.release(key);
            });
        }
        void select(int slot, ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { current(); selectOwned(slot); });
        }
        void use(int slot, ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { current();
                if (physical(client.options.keyUse)) throw new IllegalStateException("GAME_PHYSICAL_INPUT_ACTIVE");
                selectOwned(slot); ledger.press(client.options.keyUse);
                client.gameMode.useItem(client.player, InteractionHand.MAIN_HAND);
            });
        }
        void move(float forward, boolean jump, ControlArbiter control, ControlArbiter.Permit permit) {
            move(forward, jump, false, control, permit);
        }
        void move(float forward, boolean jump, boolean sprint, ControlArbiter control, ControlArbiter.Permit permit) {
            if (!Float.isFinite(forward) || forward < -1 || forward > 1) throw new IllegalArgumentException("GAME_MOVEMENT_INVALID");
            control.actuate(permit, () -> { current();
                if (sprint) {
                    if (forward < .8f || physical(client.options.keySprint)) throw new IllegalStateException("GAME_PHYSICAL_INPUT_ACTIVE");
                    ledger.press(client.options.keySprint);
                } else ledger.release(client.options.keySprint);
                if (movement == null) {
                    var player = client.player;
                    movement = new OwnedValue<>(() -> player.input, value -> player.input = value);
                    installedMotion = new Motion(this, control, permit);
                    movement.replace(installedMotion);
                }
                if (!movement.owns(installedMotion)) throw new IllegalStateException("GAME_INPUT_OWNER_CHANGED");
                installedMotion.forward = forward; installedMotion.jump = jump;
            });
        }
        void look(float yaw, float pitch, ControlArbiter control, ControlArbiter.Permit permit) {
            if (!Float.isFinite(yaw) || !Float.isFinite(pitch) || pitch < -90 || pitch > 90)
                throw new IllegalArgumentException("GAME_ROTATION_INVALID");
            control.actuate(permit, () -> { current(); client.player.setYRot(yaw); client.player.setXRot(pitch); });
        }
        void mine(BlockPos position, Direction face, ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { current();
                if (!destroying) { destroying = true; client.gameMode.startDestroyBlock(position, face); }
                else client.gameMode.continueDestroyBlock(position, face);
            });
        }
        void stopMining(ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { current();
                if (destroying) { client.gameMode.stopDestroyBlock(); destroying = false; }
            });
        }
        void attack(net.minecraft.world.entity.monster.Monster enemy, ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { current();
                if (physical(client.options.keyAttack) || enemy == null || !enemy.isAlive()
                        || enemy.level() != client.level || client.level.getEntity(enemy.getId()) != enemy
                        || client.player.distanceToSqr(enemy) > 9 || !client.player.hasLineOfSight(enemy)
                        || client.player.getAttackStrengthScale(0) < .9f)
                    throw new IllegalStateException("GAME_DEFENSE_TARGET_CHANGED");
                client.gameMode.attack(client.player, enemy); client.player.swing(InteractionHand.MAIN_HAND);
            });
        }
        void hunt(net.minecraft.world.entity.animal.Animal animal, java.util.UUID expected, String material,
                  ControlArbiter control, ControlArbiter.Permit permit) {
            control.actuate(permit, () -> { current();
                if (physical(client.options.keyAttack) || expected == null || animal == null
                        || !expected.equals(animal.getUUID()) || !NativeHunt.eligible(client, animal, material)
                        || client.player.distanceToSqr(animal) > 9 || !client.player.hasLineOfSight(animal)
                        || client.player.getAttackStrengthScale(0) < .9f)
                    throw new IllegalStateException("GAME_GATHER_TARGET_CHANGED");
                client.gameMode.attack(client.player, animal); client.player.swing(InteractionHand.MAIN_HAND);
            });
        }
        void release() { thread(); ticket.release(); }
    }
    /** Vanilla calls this continuation later: the original scope and permit are checked again there. */
    private final class Motion extends Input {
        private final Scope scope;
        private final ControlArbiter control;
        private final ControlArbiter.Permit permit;
        private float forward;
        private boolean jump;
        Motion(Scope scope, ControlArbiter control, ControlArbiter.Permit permit) {
            this.scope = scope; this.control = control; this.permit = permit;
        }
        private void clear() {
            leftImpulse = forwardImpulse = 0; up = down = left = right = jumping = shiftKeyDown = false;
        }
        @Override public void tick(boolean slowly, float factor) {
            thread();
            if (slowly && (!Float.isFinite(factor) || factor < 0 || factor > 1)) { clear(); return; }
            try {
                control.actuate(permit, () -> { scope.current();
                    if (movement == null || !movement.owns(this)) throw new IllegalStateException("GAME_INPUT_OWNER_CHANGED");
                    forwardImpulse = forward * (slowly ? factor : 1); leftImpulse = 0;
                    up = forward > 0; down = forward < 0; left = right = shiftKeyDown = false; jumping = jump;
                });
            } catch (dev.aitalkstreamer.mc.core.Json.Rejected | IllegalStateException revoked) {
                // This is our own detached input object, never another player's or a physical mapping.
                clear();
            }
        }
    }
    private void selectOwned(int slot) {
        if (slot < 0 || slot > 8) throw new IllegalArgumentException("GAME_ITEM_HOTBAR_INVALID");
        if (!sameOwner()) throw new IllegalStateException("GAME_INPUT_CONTEXT_CHANGED");
        if (selected == null) {
            var player = client.player; var world = client.level; var connection = client.getConnection();
            var inventory = player.getInventory(); var interactions = client.gameMode;
            selected = new HotbarSelection(() -> inventory.selected, value -> inventory.selected = value,
                    value -> connection.send(new ServerboundSetCarriedItemPacket(value)),
                    () -> client.player == player && client.level == world && client.getConnection() == connection
                            && client.gameMode == interactions && player.getInventory() == inventory);
        }
        selected.select(slot);
    }
    void release() { thread(); lifetimes.releaseAll(); }
    private void releaseOwned() {
        thread(); Throwable failure = null;
        try { ledger.release(); } catch (RuntimeException | Error error) { failure = error; }
        try {
            if (destroying) { if (sameOwner()) client.gameMode.stopDestroyBlock(); destroying = false; }
        } catch (RuntimeException | Error error) { if (failure == null) failure = error; else failure.addSuppressed(error); }
        try {
            if (installedMotion != null) installedMotion.clear();
            if (movement != null) { movement.release(); movement = null; installedMotion = null; }
        } catch (RuntimeException | Error error) { if (failure == null) failure = error; else failure.addSuppressed(error); }
        try { if (selected != null) { selected.release(); selected = null; } }
        catch (RuntimeException | Error error) { if (failure == null) failure = error; else failure.addSuppressed(error); }
        if (failure instanceof RuntimeException error) throw error;
        if (failure instanceof Error error) throw error;
        owner = null;
    }
}
