package dev.aitalkstreamer.mc.neoforge;

import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.CropBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.item.ItemNameBlockItem;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.Map;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Ordinary one-seed planting on explicit, loaded vanilla farmland. No world writes. */
public final class NativePlanting {
    private NativePlanting() { }
    private static final Map<String, String> CROPS = Map.of(
            "minecraft:wheat_seeds", "minecraft:wheat",
            "minecraft:carrot", "minecraft:carrots",
            "minecraft:potato", "minecraft:potatoes",
            "minecraft:beetroot_seeds", "minecraft:beetroots");

    public static String crop(String item) { return item == null ? null : CROPS.get(item); }
    static boolean crop(Block block) {
        return block instanceof CropBlock && CROPS.containsValue(BuiltInRegistries.BLOCK.getKey(block).toString());
    }
    static boolean confirmed(Block expected, BlockState state) {
        return state.getBlock() == expected && (!crop(expected) || ((CropBlock) expected).getAge(state) == 0);
    }
    static Vec3 top(BlockPos soil) { return new Vec3(soil.getX() + .5, soil.getY() + 15.0 / 16 - .0001, soil.getZ() + .5); }
    private static JsonObject registryProof;
    /** Call only from the initialized game client, where NeoForge's registries and flags exist. */
    static synchronized JsonObject runtimeProof() {
        if (registryProof == null) {
            var errors = new ArrayList<String>();int checks = 0;
            try {
                var seeds = new String[]{"minecraft:wheat_seeds", "minecraft:carrot", "minecraft:potato", "minecraft:beetroot_seeds"};
                var crops = new Block[]{Blocks.WHEAT, Blocks.CARROTS, Blocks.POTATOES, Blocks.BEETROOTS};
                for (int i = 0; i < seeds.length; i++) {
                    var block = crops[i];var plant = (CropBlock) block;
                    boolean[] outcomes = {crop(block), confirmed(block, plant.getStateForAge(0)),
                            !confirmed(block, plant.getStateForAge(1)), !confirmed(block, Blocks.AIR.defaultBlockState()),
                            !confirmed(block, ((CropBlock) crops[(i + 1) % 4]).getStateForAge(0)),
                            BuiltInRegistries.ITEM.get(ResourceLocation.parse(seeds[i])) instanceof ItemNameBlockItem item && item.getBlock() == block};
                    for (int n = 0; n < outcomes.length; n++) {checks++;if (!outcomes[n]) errors.add(seeds[i] + ":" + n);}
                }
                checks++;if (crop(Blocks.STONE)) errors.add("stone_is_not_a_crop");
                checks++;if (!confirmed(Blocks.STONE, Blocks.STONE.defaultBlockState())) errors.add("ordinary_block_receipt_regressed");
            } catch (RuntimeException | LinkageError error) {errors.add(error.getClass().getSimpleName());}
            registryProof = obj("source", "initialized_runtime_registry", "valid", errors.isEmpty() && checks == 26,
                    "checks", checks, "errors", errors, "world_writes", 0, "input_actions_issued", 0,
                    "actual_planting_claim", false);
        }
        return registryProof.deepCopy();
    }

    static BlockHitResult site(Minecraft client, BlockPos planted) {
        if (client.level == null || client.player == null || !client.level.hasChunkAt(planted)
                || planted.getY() <= client.level.getMinBuildHeight() || planted.getY() >= client.level.getMaxBuildHeight()
                || !client.level.getWorldBorder().isWithinBounds(planted)
                || !client.level.hasChunkAt(planted.below())) return null;
        if (!client.level.getBlockState(planted).isAir() || !client.level.getFluidState(planted).isEmpty()
                || !client.level.getBlockState(planted.below()).is(Blocks.FARMLAND)) return null;
        var eye = client.player.getEyePosition();
        var hit = client.level.clip(new ClipContext(eye, top(planted.below()),
                ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, client.player));
        return hit.getType() == HitResult.Type.BLOCK && hit.getDirection() == Direction.UP
                && hit.getBlockPos().equals(planted.below())
                && eye.distanceToSqr(hit.getLocation()) <= Math.pow(client.player.blockInteractionRange(), 2) ? hit : null;
    }
}
