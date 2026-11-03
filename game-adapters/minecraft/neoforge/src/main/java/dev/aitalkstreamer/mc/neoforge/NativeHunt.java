package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.animal.Animal;
import net.minecraft.world.item.*;
import net.minecraft.world.phys.Vec3;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;

/** One bounded livestock collection task, using the original permit and ordinary walking/attacks. */
final class NativeHunt implements ExecutorTaskSession.Runtime {
    private enum Phase { DONE, APPROACH, ATTACK, PICKUP }
    private final Minecraft client;
    private final NativeInputOwner inputs;
    private final NativeTravel travel;
    private Phase phase = Phase.DONE;
    private NativeContext owner;
    private NativeInputOwner.Scope scope;
    private ControlArbiter control;
    private ControlArbiter.Permit permit;
    private JsonObject task;
    private InventoryTarget target;
    private Runnable finished;
    private Animal animal;
    private UUID animalId;
    private String entityType, itemId;
    private Item material, weaponItem;
    private int weaponSlot, ticks, attacks, routes, inventoryPackets, confirmedInventory;
    private boolean childDone, childActive, observedDeath;

    NativeHunt(Minecraft client, NativeInputOwner inputs, NativeTravel travel) {
        this.client = client; this.inputs = inputs; this.travel = travel;
    }
    static boolean eligible(Minecraft client, Animal entity, String item) {
        return entity != null && client.level != null && client.player != null
                && entity.level() == client.level && client.level.getEntity(entity.getId()) == entity
                && NativeHuntPlan.eligible(BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString(), item,
                entity.isAlive(), entity.isBaby(), entity.hasCustomName(), entity.isLeashed(), entity.isPassenger(),
                entity.isVehicle(), client.player.distanceToSqr(entity));
    }
    private int count() {
        int total = 0;
        for (int i = 0; i < 36; i++) {
            var stack = client.player.getInventory().getItem(i);
            if (stack.is(material)) total += stack.getCount();
        }
        return total;
    }
    private int weapon() {
        for (int i = 0; i < 9; i++) {
            var stack = client.player.getInventory().getItem(i);
            if ((stack.getItem() instanceof AxeItem || stack.getItem() instanceof SwordItem)
                    && (!stack.isDamageableItem() || stack.getMaxDamage() - stack.getDamageValue() > 3)) return i;
        }
        return -1;
    }
    private void ready() {
        require(client.isSameThread(), "GAME_WRONG_THREAD");
        require(client.level != null && client.player != null && client.gameMode != null && client.getConnection() != null,
                "GAME_WORLD_UNAVAILABLE");
        require(client.player.isAlive() && client.isWindowActive() && !client.isPaused() && client.screen == null
                && client.player.containerMenu == client.player.inventoryMenu && client.player.inventoryMenu.getCarried().isEmpty()
                && !client.player.isUsingItem(), "GAME_GUI_BLOCKED");
        require(!client.player.getAbilities().instabuild && !client.player.isSpectator(), "GAME_SURVIVAL_REQUIRED");
        require(NativeHuntPlan.playerReady(client.player.getHealth(), client.player.getFoodData().getFoodLevel())
                && !client.player.isInWater() && !client.player.isInLava() && !client.player.isOnFire()
                && !client.player.isPassenger() && !client.player.isFallFlying() && !client.player.onClimbable(),
                "GAME_GATHER_PRECONDITION_FAILED");
    }
    private List<Animal> animals(String item) {
        var candidates = client.level.getEntitiesOfClass(Animal.class, client.player.getBoundingBox().inflate(16, 6, 16),
                e -> eligible(client, e, item) && Math.abs(e.getY() - client.player.getY()) <= 6
                        && client.player.hasLineOfSight(e));
        candidates.sort(Comparator.comparingDouble(client.player::distanceToSqr));
        return candidates;
    }
    private JsonObject route(Animal entity) {
        var p = entity.blockPosition();
        for (int[] delta : List.of(new int[]{0,0}, new int[]{1,0}, new int[]{-1,0}, new int[]{0,1}, new int[]{0,-1})) {
            var at = p.offset(delta[0], 0, delta[1]);
            var goal = obj("skill", "navigate", "target", obj("dimension", client.level.dimension().location().toString(),
                    "x", at.getX(), "y", at.getY(), "z", at.getZ()), "radius", 1);
            if (travel.check(goal, null).get("allowed").getAsBoolean()) return goal;
        }
        return null;
    }
    JsonObject check(JsonObject goal) {
        String reason = null;
        try {
            ready();
            String item = str(goal, "item_id");
            require(str(goal, "skill").equals("gather") && NativeHuntPlan.material(item) && num(goal, "count") == 1,
                    "GAME_GATHER_UNSUPPORTED");
            require(weapon() >= 0, "GAME_GATHER_TOOL_UNAVAILABLE");
            require(client.player.getInventory().getFreeSlot() >= 0, "GAME_INVENTORY_FULL");
            boolean admitted = false;
            for (Animal entity : animals(item).stream().limit(4).toList())
                if (client.player.distanceToSqr(entity) <= 9 || route(entity) != null) { admitted = true; break; }
            require(admitted, "GAME_GATHER_RESOURCE_UNAVAILABLE");
        } catch (Rejected denied) { reason = denied.code; }
        catch (LocalTaskFailure denied) { reason = denied.code(); }
        return obj("allowed", reason == null, "reason", reason, "source", "runtime_client", "unknown_fields",
                List.of("future_animal_movement", "future_drops_and_inventory_causality", "server_attack_rules"));
    }
    @Override public void start(JsonObject task, ControlArbiter control, ControlArbiter.Permit permit,
                                InventoryTarget target, BaseTarget base, Runnable finished) {
        ready(); require(phase == Phase.DONE, "GAME_TASK_BUSY");
        require(check(task.getAsJsonObject("goal")).get("allowed").getAsBoolean(), "GAME_GATHER_PRECONDITION_FAILED");
        this.task = task.deepCopy(); this.control = control; this.permit = permit; this.target = target; this.finished = finished;
        itemId = str(task.getAsJsonObject("goal"), "item_id");
        material = BuiltInRegistries.ITEM.get(ResourceLocation.parse(itemId));
        require(target != null && target.itemId().equals(itemId) && target.requestedIncrement() == 1
                && target.baseline() == count(), "GAME_INVENTORY_COUNT_INVALID");
        owner = new NativeContext(client.level, client.player, client.getConnection(), client.gameMode);
        animal = animals(itemId).stream().limit(4).filter(e -> client.player.distanceToSqr(e) <= 9 || route(e) != null)
                .findFirst().orElseThrow(() -> new LocalTaskFailure(GATHER_RESOURCE_UNAVAILABLE));
        animalId = animal.getUUID(); entityType = BuiltInRegistries.ENTITY_TYPE.getKey(animal.getType()).toString();
        ticks = attacks = routes = inventoryPackets = 0; confirmedInventory = target.baseline();
        observedDeath = childDone = childActive = false; phase = Phase.ATTACK;
    }
    private void live() {
        ready(); owner.require(client.level, client.player, client.getConnection(), client.gameMode);
        require(control.allowed() && control.permit().equals(permit), "GAME_CONTROL_CONFLICT");
        if (++ticks > 600) throw new LocalTaskFailure(GATHER_NO_PROGRESS);
    }
    private void release() { if (scope != null) { scope.release(); scope = null; } }
    private void walk(JsonObject goal, boolean pickup) {
        release();
        if (++routes > 8) throw new LocalTaskFailure(GATHER_NO_PROGRESS);
        var child = task.deepCopy(); child.add("goal", goal);
        childDone = false; childActive = true; phase = pickup ? Phase.PICKUP : Phase.APPROACH;
        travel.start(child, control, permit, pickup ? target : null, null, () -> childDone = true);
    }
    @Override public void tick() {
        if (phase == Phase.DONE) return; live();
        if (inventoryPackets > 0 && confirmedInventory >= target.targetTotal() && count() >= target.targetTotal()) {
            stop(); finished.run(); return;
        }
        if (phase == Phase.APPROACH || phase == Phase.PICKUP) {
            travel.tick();
            if (childDone) { childActive = false; phase = Phase.ATTACK; }
            return;
        }
        if (animal.isDeadOrDying()) {
            observedDeath = true;
            var goal = obj("skill", "gather", "item_id", itemId, "count", 1);
            if (travel.check(goal, null).get("allowed").getAsBoolean()) walk(goal, true);
            else if (ticks > 560) throw new LocalTaskFailure(GATHER_NO_PROGRESS);
            return;
        }
        if (!animalId.equals(animal.getUUID()) || !eligible(client, animal, itemId))
            throw new LocalTaskFailure(GATHER_CONTEXT_CHANGED);
        if (client.player.distanceToSqr(animal) > 9 || !client.player.hasLineOfSight(animal)) {
            var goal = route(animal);
            if (goal == null) throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
            walk(goal, false); return;
        }
        if (scope == null) {
            weaponSlot = weapon(); if (weaponSlot < 0) throw new LocalTaskFailure(GATHER_TOOL_UNAVAILABLE);
            weaponItem = client.player.getInventory().getItem(weaponSlot).getItem();
            scope = inputs.scope(); scope.select(weaponSlot, control, permit);
        }
        var held = client.player.getInventory().getItem(weaponSlot);
        if (client.player.getInventory().selected != weaponSlot || !held.is(weaponItem)
                || held.isDamageableItem() && held.getMaxDamage() - held.getDamageValue() <= 1)
            throw new LocalTaskFailure(GATHER_TOOL_UNAVAILABLE);
        Vec3 delta = animal.getEyePosition().subtract(client.player.getEyePosition());
        scope.look((float)(Math.toDegrees(Math.atan2(delta.z, delta.x)) - 90),
                (float)-Math.toDegrees(Math.atan2(delta.y, Math.hypot(delta.x, delta.z))), control, permit);
        if (client.player.getAttackStrengthScale(0) >= .9f) {
            if (attacks >= 12) throw new LocalTaskFailure(GATHER_NO_PROGRESS);
            scope.hunt(animal, animalId, itemId, control, permit); attacks++;
        }
    }
    void inventoryPacket() {
        if (phase == Phase.DONE || !client.isSameThread() || client.player == null || owner == null) return;
        if (owner.world() != client.level || owner.player() != client.player || owner.connection() != client.getConnection()
                || owner.interactions() != client.gameMode) return;
        inventoryPackets++; confirmedInventory = count();
    }
    private void stop() { if (childActive) travel.cancel(); childActive = false; release(); phase = Phase.DONE; }
    @Override public void cancel() { stop(); }
    boolean active() { return phase != Phase.DONE; }
    JsonObject proof() { return obj("active", active(), "phase", phase.name().toLowerCase(Locale.ROOT),
            "task_id", task == null ? null : nullable(task, "task_id"), "entity_uuid", animalId == null ? null : animalId.toString(),
            "entity_type", entityType, "raw_item_id", itemId, "attacks", attacks, "route_attempts", routes,
            "observed_death", observedDeath, "server_inventory_packets", inventoryPackets, "confirmed_inventory", confirmedInventory,
            "raw_material_is_edible", false, "world_data_injection", false); }
}
