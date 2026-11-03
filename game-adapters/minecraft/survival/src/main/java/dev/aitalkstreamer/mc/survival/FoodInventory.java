package dev.aitalkstreamer.mc.survival;

import java.util.*;
import dev.aitalkstreamer.mc.core.InventoryExchange.Stack;
import dev.aitalkstreamer.mc.core.InventoryExchange.State;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Exact one-item consumption and vanilla player-inventory insertion order for a remainder. */
public final class FoodInventory {
    private FoodInventory() { }
    public static State consumed(State prepared, int hand, Stack remainder, int limit, List<Integer> main, int offhand) {
        require(main.size() == 36 && new HashSet<>(main).size() == 36 && main.contains(hand) && offhand == 45
                && main.stream().allMatch(i -> i >= 9 && i <= 44) && prepared.cursor().equals(Stack.EMPTY)
                && prepared.slots().subList(0, 5).stream().allMatch(s -> s.equals(Stack.EMPTY)), "GAME_EATING_HANDLER_INVALID");
        Stack food = prepared.slots().get(hand);
        require(food.count() > 0 && limit >= 1 && limit <= 99 && remainder.count() <= limit
                && (remainder.type() == 0 || remainder.type() != food.type()), "GAME_EATING_REMAINDER_INVALID");
        var slots = new ArrayList<>(prepared.slots());
        if (food.count() == 1) slots.set(hand, remainder);
        else {
            slots.set(hand, new Stack(food.type(), food.count() - 1));
            int left = remainder.count();
            List<Integer> merge = new ArrayList<>(); merge.add(hand); merge.add(offhand);
            for (int slot : main) if (!merge.contains(slot)) merge.add(slot);
            for (int slot : merge) {
                var current = slots.get(slot);
                if (left > 0 && current.type() == remainder.type() && current.count() > 0 && current.count() < limit) {
                    int added = Math.min(left, limit - current.count());
                    slots.set(slot, new Stack(remainder.type(), current.count() + added)); left -= added;
                }
            }
            for (int slot : main) if (left > 0 && slots.get(slot).equals(Stack.EMPTY)) {
                int added = Math.min(left, limit); slots.set(slot, new Stack(remainder.type(), added)); left -= added;
            }
            require(left == 0, "GAME_EATING_REMAINDER_SPACE_REQUIRED");
        }
        return new State(slots, Stack.EMPTY);
    }
}
