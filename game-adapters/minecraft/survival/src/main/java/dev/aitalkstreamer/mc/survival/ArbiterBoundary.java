package dev.aitalkstreamer.mc.survival;

import dev.aitalkstreamer.mc.core.ControlArbiter;
import dev.aitalkstreamer.mc.core.Json;
import dev.aitalkstreamer.mc.InputOwner;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.input.Input;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.player.PlayerInventory;
import java.util.Objects;
import java.util.function.BooleanSupplier;

/** Uses the bridge's actual arbiter, with one immutable permit for the accepted root. */
public final class ArbiterBoundary implements SurvivalAuthority.Boundary {
    private final ControlArbiter control;
    private final ControlArbiter.Permit permit;
    private final String acceptedTask;
    private final InputOwner.Scope inputs;
    public ArbiterBoundary(ControlArbiter control, ControlArbiter.Permit permit, String acceptedTask) {
        this(control, permit, acceptedTask, null);
    }
    public ArbiterBoundary(ControlArbiter control, ControlArbiter.Permit permit, String acceptedTask, InputOwner inputs) {
        this.control = Objects.requireNonNull(control); this.permit = Objects.requireNonNull(permit);
        this.acceptedTask = Objects.requireNonNull(acceptedTask);
        this.inputs = inputs == null ? null : inputs.scope();
    }
    boolean inputsBound() { return inputs != null; }
    void key(KeyBinding key, boolean down) {
        if (inputs == null) throw new SurvivalAuthority.Denied();
        SurvivalAuthority.write(() -> inputs.key(key, down, control, permit));
    }
    void click(KeyBinding key) {
        if (inputs == null) throw new SurvivalAuthority.Denied();
        SurvivalAuthority.write(() -> inputs.click(key, control, permit));
    }
    void movement(ClientPlayerEntity player, Input replacement) {
        if (inputs == null) throw new SurvivalAuthority.Denied();
        SurvivalAuthority.write(() -> inputs.movement(player, replacement, control, permit));
    }
    void select(PlayerInventory inventory, int slot) {
        if (inputs == null) throw new SurvivalAuthority.Denied();
        SurvivalAuthority.write(() -> inputs.select(inventory, slot, control, permit));
    }
    void sneaking(Input input, boolean down) {
        if (inputs == null) throw new SurvivalAuthority.Denied();
        SurvivalAuthority.write(() -> inputs.sneaking(input, down, control, permit));
    }
    void movementAxis(Input input, InputOwner.MovementAxis axis, float value) {
        if (inputs == null) throw new SurvivalAuthority.Denied();
        SurvivalAuthority.write(() -> inputs.movementAxis(input, axis, value, control, permit));
    }
    void movementKey(Input input, InputOwner.MovementKey key, boolean value) {
        if (inputs == null) throw new SurvivalAuthority.Denied();
        SurvivalAuthority.write(() -> inputs.movementKey(input, key, value, control, permit));
    }
    private boolean matches(SurvivalAuthority.Context context) {
        return context.task().equals(acceptedTask) && context.epoch() == permit.epoch() && context.controller().equals(permit.controller())
                && context.lease().equals(permit.lease()) && context.world().equals(permit.world());
    }
    @Override public boolean current(SurvivalAuthority.Context context) {
        if (!matches(context) || !control.allowed()) return false;
        try { return control.permit().equals(permit); } catch (Json.Rejected revoked) { return false; }
    }
    @Override public void actuate(SurvivalAuthority.Context context, BooleanSupplier stillOpen, Runnable boundedWrite) {
        if (!matches(context)) throw new SurvivalAuthority.Denied();
        control.actuate(permit, () -> {
            if (!stillOpen.getAsBoolean()) throw new SurvivalAuthority.Denied();
            if (inputs != null) inputs.current();
            boundedWrite.run();
        });
    }
    @Override public void releaseOwnedInputs(SurvivalAuthority.Context context) {
        if (!matches(context)) throw new SurvivalAuthority.Denied();
        if (inputs == null) return;
        // Manual stop increments the epoch before client-thread cleanup. The original input
        // generation can still be restored, while a completed newer generation is untouched.
        if (!control.release(permit.epoch(), inputs::release)) inputs.release();
    }
}
