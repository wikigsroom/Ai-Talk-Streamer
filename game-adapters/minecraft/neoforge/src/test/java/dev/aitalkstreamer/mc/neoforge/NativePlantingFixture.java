package dev.aitalkstreamer.mc.neoforge;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.Shapes;
import java.util.Objects;

/** Policy and supplied geometry only. Registry checks run in the initialized real client. */
public final class NativePlantingFixture {
    private static int checks;
    private static void equal(Object expected,Object actual) {
        checks++;if(!Objects.equals(expected,actual))throw new AssertionError("plant boundary "+checks+": "+expected+" != "+actual);
    }
    public static void main(String[] args) {
        String[] seeds={"wheat_seeds","carrot","potato","beetroot_seeds"};
        String[] crops={"wheat","carrots","potatoes","beetroots"};
        for(int i=0;i<seeds.length;i++) {
            equal("minecraft:"+crops[i],NativePlanting.crop("minecraft:"+seeds[i]));
        }
        for(String unsafe:new String[]{null,"mod:wheat_seeds","minecraft:poisonous_potato","minecraft:melon_seeds","minecraft:torch"})
            equal(null,NativePlanting.crop(unsafe));
        for(BlockPos soil:new BlockPos[]{BlockPos.ZERO,new BlockPos(1361,74,-152)}) {
            var shape=Shapes.box(0,0,0,1,15.0/16,1);
            var aim=NativePlanting.top(soil);
            var hit=shape.clip(new Vec3(soil.getX()+.5,soil.getY()+2.62,soil.getZ()+2),aim,soil);
            equal(true,hit!=null);equal(Direction.UP,hit.getDirection());equal(soil,hit.getBlockPos());
            equal(true,shape.bounds().move(soil).contains(aim));
        }
        System.out.println("PASS NativePlantingFixture "+checks+" checks; policy and supplied shape API only; registry checks require real initialized NeoForge client");
    }
}
