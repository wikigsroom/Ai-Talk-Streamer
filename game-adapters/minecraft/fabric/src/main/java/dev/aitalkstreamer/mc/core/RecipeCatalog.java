package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.function.Supplier;
import java.util.function.Function;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Bounded projection of recipes received from the current server, never a crafting result. */
public final class RecipeCatalog {
    public static final int SCAN_LIMIT = 8192, RECIPE_LIMIT = 16, ALTERNATIVE_LIMIT = 16, BYTE_LIMIT = 49152;
    public static final int MODDED_SCAN_LIMIT = 65536;
    private static final String ITEM = "[a-z0-9_.-]+:[a-z0-9_./-]+";
    public record Source(String id, String type, String outputItem, int outputCount, String layout,
                         int width, int height, Supplier<List<List<String>>> ingredients) { }
    private RecipeCatalog() { }
    private static void identifier(String value) {
        require(value != null && value.length() <= 160 && value.matches(ITEM), "GAME_RECIPE_DATA_INVALID");
    }
    public static JsonObject lookup(String item, int count, Iterable<Source> catalog) {
        return lookup(item, count, catalog, SCAN_LIMIT);
    }
    /** Mod recipes may have dynamic/unsupported static outputs. Never turn those into an absent recipe. */
    public static <T> JsonObject lookupProjected(String item, int count, Iterable<T> catalog,
                                                Function<T, Source> project, int scanLimit) {
        require(scanLimit >= 1 && scanLimit <= MODDED_SCAN_LIMIT, "GAME_RECIPE_SCAN_BUDGET_INVALID");
        identifier(item); require(count >= 1 && count <= 4096, "GAME_RECIPE_COUNT_INVALID");
        List<Source> projected = new ArrayList<>(); int scanned = 0, unavailable = 0;
        for (T entry : catalog) {
            require(++scanned <= scanLimit, "GAME_RECIPE_SCAN_LIMIT");
            Source source;
            try { source = project.apply(entry); }
            catch (RuntimeException unsupported) { unavailable++; continue; }
            if (source == null) unavailable++; else projected.add(source);
        }
        JsonObject result = lookup(item, count, projected, scanLimit);
        if (unavailable > 0) {
            require(result.get("recipe_known").getAsBoolean(), "GAME_RECIPE_PROJECTION_UNAVAILABLE");
            result.addProperty("truncated", true);
            JsonArray unknown = result.getAsJsonArray("unknown_fields");
            unknown.add("unprojectable_received_recipe_outputs"); unknown.add("candidate_count"); unknown.add("ambiguous");
            JsonArray choices = result.getAsJsonArray("recipes");
            while (GSON.toJson(result).getBytes(StandardCharsets.UTF_8).length > BYTE_LIMIT && !choices.isEmpty())
                choices.remove(choices.size() - 1);
        }
        return result;
    }
    /** A loader may select a larger bounded catalogue; output and ingredient budgets stay identical. */
    public static JsonObject lookup(String item, int count, Iterable<Source> catalog, int scanLimit) {
        require(scanLimit >= 1 && scanLimit <= MODDED_SCAN_LIMIT, "GAME_RECIPE_SCAN_BUDGET_INVALID");
        identifier(item); require(count >= 1 && count <= 4096, "GAME_RECIPE_COUNT_INVALID");
        TreeMap<String, Source> selected = new TreeMap<>(); Set<String> ids = new HashSet<>();
        int scanned = 0, candidates = 0;
        for (Source recipe : catalog) {
            require(++scanned <= scanLimit, "GAME_RECIPE_SCAN_LIMIT");
            if (!item.equals(recipe.outputItem())) continue;
            identifier(recipe.id()); require(ids.add(recipe.id()), "GAME_RECIPE_DATA_INVALID"); candidates++;
            selected.put(recipe.id(), recipe);
            if (selected.size() > RECIPE_LIMIT) selected.pollLastEntry();
        }
        JsonArray recipes = new JsonArray(); boolean truncated = candidates > selected.size();
        JsonObject result = obj("kind", "recipe", "source", "runtime_recipe_manager", "catalog_scope", "current_server_received",
                "item_id", item, "requested_count", count, "recipe_known", candidates > 0, "candidate_count", candidates,
                "ambiguous", candidates > 1, "truncated", false, "inventory_checked", false, "ingredient_projection", "item_ids_only",
                "unknown_fields", List.of("ingredient_components", "remaining_items", "recipe_unlock_requirements",
                        "server_side_crafting_restrictions", "inventory_allocation", "unreceived_server_recipes", "dynamic_recipe_outputs"));
        // Bind the actual array: obj()/Gson.toJsonTree would otherwise copy it.
        result.add("recipes", recipes);
        int usedBytes = GSON.toJson(result).getBytes(StandardCharsets.UTF_8).length;
        for (Source source : selected.values()) {
            identifier(source.type());
            require(source.outputCount() > 0 && source.outputCount() <= 4096
                    && List.of("shaped", "shapeless", "other").contains(source.layout())
                    && source.width() >= 0 && source.width() <= 3 && source.height() >= 0 && source.height() <= 3,
                    "GAME_RECIPE_DATA_INVALID");
            List<List<String>> values = Objects.requireNonNull(source.ingredients().get());
            require(values.size() <= 9, "GAME_RECIPE_PROJECTION_UNAVAILABLE");
            require(source.layout().equals("shaped") ? source.width() > 0 && source.height() > 0
                    && values.size() == source.width() * source.height() : source.width() == 0 && source.height() == 0,
                    "GAME_RECIPE_DATA_INVALID");
            JsonArray slots = new JsonArray(); boolean known = !values.isEmpty();
            for (int i = 0; i < values.size(); i++) {
                require(values.get(i).size() <= SCAN_LIMIT, "GAME_RECIPE_PROJECTION_UNAVAILABLE");
                TreeSet<String> alternatives = new TreeSet<>();
                for (String alternative : values.get(i)) { identifier(alternative); alternatives.add(alternative); }
                // Large modded tags can otherwise hide every vanilla ingredient
                // behind the first namespace. Retain actual members only; a cut
                // list is still explicitly incomplete and is never allocation.
                List<String> limited = alternatives.stream().sorted(Comparator
                        .comparing((String id) -> !id.startsWith("minecraft:"))
                        .thenComparing(Comparator.naturalOrder())).limit(ALTERNATIVE_LIMIT).toList();
                boolean cut = alternatives.size() > limited.size(); truncated |= cut;
                slots.add(obj("index", i, "empty", alternatives.isEmpty(), "alternatives", limited,
                        "alternatives_total", alternatives.size(), "truncated", cut));
            }
            int batches = (count + source.outputCount() - 1) / source.outputCount();
            JsonObject choice = obj("recipe_id", source.id(), "recipe_type", source.type(), "layout", source.layout(),
                    "width", source.width(), "height", source.height(), "output_per_batch", source.outputCount(),
                    "batches", batches, "output_for_batches", batches * source.outputCount(),
                    "ingredients_known", known, "slots", slots);
            int choiceBytes = GSON.toJson(choice).getBytes(StandardCharsets.UTF_8).length + (recipes.isEmpty() ? 0 : 1);
            if (usedBytes + choiceBytes > BYTE_LIMIT) { truncated = true; break; }
            recipes.add(choice); usedBytes += choiceBytes;
        }
        result.addProperty("truncated", truncated);
        return result;
    }
}
