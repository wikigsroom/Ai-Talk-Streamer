package dev.aitalkstreamer.mc.neoforge;

import dev.aitalkstreamer.mc.core.InventoryTarget;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Bounded allocation across overlapping live ingredient predicates; no Minecraft objects or writes. */
public final class NativeCraftPlan {
    public record Ingredient(boolean empty, Set<Integer> slots) {
        public Ingredient {
            slots = Set.copyOf(slots);
            require((!empty || slots.isEmpty()) && slots.stream().allMatch(s -> s >= 0 && s < 36), "GAME_CRAFT_INGREDIENT_INVALID");
        }
    }
    public record Recipe(String id, boolean shaped, int width, int height, int perBatch, List<Ingredient> ingredients) {
        public Recipe {
            ingredients = List.copyOf(ingredients);
            require(id != null && !id.isBlank() && id.length() <= 160 && ingredients.size() >= 1 && ingredients.size() <= 9
                    && ingredients.stream().anyMatch(i -> !i.empty()), "GAME_CRAFT_RECIPE_UNAVAILABLE");
            require(perBatch >= 1 && perBatch <= 99, "GAME_CRAFT_OUTPUT_COUNT_INVALID");
            require(shaped ? width >= 1 && width <= 3 && height >= 1 && height <= 3 && ingredients.size() == width * height
                    : width == 0 && height == 0 && ingredients.stream().noneMatch(Ingredient::empty), "GAME_CRAFT_RECIPE_UNAVAILABLE");
        }
        public int gridSize() { return shaped ? width <= 2 && height <= 2 ? 2 : 3 : ingredients.size() <= 4 ? 2 : 3; }
    }
    public record Allocation(int ingredient, int slot, int count) { }
    public record Plan(Recipe recipe, InventoryTarget target, List<Integer> positions, List<Allocation> allocations) {
        public Plan { positions = List.copyOf(positions); allocations = List.copyOf(allocations); }
    }
    private NativeCraftPlan() { }
    private static final class Edge {
        final int to, reverse, initial;
        int capacity;
        Edge(int to, int reverse, int capacity) { this.to = to; this.reverse = reverse; this.initial = this.capacity = capacity; }
    }
    private static Edge edge(List<List<Edge>> graph, int from, int to, int amount) {
        var forward = new Edge(to, graph.get(to).size(), amount);
        graph.get(from).add(forward); graph.get(to).add(new Edge(from, graph.get(from).size() - 1, 0)); return forward;
    }
    /** null means a known recipe lacks materials; malformed inputs still fail explicitly. */
    public static Plan allocate(Recipe recipe, List<Integer> inventory, String item, int baseline, int requested) {
        require(inventory.size() == 36 && inventory.stream().allMatch(n -> n != null && n >= 0 && n <= 99), "GAME_CRAFT_INVENTORY_INVALID");
        var target = new InventoryTarget(item, baseline, requested, recipe.perBatch());
        require(target.batches() <= 4096, "GAME_CRAFT_OUTPUT_COUNT_INVALID");
        int sink = 37 + recipe.ingredients().size();
        List<List<Edge>> graph = new ArrayList<>(); for (int i = 0; i <= sink; i++) graph.add(new ArrayList<>());
        for (int s = 0; s < 36; s++) edge(graph, 0, s + 1, inventory.get(s));
        var edges = new ArrayList<List<Edge>>();
        for (int i = 0; i < recipe.ingredients().size(); i++) {
            var ingredient = recipe.ingredients().get(i); var allocated = new ArrayList<Edge>();
            for (int s = 0; s < 36; s++) allocated.add(!ingredient.empty() && ingredient.slots().contains(s)
                    ? edge(graph, s + 1, 37 + i, target.batches()) : null);
            edges.add(allocated); if (!ingredient.empty()) edge(graph, 37 + i, sink, target.batches());
        }
        int flow = 0, augments = 0;
        while (true) {
            int[] previous = new int[sink + 1], via = new int[sink + 1]; Arrays.fill(previous, -1); previous[0] = 0;
            var queue = new ArrayDeque<Integer>(); queue.add(0);
            while (!queue.isEmpty() && previous[sink] < 0) {
                int from = queue.remove();
                for (int j = 0; j < graph.get(from).size(); j++) {
                    Edge e = graph.get(from).get(j);
                    if (e.capacity > 0 && previous[e.to] < 0) { previous[e.to] = from; via[e.to] = j; queue.add(e.to); }
                }
            }
            if (previous[sink] < 0) break;
            require(++augments <= 36 * 9, "GAME_CRAFT_ALLOCATION_INVALID");
            int amount = Integer.MAX_VALUE;
            for (int at = sink; at != 0; at = previous[at]) amount = Math.min(amount, graph.get(previous[at]).get(via[at]).capacity);
            for (int at = sink; at != 0; at = previous[at]) {
                Edge e = graph.get(previous[at]).get(via[at]); e.capacity -= amount; graph.get(e.to).get(e.reverse).capacity += amount;
            }
            flow = Math.addExact(flow, amount);
        }
        int demand = (int) recipe.ingredients().stream().filter(i -> !i.empty()).count() * target.batches();
        if (flow != demand) return null;
        var allocations = new ArrayList<Allocation>(); var positions = new ArrayList<Integer>();
        for (int i = 0; i < recipe.ingredients().size(); i++) {
            positions.add(recipe.shaped() ? (i / recipe.width()) * recipe.gridSize() + i % recipe.width() : i);
            for (int s = 0; s < 36; s++) {
                Edge e = edges.get(i).get(s); if (e != null && e.initial > e.capacity) allocations.add(new Allocation(i, s, e.initial - e.capacity));
            }
        }
        return new Plan(recipe, target, positions, allocations);
    }
    /** Choose an executable item recipe from the received catalog, independent of catalog order. */
    public static Plan select(List<Plan> candidates) {
        require(!candidates.isEmpty(), "GAME_CRAFT_MATERIALS_MISSING");
        var first = candidates.getFirst().target();
        var ids = new HashSet<String>();
        for (var candidate : candidates) {
            // A catalog ID must name exactly one plan. Distinct ordinary recipes
            // for the same item are alternatives, rather than an admission error.
            require(ids.add(candidate.recipe().id()), "GAME_CRAFT_RECIPE_AMBIGUOUS");
            var target = candidate.target();
            require(target.itemId().equals(first.itemId()) && target.baseline() == first.baseline()
                    && target.requestedIncrement() == first.requestedIncrement()
                    && target.outputPerBatch() == candidate.recipe().perBatch(), "GAME_CRAFT_ALLOCATION_INVALID");
        }
        return candidates.stream().min(Comparator
                .comparingInt((Plan p) -> p.recipe().gridSize())
                .thenComparingInt(p -> p.allocations().stream().mapToInt(Allocation::count).sum())
                .thenComparingInt(p -> p.target().plannedIncrement() - p.target().requestedIncrement())
                .thenComparing(p -> p.recipe().id())).orElseThrow();
    }
    public static int[] remaining(Plan plan, int[] amounts) {
        require(amounts.length == plan.allocations().size(), "GAME_CRAFT_ALLOCATION_INVALID"); int[] counts = new int[36];
        for (int i = 0; i < amounts.length; i++) {
            var allocated = plan.allocations().get(i);
            require(amounts[i] >= 0 && amounts[i] <= allocated.count(), "GAME_CRAFT_ALLOCATION_INVALID");
            counts[allocated.slot()] = Math.addExact(counts[allocated.slot()], amounts[i]);
        }
        return counts;
    }
}
