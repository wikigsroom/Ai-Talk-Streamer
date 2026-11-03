package dev.aitalkstreamer.mc.survival;

import net.minecraft.block.*;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.screen.ingame.*;
import net.minecraft.recipe.*;
import net.minecraft.recipe.input.SingleStackRecipeInput;
import net.minecraft.screen.*;
import net.minecraft.item.ItemStack;
import java.util.*;

/** Exact native workstation, menu and recipe type; no menu is accepted by inheritance. */
enum CookingWorkstation {
    FURNACE, BLAST_FURNACE, SMOKER;
    String id() {return name().toLowerCase(Locale.ROOT);}
    Block block() {return switch(this) {case FURNACE->Blocks.FURNACE;case BLAST_FURNACE->Blocks.BLAST_FURNACE;case SMOKER->Blocks.SMOKER;};}
    boolean handler(ScreenHandler value) {return value!=null && value.getClass()==switch(this) {
        case FURNACE->FurnaceScreenHandler.class;case BLAST_FURNACE->BlastFurnaceScreenHandler.class;case SMOKER->SmokerScreenHandler.class;};}
    boolean screen(Object value) {return value!=null && value.getClass()==switch(this) {
        case FURNACE->FurnaceScreen.class;case BLAST_FURNACE->BlastFurnaceScreen.class;case SMOKER->SmokerScreen.class;};}
    List<RecipeEntry<? extends AbstractCookingRecipe>> recipes() {
        var manager=MinecraftClient.getInstance().getNetworkHandler().getRecipeManager();
        return switch(this) {case FURNACE->new ArrayList<>(manager.listAllOfType(RecipeType.SMELTING));
            case BLAST_FURNACE->new ArrayList<>(manager.listAllOfType(RecipeType.BLASTING));
            case SMOKER->new ArrayList<>(manager.listAllOfType(RecipeType.SMOKING));};
    }
    Optional<RecipeEntry<? extends AbstractCookingRecipe>> first(ItemStack input) {
        var c=MinecraftClient.getInstance();var manager=c.getNetworkHandler().getRecipeManager();var in=new SingleStackRecipeInput(input);
        return switch(this) {case FURNACE->manager.getFirstMatch(RecipeType.SMELTING,in,c.world).map(e->e);
            case BLAST_FURNACE->manager.getFirstMatch(RecipeType.BLASTING,in,c.world).map(e->e);
            case SMOKER->manager.getFirstMatch(RecipeType.SMOKING,in,c.world).map(e->e);};
    }
    int maximumTicks() {return this==SMOKER?120:1200;}
}
