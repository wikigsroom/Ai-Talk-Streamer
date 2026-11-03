package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.item.*;
import net.minecraft.world.phys.Vec3;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** Bounded ordinary defense and food run inside the original task's one permit and input owner. */
final class NativeSurvival implements ExecutorTaskSession.Runtime {
    private enum Phase { ACTION, FOOD, DEFENSE, ESCAPE_LANDING, ESCAPE, DONE }
    private static final Set<String> MOBS = Set.of("minecraft:zombie", "minecraft:husk", "minecraft:drowned",
            "minecraft:skeleton", "minecraft:stray", "minecraft:spider", "minecraft:cave_spider", "minecraft:silverfish", "minecraft:endermite");
    private final Minecraft client;
    private final NativeInputOwner inputs;
    private final NativeItemUse food;
    private final NativeTravel travel;
    private ExecutorTaskSession.Runtime action;
    private NativeInputOwner.Scope scope;
    private NativeContext owner;
    private JsonObject task;
    private InventoryTarget target;
    private BaseTarget base;
    private ControlArbiter control;
    private ControlArbiter.Permit permit;
    private Runnable finished;
    private Phase phase = Phase.DONE;
    private boolean childStarted, childDone;
    private boolean escapeSatisfiesOriginal;
    private Monster enemy;
    private int ticks, attacks, supplies, interventions, weapon, burningTicks;
    private float startingHealth, lowestHealth, enemyHealth;
    private Item selectedWeapon;
    private String lastOutcome;
    private int landingTicks, totalLandingTicks;

