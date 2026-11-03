package dev.aitalkstreamer.mc;

import dev.aitalkstreamer.mc.core.ControlArbiter;
import dev.aitalkstreamer.mc.core.InputLedger;
import dev.aitalkstreamer.mc.core.PhysicalKeys;
import dev.aitalkstreamer.mc.core.OwnedValue;
import dev.aitalkstreamer.mc.core.OwnedFlag;
import dev.aitalkstreamer.mc.core.InputLeaseFence;
import dev.aitalkstreamer.mc.core.HotbarSelection;
import dev.aitalkstreamer.mc.core.NativeContext;
import dev.aitalkstreamer.mc.mixin.KeyBindingAccessor;
import dev.aitalkstreamer.mc.mixin.MinecraftInputInvoker;
import net.minecraft.client.input.Input;
import net.minecraft.client.input.KeyboardInput;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.player.PlayerInventory;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import org.lwjgl.glfw.GLFW;
import net.minecraft.util.Hand;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.function.BooleanSupplier;

/** Only synthetic keys owned by this adapter are released; physical held keys survive. */
public final class InputOwner {
    public enum MovementAxis { FORWARD, SIDEWAYS }
    public enum MovementKey { FORWARD, BACK, LEFT, RIGHT, JUMP, SNEAK }
    private final MinecraftClient client;
    private final InputLedger<KeyBinding> ledger;
    private final PhysicalKeys physicalKeys;
    private final Map<ClientPlayerEntity, OwnedValue<Input>> movement = new IdentityHashMap<>();
    private final Map<Input, OwnedFlag> sneaking = new IdentityHashMap<>();
    private final Map<ClientPlayerEntity, HotbarSelection> selected = new IdentityHashMap<>();
    private final InputLeaseFence lifetimes;
    private final BooleanSupplier beforeUse;
    public InputOwner(MinecraftClient client, PhysicalKeys physicalKeys) {
        this(client, physicalKeys, () -> true);
    }
    public InputOwner(MinecraftClient client, PhysicalKeys physicalKeys, BooleanSupplier beforeUse) {
        this.client = client;
        this.beforeUse = java.util.Objects.requireNonNull(beforeUse);
        this.physicalKeys = physicalKeys;
        ledger = new InputLedger<>((binding, physical) -> {
            binding.setPressed(physical);
            if (!physical && binding == client.options.useKey && client.player != null && client.player.isUsingItem() && client.interactionManager != null)
                client.interactionManager.stopUsingItem(client.player);
        }, this::physical);
        lifetimes = new InputLeaseFence(this::releaseOwned);
    }
    /** An immutable task-local handle, invalidated by any completed global restoration. */
    public Scope scope() { mainThread(); return new Scope(lifetimes.ticket()); }
    /** The synthetic ledger is independent of the physical key state. */
    public boolean owns(dev.aitalkstreamer.mc.core.HeldActionRouter.Action action) {
        mainThread();
        return ledger.owns(action == dev.aitalkstreamer.mc.core.HeldActionRouter.Action.USE
                ? client.options.useKey : client.options.attackKey);
    }
    public final class Scope {
        private final InputLeaseFence.Ticket ticket;
        private final NativeContext context;
        private Scope(InputLeaseFence.Ticket ticket) {
            this.ticket = ticket;
            context = new NativeContext(client.world, client.player, client.getNetworkHandler(), client.interactionManager);
        }
        public void current() {
            mainThread(); ticket.check();
            context.require(client.world, client.player, client.getNetworkHandler(), client.interactionManager);
            if (!client.player.isAlive() || !client.isWindowFocused() || client.isPaused())
                throw new IllegalStateException("GAME_INPUT_CONTEXT_INACTIVE");
        }
        public void key(KeyBinding key, boolean down, ControlArbiter control, ControlArbiter.Permit permit) {
            current(); InputOwner.this.key(key, down, control, permit);
        }
        public void click(KeyBinding key, ControlArbiter control, ControlArbiter.Permit permit) {
            current(); InputOwner.this.click(key, control, permit);
        }
        public void movement(ClientPlayerEntity player, Input replacement, ControlArbiter control, ControlArbiter.Permit permit) {
            current(); InputOwner.this.movement(player, replacement, control, permit);
        }
        public void select(PlayerInventory inventory, int slot, ControlArbiter control, ControlArbiter.Permit permit) {
            current(); InputOwner.this.select(inventory, slot, control, permit);
        }
        public void sneaking(Input input, boolean down, ControlArbiter control, ControlArbiter.Permit permit) {
            current(); InputOwner.this.sneaking(input, down, control, permit);
        }
        public void movementAxis(Input input, MovementAxis axis, float value, ControlArbiter control, ControlArbiter.Permit permit) {
            current(); InputOwner.this.movementAxis(input, axis, value, control, permit);
        }
        public void movementKey(Input input, MovementKey key, boolean value, ControlArbiter control, ControlArbiter.Permit permit) {
            current(); InputOwner.this.movementKey(input, key, value, control, permit);
        }
        public void release() { mainThread(); ticket.release(); }
    }
    private void mainThread() { if (!client.isOnThread()) throw new IllegalStateException("Game input must run on client thread"); }
    private boolean physical(KeyBinding binding) {
        if (!client.isWindowFocused()) { physicalKeys.lostFocus(); return false; }
        long window = client.getWindow().getHandle(); InputUtil.Key key = ((KeyBindingAccessor) binding).mcBridgeBoundKey();
        if (key.getCategory() == InputUtil.Type.MOUSE) return GLFW.glfwGetMouseButton(window, key.getCode()) == GLFW.GLFW_PRESS;
        if (key.getCategory() == InputUtil.Type.KEYSYM) return key.getCode() >= 0 && InputUtil.isKeyPressed(window, key.getCode());
        return physicalKeys.held(key.getCode(), code -> InputUtil.isKeyPressed(window, code));
    }
    public void press(KeyBinding key, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> ledger.press(key));
    }
    public void key(KeyBinding key, boolean down, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> { if (down) ledger.press(key); else ledger.release(key); });
    }
    public void click(KeyBinding key, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> {
            if (!ledger.owns(key)) throw new IllegalStateException("GAME_SYNTHETIC_KEY_NOT_OWNED");
            var invoke = (MinecraftInputInvoker) client;
            if (key == client.options.attackKey) invoke.mcBridgeAttack();
            else if (key == client.options.useKey && beforeUse.getAsBoolean()) invoke.mcBridgeUse();
            // Movement/jump/sprint use held state, with no extra queued wasPressed event.
        });
    }
    public void movement(ClientPlayerEntity player, Input replacement, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> {
            if (player != client.player || replacement == null) throw new IllegalStateException("GAME_PLAYER_INPUT_CONTEXT");
            movement.computeIfAbsent(player, p -> new OwnedValue<>(() -> p.input, input -> p.input = input)).replace(replacement);
        });
    }
    private void sneaking(Input input, boolean down, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> {
            if (client.player == null || input == null || input != client.player.input)
                throw new IllegalStateException("GAME_PLAYER_INPUT_CONTEXT");
            OwnedFlag flag = sneaking.computeIfAbsent(input, key -> new OwnedFlag(() -> key.sneaking, value -> key.sneaking = value));
            flag.replace(down);
            if (!flag.owned()) sneaking.remove(input);
        });
    }
    private void syntheticMovement(Input input) {
        if (client.player == null || input == null || client.player.input != input)
            throw new IllegalStateException("GAME_PLAYER_INPUT_CONTEXT");
        OwnedValue<Input> value = movement.get(client.player);
        if (value == null || !value.owns(input)) throw new IllegalStateException("GAME_INPUT_OWNER_CHANGED");
    }
    private void movementAxis(Input input, MovementAxis axis, float value, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> {
            syntheticMovement(input);
            if (axis == null || !Float.isFinite(value) || value < -1 || value > 1)
                throw new IllegalArgumentException("GAME_PLAYER_INPUT_CONTEXT");
            switch (axis) {
                case FORWARD -> input.movementForward = value;
                case SIDEWAYS -> input.movementSideways = value;
            }
        });
    }
    private void movementKey(Input input, MovementKey key, boolean value, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> {
            syntheticMovement(input);
            if (key == null) throw new IllegalArgumentException("GAME_PLAYER_INPUT_CONTEXT");
            switch (key) {
                case FORWARD -> input.pressingForward = value;
                case BACK -> input.pressingBack = value;
                case LEFT -> input.pressingLeft = value;
                case RIGHT -> input.pressingRight = value;
                case JUMP -> input.jumping = value;
                case SNEAK -> input.sneaking = value;
            }
        });
    }
    public void use(int slot, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> {
            selectOwned(slot); ledger.press(client.options.useKey);
            client.interactionManager.interactItem(client.player, Hand.MAIN_HAND);
        });
    }
    public void select(int slot, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> selectOwned(slot));
    }
    public void select(PlayerInventory inventory, int slot, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread(); control.actuate(permit, () -> {
            if (client.player == null || inventory != client.player.getInventory())
                throw new IllegalStateException("GAME_ITEM_HOTBAR_CONTEXT_CHANGED");
            selectOwned(slot);
        });
    }
    private void selectOwned(int slot) {
        if (slot < 0 || slot > 8 || client.player == null) throw new IllegalArgumentException("GAME_ITEM_HOTBAR_INVALID");
        var player = client.player; var connection = client.getNetworkHandler(); var world = client.world;
        var inventory = player.getInventory();
        if (connection == null || world == null) throw new IllegalStateException("GAME_ITEM_HOTBAR_CONTEXT_CHANGED");
        selected.computeIfAbsent(player, p -> new HotbarSelection(() -> inventory.selectedSlot,
                value -> inventory.selectedSlot = value,
                value -> connection.sendPacket(new net.minecraft.network.packet.c2s.play.UpdateSelectedSlotC2SPacket(value)),
                () -> client.player == p && client.world == world && client.getNetworkHandler() == connection
                        && p.getInventory() == inventory)).select(slot);
    }
    public void look(float yaw, float pitch, ControlArbiter control, ControlArbiter.Permit permit) {
        mainThread();
        if (!Float.isFinite(yaw) || !Float.isFinite(pitch) || pitch < -90 || pitch > 90) throw new IllegalArgumentException("Invalid view rotation");
        control.actuate(permit, () -> { client.player.setYaw(yaw); client.player.setPitch(pitch); });
    }
    public void release() {
        mainThread(); lifetimes.releaseAll();
    }
    private void releaseOwned() {
        mainThread();
        Throwable failure = null;
        try { ledger.release(); } catch (RuntimeException | Error error) { failure = error; }
        for (Input input : java.util.List.copyOf(sneaking.keySet())) {
            try {
                // Vanilla keyboard input follows the actual currently mapped physical key,
                // including key-up during the interrupted temporary suppression.
                if (input instanceof KeyboardInput) sneaking.get(input).release(() -> physical(client.options.sneakKey));
                else sneaking.get(input).release();
                sneaking.remove(input);
            } catch (RuntimeException | Error error) { if (failure == null) failure = error; else failure.addSuppressed(error); }
        }
        for (var player : java.util.List.copyOf(movement.keySet())) {
            try { movement.get(player).release(); movement.remove(player); }
            catch (RuntimeException | Error error) { if (failure == null) failure = error; else failure.addSuppressed(error); }
        }
        for (var player : java.util.List.copyOf(selected.keySet())) {
            try { selected.get(player).release(); selected.remove(player); }
            catch (RuntimeException | Error error) { if (failure == null) failure = error; else failure.addSuppressed(error); }
        }
        if (failure instanceof RuntimeException error) throw error;
        if (failure instanceof Error error) throw error;
    }
}
