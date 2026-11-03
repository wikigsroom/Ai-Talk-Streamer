package dev.aitalkstreamer.mc.survival;

import adris.altoclef.TaskCatalogue;
import adris.altoclef.tasks.movement.GetToBlockTask;
import adris.altoclef.tasksystem.Task;
import com.google.gson.JsonObject;
import dev.aitalkstreamer.mc.core.InventoryTarget;
import dev.aitalkstreamer.mc.core.BaseTarget;
import net.minecraft.client.MinecraftClient;
import net.minecraft.item.Item;
import net.minecraft.registry.Registries;
import net.minecraft.util.Identifier;
import net.minecraft.util.math.BlockPos;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Called after wire validation, world/rule/budget checks and durable task acceptance. */
public final class ControlledTaskFactory {
    public record Prepared(Task task, String recipeId, CraftPlan.Plan craftPlan) { }
    private ControlledTaskFactory() { }
    public static Prepared prepare(JsonObject goal, BaseTarget resolvedBase, InventoryTarget acceptedTarget) {
        SurvivalAuthority.requireScope();
        MinecraftClient client = MinecraftClient.getInstance();
        require(client.isOnThread() && client.player != null && client.world != null && client.getNetworkHandler() != null,
                "GAME_WORLD_UNAVAILABLE");
        return switch (str(goal, "skill")) {
            case "navigate" -> {
                JsonObject position = goal.getAsJsonObject("target");
                require(client.world.getRegistryKey().getValue().toString().equals(str(position, "dimension")), "GAME_DIMENSION_CHANGED");
                yield new Prepared(new GetToBlockTask(new BlockPos(position.get("x").getAsInt(), position.get("y").getAsInt(), position.get("z").getAsInt())), null, null);
            }
            case "return_base" -> {
                require(resolvedBase != null, "GAME_BASE_NOT_RESOLVED");
                require(str(goal, "base_id").equals(resolvedBase.baseId()), "GAME_BASE_CONTEXT_INVALID");
                require(client.world.getRegistryKey().getValue().toString().equals(resolvedBase.dimension()), "GAME_BASE_DIMENSION_CHANGED");
                yield new Prepared(new GetToBlockTask(new BlockPos(resolvedBase.x(), resolvedBase.y(), resolvedBase.z())), null, null);
            }
            case "gather" -> {
                Identifier id = Identifier.tryParse(str(goal, "item_id"));
                require(id != null && Registries.ITEM.containsId(id), "GAME_ITEM_UNKNOWN");
                Item item = Registries.ITEM.get(id); int count = Math.toIntExact(num(goal, "count"));
                require(TaskCatalogue.taskExists(item), "GAME_RESOURCE_NOT_CATALOGUED");
                require(acceptedTarget != null && acceptedTarget.itemId().equals(id.toString())
                        && acceptedTarget.requestedIncrement() == count && acceptedTarget.outputPerBatch() == 1,
                        "GAME_INVENTORY_TARGET_MISMATCH");
                int total = 0;
                for (int i = 0; i < client.player.getInventory().size(); i++) {
                    var stack = client.player.getInventory().getStack(i);
                    if (stack.isOf(item)) total = Math.addExact(total, stack.getCount());
                }
                require(acceptedTarget.baseline() == total, "GAME_INVENTORY_BASELINE_CHANGED");
                yield new Prepared(TaskCatalogue.getItemTask(item, acceptedTarget.targetTotal()), null, null);
            }
            case "craft" -> {
                var spec = CraftSpec.capture(goal, acceptedTarget);
                yield new Prepared(new ConfirmedCraftTask(spec), spec.plan.recipeId(), spec.plan);
            }
            default -> throw new IllegalArgumentException("GAME_CAPABILITY_UNAVAILABLE");
        };
    }
}