    NativeSurvival(Minecraft client, NativeInputOwner inputs, NativeItemUse food, NativeTravel travel) {
        this.client = client; this.inputs = inputs; this.food = food; this.travel = travel;
    }
    void bind(ExecutorTaskSession.Runtime action) { this.action = Objects.requireNonNull(action); }
    private void live() {
        owner.require(client.level, client.player, client.getConnection(), client.gameMode);
        require(control.allowed() && control.permit().equals(permit), "GAME_CONTROL_CONFLICT");
        require(client.player.isAlive() && client.isWindowActive() && !client.isPaused(), "GAME_GUI_BLOCKED");
    }
    private List<Monster> threats() {
        var result = client.level.getEntitiesOfClass(Monster.class, client.player.getBoundingBox().inflate(5),
                e -> e.isAlive() && client.player.distanceToSqr(e) <= 25);
        result.sort(Comparator.comparingDouble(client.player::distanceToSqr)); return result;
    }
    private int weapon() {
        for (int i = 0; i < 9; i++) {
            ItemStack stack = client.player.getInventory().getItem(i);
            if ((stack.getItem() instanceof SwordItem || stack.getItem() instanceof AxeItem)
                    && (!stack.isDamageableItem() || stack.getMaxDamage() - stack.getDamageValue() > 1)) return i;
        }
        return -1;
    }
    private Item food() {
        for (int i = 0; i < 36; i++) {
            var stack = client.player.getInventory().getItem(i);
            if (!stack.isEmpty() && NativeFoodPlan.edible(BuiltInRegistries.ITEM.getKey(stack.getItem()).toString())) return stack.getItem();
        }
        return null;
    }
    private void stopChild() {
        if (childStarted) {
            if (phase == Phase.FOOD) food.cancel();
            else if (phase == Phase.ESCAPE) travel.cancel();
            else action.cancel();
        }
        childStarted = false; childDone = false;
        if (scope != null) { scope.release(); scope = null; }
    }
    private boolean canInterrupt() {
        return client.screen == null && client.player.containerMenu == client.player.inventoryMenu
                && client.player.inventoryMenu.getCarried().isEmpty()
                && (phase != Phase.ACTION || action == travel);
    }
    private void beginAction() {
        phase = Phase.ACTION; childDone = false; childStarted = true;
        action.start(task.deepCopy(), control, permit, target, base, () -> childDone = true);
    }
    private void escape(Monster from) {
        stopChild(); ticks = 0; landingTicks = 0; enemy = from;
        if (from == null || client.player.isInWater() || client.player.isInLava())
            throw new LocalTaskFailure(DEFENSE_ESCAPE_TIMEOUT);
        // Knockback and an ordinary jump are transient states, not evidence
        // that no retreat exists. Release this task's old inputs and allow
        // vanilla physics to land before searching from the real footing.
        // live() still checks the original world, player and permit each tick.
        if (!client.player.onGround()) {
            phase = Phase.ESCAPE_LANDING; lastOutcome = "waiting_for_escape_landing"; return;
        }
        beginEscape(from);
    }
    private void beginEscape(Monster from) {
        phase = Phase.ESCAPE; ticks = 0;
        escapeSatisfiesOriginal=false;
        JsonObject original=task.getAsJsonObject("goal");
        if(str(original,"skill").equals("navigate") && away(original.getAsJsonObject("target"),from)
                && travel.check(original,null).get("allowed").getAsBoolean()) {
            childStarted=true;escapeSatisfiesOriginal=true;
            travel.start(task.deepCopy(),control,permit,null,null,()->childDone=true);return;
        }
        var candidates=new ArrayList<JsonObject>();
        var navigation=travel.navigation();
        if(navigation!=null)for(var row:navigation.getAsJsonArray("frontiers"))candidates.add(row.getAsJsonObject().getAsJsonObject("position"));
        candidates.sort(Comparator.comparingDouble((JsonObject p)->escapeClearance(p,from)).reversed());
        for(var position:candidates) {
            if(!away(position,from))continue;
            var goal=obj("skill","navigate","target",position.deepCopy(),"radius",1);
            if(!travel.check(goal,null).get("allowed").getAsBoolean())continue;
            var retreat=task.deepCopy();retreat.add("goal",goal);childStarted=true;
            travel.start(retreat,control,permit,null,null,()->childDone=true);return;
        }
        var p = client.player.blockPosition(); var delta = client.player.position().subtract(from.position());
        int dx = delta.x >= 0 ? 1 : -1, dz = delta.z >= 0 ? 1 : -1;
        for (int[] offset : List.of(new int[]{dx * 6, dz * 6}, new int[]{dx * 6, 0}, new int[]{0, dz * 6})) {
            var goal = obj("skill", "navigate", "target", obj("dimension", client.level.dimension().location().toString(),
                    "x", p.getX() + offset[0], "y", p.getY(), "z", p.getZ() + offset[1]), "radius", 1);
            if (!away(goal.getAsJsonObject("target"),from)) continue;
            if (!travel.check(goal, null).get("allowed").getAsBoolean()) continue;
            var retreat = task.deepCopy(); retreat.add("goal", goal); childStarted = true;
            travel.start(retreat, control, permit, null, null, () -> childDone = true); return;
        }
        throw new LocalTaskFailure(DEFENSE_ESCAPE_TIMEOUT);
    }
    private double distance(JsonObject position,Monster from) {
        return from.position().distanceToSqr(new Vec3(num(position,"x")+.5,num(position,"y"),num(position,"z")+.5));
    }
    private boolean away(JsonObject position,Monster from) {
        return str(position,"dimension").equals(client.level.dimension().location().toString())
                && distance(position,from)>client.player.distanceToSqr(from)+.5
                && avoidsOtherThreats(position);
    }
    private boolean avoidsOtherThreats(JsonObject position) {
        for(var other:client.level.getEntitiesOfClass(Monster.class,client.player.getBoundingBox().inflate(16),
                e->e.isAlive() && client.player.distanceToSqr(e)<=256))
            if(distance(position,other)<Math.min(16,client.player.distanceToSqr(other)))return false;
        return true;
    }
    private double escapeClearance(JsonObject position,Monster from) {
        double nearest=distance(position,from);
        for(var other:client.level.getEntitiesOfClass(Monster.class,client.player.getBoundingBox().inflate(16),
                e->e.isAlive() && client.player.distanceToSqr(e)<=256))nearest=Math.min(nearest,distance(position,other));
        return nearest;
    }
    private boolean intervene() {
        live(); var nearby = threats(); int hunger = client.player.getFoodData().getFoodLevel();
        if (client.player.isInLava() || client.player.getAirSupply() < 40)
            throw new LocalTaskFailure(SURVIVAL_ENVIRONMENT_UNSUPPORTED);
        // Travel owns the bounded ordinary swim-to-bank path. Do not replace it
        // with a grounded-only retreat, attack or inventory food intervention.
        if (client.player.isInWater()) return false;
        if (client.player.isOnFire()) {
            if (!nearby.isEmpty()) { escape(nearby.getFirst()); return true; }
            return false;
        }
        if (!nearby.isEmpty()) {
            if (!canInterrupt()) throw new LocalTaskFailure(DEFENSE_RANGE_LIMIT);
            if (++interventions > 3) throw new LocalTaskFailure(DEFENSE_TIMEOUT);
            Monster first = nearby.getFirst(); int slot = weapon();
            if (nearby.size() != 1 || !MOBS.contains(BuiltInRegistries.ENTITY_TYPE.getKey(first.getType()).toString())
                    || client.player.getHealth() < 12 || hunger < 6 || slot < 0) { escape(first); return true; }
            stopChild(); phase = Phase.DEFENSE; ticks = attacks = 0; enemy = first; weapon = slot;
            startingHealth = lowestHealth = client.player.getHealth(); enemyHealth = first.getHealth();
            selectedWeapon = client.player.getInventory().getItem(weapon).getItem();
            scope = inputs.scope(); scope.select(weapon, control, permit); lastOutcome = "defending"; return true;
        }
        if (hunger <= 14 && canInterrupt()) {
            Item meal = food();
            if (meal == null) { if (hunger <= 6) throw new LocalTaskFailure(SUPPLY_NO_PROGRESS); return false; }
            if (++supplies > 3) throw new LocalTaskFailure(SUPPLY_RANGE_LIMIT);
            stopChild(); phase = Phase.FOOD; ticks = 0;
            var eating = task.deepCopy(); eating.add("goal", obj("skill", "use_item", "item_id", BuiltInRegistries.ITEM.getKey(meal).toString(), "purpose", "eat"));
            childStarted = true; food.start(eating, control, permit, null, null, () -> childDone = true); return true;
        }
        return false;
    }
    private void environmentalDanger() {
        if (client.player.isInLava() || client.player.getAirSupply() < 40)
            throw new LocalTaskFailure(SURVIVAL_ENVIRONMENT_UNSUPPORTED);
        // Do not abandon a partly clicked crafting/menu transaction. Its own
        // bounded server-confirmation path must finish or fail first. At a clean
        // gameplay boundary work can fail honestly and replan without pausing.
        if (phase == Phase.ACTION && action != travel
                && (client.player.isOnFire() || !threats().isEmpty())
                && client.screen == null && client.player.containerMenu == client.player.inventoryMenu
                && client.player.inventoryMenu.getCarried().isEmpty())
            throw new LocalTaskFailure(DEFENSE_HAZARD_INTERRUPTED);
    }
    @Override public void start(JsonObject task, ControlArbiter control, ControlArbiter.Permit permit,
                                InventoryTarget target, BaseTarget base, Runnable finished) {
        require(phase == Phase.DONE, "GAME_TASK_BUSY"); this.task = task.deepCopy(); this.control = control;
        this.permit = permit; this.target = target; this.base = base; this.finished = finished;
        owner = new NativeContext(client.level, client.player, client.getConnection(), client.gameMode);
        supplies = interventions = attacks = ticks = burningTicks = landingTicks = totalLandingTicks = 0;
        childStarted = childDone = false; enemy = null; lastOutcome = null;
        phase = Phase.ACTION;
        live(); environmentalDanger();
        // Explicit item use and in-progress workstation actions retain their own complete receipt path.
        if (action != travel || !intervene()) beginAction();
    }
    @Override public void tick() {
        if (phase == Phase.DONE) return; live(); environmentalDanger(); ticks++;
        if (client.player.isOnFire()) burningTicks++;
        if (phase == Phase.DEFENSE) {
            scope.current(); lowestHealth = Math.min(lowestHealth, client.player.getHealth());
            if (client.player.isOnFire() || client.player.isInLava() || client.player.getAirSupply() < 40
                    || lowestHealth < 10 || startingHealth - lowestHealth > 6 || threats().size() > 1) { escape(enemy); return; }
            if (enemy.isDeadOrDying()) { lastOutcome = "observed_dead"; stopChild(); beginAction(); return; }
            if (client.level.getEntity(enemy.getId()) != enemy) throw new LocalTaskFailure(DEFENSE_NO_PROGRESS);
            if (client.player.distanceToSqr(enemy) > 49) { lastOutcome = "disengaged"; stopChild(); beginAction(); return; }
            if (ticks > 300 || attacks > 30) throw new LocalTaskFailure(DEFENSE_TIMEOUT);
            var held = client.player.getInventory().getItem(weapon);
            if (!held.is(selectedWeapon) || client.player.getInventory().selected != weapon
                    || held.isDamageableItem() && held.getMaxDamage() - held.getDamageValue() <= 1)
                throw new LocalTaskFailure(DEFENSE_NO_PROGRESS);
            Vec3 delta = enemy.getEyePosition().subtract(client.player.getEyePosition());
            scope.look((float)(Math.toDegrees(Math.atan2(delta.z, delta.x)) - 90),
                    (float)-Math.toDegrees(Math.atan2(delta.y, Math.sqrt(delta.x * delta.x + delta.z * delta.z))), control, permit);
            if (client.player.distanceToSqr(enemy) <= 9 && client.player.hasLineOfSight(enemy)
                    && client.player.getAttackStrengthScale(0) >= .9f) { scope.attack(enemy, control, permit); attacks++; }
            if (ticks > 100 && enemy.getHealth() >= enemyHealth) throw new LocalTaskFailure(DEFENSE_NO_PROGRESS);
            return;
        }
        if (phase == Phase.FOOD) {
            if (!threats().isEmpty()) throw new LocalTaskFailure(SUPPLY_NO_PROGRESS);
            if (ticks > 200) throw new LocalTaskFailure(SUPPLY_TIMEOUT);
            food.tick();
            if (childDone) { lastOutcome = "food_server_confirmed"; stopChild(); beginAction(); }
            return;
        }
        if (phase == Phase.ESCAPE_LANDING) {
            totalLandingTicks++;
            var landing = NativeEscapeLanding.observe(client.player.onGround(),
                    client.player.isInWater(), client.player.isInLava(), ++landingTicks);
            if (landing == NativeEscapeLanding.State.READY) {
                lastOutcome = "escape_landed"; beginEscape(enemy);
            } else if (landing != NativeEscapeLanding.State.WAITING) {
                lastOutcome = "escape_landing_" + landing.name().toLowerCase(Locale.ROOT);
                throw new LocalTaskFailure(DEFENSE_ESCAPE_TIMEOUT);
            }
            return;
        }
        if (phase == Phase.ESCAPE) {
            if (ticks > 200) throw new LocalTaskFailure(DEFENSE_ESCAPE_TIMEOUT);
            travel.tick();
            if (childDone) {
                lastOutcome="retreated_replanning";stopChild();
                if(escapeSatisfiesOriginal){phase=Phase.DONE;finished.run();}
                else throw new LocalTaskFailure(DEFENSE_RETREAT_COMPLETE);
            }
            return;
        }
        if (action == travel && intervene()) return;
        action.tick();
        if (childDone) { phase = Phase.DONE; finished.run(); }
    }
    @Override public void cancel() { stopChild(); phase = Phase.DONE; }
    @Override public boolean allowsGui() { return phase == Phase.ACTION && action.allowsGui(); }
    @Override public CraftReceipt craftReceipt() { return action == null ? null : action.craftReceipt(); }
    @Override public ItemUseReceipt itemUseReceipt() { return action == null ? null : action.itemUseReceipt(); }
    boolean ownsAttack() { return phase == Phase.DEFENSE; }
    boolean eating() { return phase == Phase.FOOD; }
    JsonObject proof() { return obj("phase", phase.name(), "attacks", attacks, "supply_actions", supplies,
            "escape_landing_ticks", totalLandingTicks, "escape_landing_input_actions", 0,
            "burning_ticks", burningTicks, "ordinary_fire_does_not_pause_world", true,
            "interventions", interventions, "outcome", lastOutcome, "original_permit_epoch", permit == null ? null : permit.epoch(),
            "enemy_id", enemy == null ? null : enemy.getId(), "enemy_health", enemy == null ? null : enemy.getHealth()); }
}
