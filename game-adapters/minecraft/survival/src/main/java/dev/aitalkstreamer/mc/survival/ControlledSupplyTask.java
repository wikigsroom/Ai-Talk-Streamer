package dev.aitalkstreamer.mc.survival;

import adris.altoclef.AltoClef;
import adris.altoclef.tasks.resources.CollectFoodTask;
import adris.altoclef.tasksystem.Task;
import dev.aitalkstreamer.mc.core.LocalTaskFailure;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.util.math.Vec3d;
import java.util.*;

/** The existing food resource tree, with a fixed original owner, target and finite collection budget. */
public final class ControlledSupplyTask extends Task {
    private static ControlledSupplyTask active;
    private final SurvivalAuthority.Session owner;
    private final int target;
    private final CollectFoodTask collection;
    private final SupplyPolicy policy;
    private final Vec3d anchor;
    private boolean finished;
    private ControlledSupplyTask(int target) {
        owner=SurvivalAuthority.session(); this.target=target;
        collection=new CollectFoodTask(target); anchor=AltoClef.getInstance().getPlayer().getPos();
        policy=new SupplyPolicy(now(),target,new SupplyPolicy.Facts(inventoryNutrition(),0));
    }
    public static ControlledSupplyTask select(double units) {
        return SurvivalAuthority.effect(()->{
            int target=SupplyPolicy.validateTarget(units); var session=SurvivalAuthority.session();
            if (active != null && active.owner == session && !active.finished) return active;
            if (active == null || active.owner != session)
                SurvivalAuthority.owned(()->{if(active != null && active.owner == session)active=null;});
            return active=new ControlledSupplyTask(target);
        });
    }
    public static boolean retainsCraft() {return active!=null && active.owner.current() && ConfirmedCraftTask.retains(active);}
    public static void checkpoint() {
        SurvivalAuthority.requireScope();
        if (active == null || active.finished) return;
        var result=active.refresh();
        if (result.mode()==SupplyPolicy.Mode.FAILED) throw new LocalTaskFailure(result.reason());
    }
    private void scope() { if (SurvivalAuthority.session()!=owner) throw new SurvivalAuthority.Denied(); }
    private SupplyPolicy.Decision refresh() {
        return SurvivalAuthority.effect(()->{
            scope();var result=policy.observe(now(),new SupplyPolicy.Facts(inventoryNutrition(),
                    AltoClef.getInstance().getPlayer().getPos().squaredDistanceTo(anchor)), !ControlledCookingTask.busy() && !ControlledFoodCookingTask.busy() && !ControlledEatingTask.busy() && !ControlledEquipment.busy() && !ControlledStorage.blocksInventory());
            if (result.mode()==SupplyPolicy.Mode.FINISHED) finished=true;
            return result;
        });
    }
    /** Actual stack components, including custom food overrides and non-food special uses. */
    public static boolean allowedFood(ItemStack stack) {
        SurvivalAuthority.requireScope();
        if (stack == null || stack.isEmpty() || stack.isOf(Items.CHORUS_FRUIT)
                || stack.contains(DataComponentTypes.SUSPICIOUS_STEW_EFFECTS)) return false;
        var food=stack.get(DataComponentTypes.FOOD);
        if (food==null || food.nutrition()<=0 || food.nutrition()>20 || food.getEatTicks()<=0 || food.getEatTicks()>100
                || !Float.isFinite(food.saturation()) || food.saturation()<0) return false;
        return food.effects().stream().allMatch(effect->Float.isFinite(effect.probability())
                && effect.probability()>=0 && effect.probability()<=1
                && (effect.probability()==0 || effect.effect().getEffectType().value().isBeneficial()));
    }
    public static int inventoryNutrition() {
        return SurvivalAuthority.effect(()->{
            var inventory=AltoClef.getInstance().getPlayer().getInventory(); int nutrition=0;
            for (int slot=0;slot<inventory.size();slot++) {
                var stack=inventory.getStack(slot);
                if (allowedFood(stack)) nutrition=Math.addExact(nutrition,
                        Math.multiplyExact(stack.getCount(),stack.get(DataComponentTypes.FOOD).nutrition()));
            }
            return nutrition;
        });
    }
    /** Consumption uses main-inventory stacks and exact item-use eligibility; reserve admission still counts owned stock. */
    public static List<ItemStack> consumableFoods(AltoClef mod) {
        SurvivalAuthority.requireScope();var inventory=mod.getPlayer().getInventory();var slots=new HashSet<Integer>();
        for(int i=0;i<36;i++) {
            var stack=inventory.getStack(i);
            if(ControlledEatingTask.canEat(stack) && adris.altoclef.util.helpers.ItemHelper.canThrowAwayStack(mod,stack)) slots.add(i);
        }
        var available=ResourceMaterials.usable(slots);var result=new ArrayList<ItemStack>();
        for(var entry:new TreeMap<>(available).entrySet()) result.add(inventory.getStack(entry.getKey()).copyWithCount(entry.getValue()));
        return List.copyOf(result);
    }
    @Override protected void onStart() { scope(); }
    @Override protected Task onTick() {
        var result=refresh();
        return switch(result.mode()) {
            case COLLECT -> { setDebugState("Acquiring a bounded food reserve");yield collection; }
            case FINISHED -> null;
            case FAILED -> throw new LocalTaskFailure(result.reason());
        };
    }
    @Override public boolean isFinished() { return finished; }
    @Override protected void onStop(Task interruptTask) { }
    @Override protected boolean isEqual(Task other) {
        return other instanceof ControlledSupplyTask task && task.owner==owner && task.target==target;
    }
    @Override protected String toDebugString() { return "Controlled food reserve of "+target+" nutrition"; }
    private static long now() { return System.nanoTime()/1_000_000; }
}
