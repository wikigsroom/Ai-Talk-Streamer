package dev.aitalkstreamer.mc.neoforge;

import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.Shapes;

/** Real Minecraft ray intersections, using the production targeting function. No client or input. */
public final class NativeFoodAimFixture {
    private static int checks;
    private static void check(boolean value) {
        checks++;
        if (!value) throw new AssertionError("ray boundary " + checks);
    }
    public static void main(String[] args) {
        int legacyMisses = 0;
        for (BlockPos at : new BlockPos[]{BlockPos.ZERO, new BlockPos(1361, 75, -152)}) {
            var eye = new Vec3(at.getX() + .5, at.getY() + 1.62, at.getZ() + 2);
            for (double height : new double[]{.125, .5, .5625, 1.0}) {
                var shape = Shapes.box(0, 0, 0, 1, height, 1);
                if (shape.clip(eye, Vec3.atCenterOf(at), at) == null) legacyMisses++;
                var target = NativeFoodSources.aimPoint(at, shape);
                var hit = shape.clip(eye, target, at);
                check(hit != null);
                check(hit.getBlockPos().equals(at));
                check(shape.bounds().move(at).contains(target));
            }
        }
        check(legacyMisses == 4);
        check(NativeFoodSources.aimPoint(BlockPos.ZERO, Shapes.empty()).equals(Vec3.atCenterOf(BlockPos.ZERO)));
        System.out.println("PASS NativeFoodAimFixture " + checks + " checks; legacy misses=" + legacyMisses
                + "; eight actual shape rays hit; no game or input effects");
    }
}
