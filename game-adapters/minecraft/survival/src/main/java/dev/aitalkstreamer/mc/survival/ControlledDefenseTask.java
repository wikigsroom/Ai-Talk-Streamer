package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasks.entity.KillEntityTask;
import adris.altoclef.tasks.movement.RunAwayFromHostilesTask;
import adris.altoclef.tasksystem.Task;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import net.minecraft.entity.Entity;
import net.minecraft.entity.LivingEntity;
import net.minecraft.entity.boss.WitherEntity;
import net.minecraft.entity.boss.dragon.EnderDragonEntity;
import net.minecraft.entity.mob.CreeperEntity;
import net.minecraft.entity.mob.EndermanEntity;
import net.minecraft.entity.mob.HostileEntity;
import net.minecraft.entity.mob.WardenEntity;
import net.minecraft.item.SwordItem;
import net.minecraft.util.math.Vec3d;
import java.util.Objects;

/** Internal defense subtask; it cannot create a public goal or acquire another root. */
public final class ControlledDefenseTask extends Task {
    private static ControlledDefenseTask active;
    private final Entity target;
    private final SurvivalAuthority.Session owner;
    private final KillEntityTask pursuit;
    private final RunAwayFromHostilesTask retreat = new RunAwayFromHostilesTask(16, true);
    private final DefensePolicy policy;
    private final Vec3d anchor;
    private boolean finished;
    private ControlledDefenseTask(Entity target) {
        this.target = Objects.requireNonNull(target); owner = SurvivalAuthority.session();
        pursuit = new KillEntityTask(target); anchor = AltoClef.getInstance().getPlayer().getPos();
        policy = new DefensePolicy(now());
    }
    public static ControlledDefenseTask select(Entity candidate) {
        return SurvivalAuthority.effect(()->{
            var session=SurvivalAuthority.session();
            if (active!=null && active.owner==session && !active.finished) return active;
            if (active==null || active.owner!=session) {
                SurvivalAuthority.owned(()->{if (active!=null && active.owner==session) active=null;});
            }
            return active=new ControlledDefenseTask(candidate);
        });
    }
    /** Reflex/vanilla attacks share the encounter's original target, risk assessment and clock. */
    static boolean attackAllowed(Entity requested) {
        SurvivalAuthority.requireScope();
        if (active==null) return true;
        active.scope(); active.refresh();
        return active.policy.permitsAttack(requested==active.target,
                requested instanceof net.minecraft.entity.projectile.FireballEntity);
    }
    /** Check even while food/fire/fall handling temporarily owns the upstream scheduler. */
    public static void checkpoint() {
        SurvivalAuthority.requireScope();
        if (active==null) return;
        active.scope();var decision=active.refresh();
        if (decision.mode()==DefensePolicy.Mode.FAILED) throw new LocalTaskFailure(decision.reason());
    }
    private void scope() {
        if (SurvivalAuthority.session() != owner) throw new SurvivalAuthority.Denied();
    }
    @Override protected void onStart() {
        scope();
        // Retain both the selected entity and deadline when another survival chain interrupts.
    }
    private DefensePolicy.Decision refresh() { return SurvivalAuthority.effect(this::sample); }
    private DefensePolicy.Decision sample() {
        scope(); var mod = AltoClef.getInstance(); var player = mod.getPlayer(); var world = mod.getWorld();
        boolean present = target.getWorld() == world && world.getEntityById(target.getId()) == target && !target.isRemoved();
        boolean alive = present && target.isAlive();
        var threats = world.getEntitiesByClass(HostileEntity.class, player.getBoundingBox().expand(16),
                entity -> entity.isAlive() && !entity.isRemoved());
        double closest = threats.stream().mapToDouble(player::squaredDistanceTo).min().orElse(1024);
        boolean sword = false;
        for (int slot = 0; slot < player.getInventory().size(); slot++) {
            var stack = player.getInventory().getStack(slot);
            if (!stack.isEmpty() && stack.getItem() instanceof SwordItem) { sword = true; break; }
        }
        boolean dangerous = target instanceof CreeperEntity || target instanceof WardenEntity
                || target instanceof WitherEntity || target instanceof EnderDragonEntity || target instanceof EndermanEntity;
        var facts = new DefensePolicy.Facts(present, alive, target instanceof HostileEntity,
                target instanceof LivingEntity living ? Math.max(0, living.getHealth()) : 0,
                player.squaredDistanceTo(target), player.getPos().squaredDistanceTo(anchor),
                player.getHealth(), player.getMaxHealth(), player.getHungerManager().getFoodLevel(), Math.max(0, player.getAir()),
                player.isSubmergedInWater(), player.isOnFire(), player.isInLava(), dangerous, sword,
                Math.max(0, player.getArmor()), threats.size(), closest);
        var decision=policy.observe(now(),facts);
        if (decision.mode()==DefensePolicy.Mode.FINISHED) finished=true;
        return decision;
    }
    @Override protected Task onTick() {
        scope();var decision=refresh();
        return switch (decision.mode()) {
            case FIGHT -> { setDebugState("Defending against the selected entity"); yield pursuit; }
            case RETREAT -> { setDebugState("Leaving the unsafe encounter"); yield retreat; }
            case FINISHED -> { finished = true; yield null; }
            case FAILED -> throw new LocalTaskFailure(decision.reason());
        };
    }
    @Override public boolean isFinished() { return finished; }
    @Override protected void onStop(Task interruptTask) { }
    @Override protected boolean isEqual(Task other) {
        return other instanceof ControlledDefenseTask task && task.target == target && task.owner == owner;
    }
    @Override protected String toDebugString() { return "Controlled defense of one original target"; }
    private static long now() { return System.nanoTime() / 1_000_000; }
}
