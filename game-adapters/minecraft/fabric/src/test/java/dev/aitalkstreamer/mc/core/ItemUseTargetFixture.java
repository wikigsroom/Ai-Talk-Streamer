package dev.aitalkstreamer.mc.core;

import static dev.aitalkstreamer.mc.core.Json.*;

/** The target is part of a receipt's identity; never substitute another crop cell. */
public final class ItemUseTargetFixture {
    private static int checks;
    private static void check(boolean value) {checks++;if(!value)throw new AssertionError("target receipt "+checks);}
    public static void main(String[] args) {
        var target=obj("dimension","minecraft:overworld","x",1361,"y",75,"z",-152);
        var task=obj("task_id","task-plant","world_session_id","session-plant","control_epoch",3,
                "goal",obj("skill","use_item","item_id","minecraft:wheat_seeds","purpose","activate","target",target));
        var receipt=new ItemUseReceipt("task-plant","session-plant",3,"minecraft:wheat_seeds","activate",2,1,
                "minecraft:overworld:1361,75,-152",4,true,true,true);
        target=task.getAsJsonObject("goal").getAsJsonObject("target");
        check(receipt.matches(task));check(receipt.complete());
        target.addProperty("x",1362);check(!receipt.matches(task));target.addProperty("x",1361);
        target.addProperty("dimension","minecraft:the_nether");check(!receipt.matches(task));target.addProperty("dimension","minecraft:overworld");
        task.addProperty("control_epoch",4);check(!receipt.matches(task));task.addProperty("control_epoch",3);
        task.addProperty("world_session_id","other");check(!receipt.matches(task));task.addProperty("world_session_id","session-plant");
        var unconfirmed=new ItemUseReceipt("task-plant","session-plant",3,"minecraft:wheat_seeds","activate",2,0,
                "minecraft:overworld:1361,75,-152",-1,false,true,false);
        check(!unconfirmed.complete());check(unconfirmed.hasEffect());
        var noBlock=new ItemUseReceipt("task-plant","session-plant",3,"minecraft:wheat_seeds","activate",2,1,
                "minecraft:overworld:1361,75,-152",4,true,false,true);
        check(!noBlock.complete());
        task.getAsJsonObject("goal").remove("target");check(receipt.matches(task));
        System.out.println("PASS ItemUseTargetFixture "+checks+" checks; no world, input or model effects");
    }
}
