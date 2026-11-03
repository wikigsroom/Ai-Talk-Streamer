package dev.aitalkstreamer.mc.survival.audit;

import com.google.gson.*;
import org.objectweb.asm.commons.Remapper;
import java.io.IOException;
import java.nio.file.*;
import java.util.*;

/** Explicit named rule set, mapped against the exact pinned Yarn Tiny2 input. */
public final class GatePolicy {
    private static final Map<String,String> POLICY_ROUTES = Map.of(
            "policy_chatCommand", "CALL:net/minecraft/client/network/ClientPlayNetworkHandler:sendChatCommand:(Ljava/lang/String;)V",
            "policy_chatMessage", "CALL:net/minecraft/client/network/ClientPlayNetworkHandler:sendChatMessage:(Ljava/lang/String;)V",
            "policy_fallFlying", "CALL:net/minecraft/client/network/ClientPlayerEntity:checkFallFlying:()Z",
            "policy_respawn", "CALL:net/minecraft/client/network/ClientPlayerEntity:requestRespawn:()V",
            "policy_disconnect", "CALL:net/minecraft/world/World:disconnect:()V",
            "policy_grounded", "FIELD:net/minecraft/entity/player/PlayerAbilities:flying:Z");
    private static final Set<String> MOVEMENT_KEYS = Set.of("jumping","pressingBack","pressingForward","pressingLeft","pressingRight","sneaking");
    private static final Set<String> MOVEMENT_AXES = Set.of("movementForward","movementSideways");
    private static final Map<String, Set<String>> ACTION_ROUTES = Map.ofEntries(
            Map.entry("action_yaw", Set.of("net/minecraft/entity/Entity:setYaw:(F)V", "net/minecraft/client/network/ClientPlayerEntity:setYaw:(F)V")),
            Map.entry("action_pitch", Set.of("net/minecraft/entity/Entity:setPitch:(F)V", "net/minecraft/client/network/ClientPlayerEntity:setPitch:(F)V")),
            Map.entry("action_sprint", Set.of("net/minecraft/client/network/ClientPlayerEntity:setSprinting:(Z)V")),
            Map.entry("action_swing", Set.of("net/minecraft/client/network/ClientPlayerEntity:swingHand:(Lnet/minecraft/util/Hand;)V")),
            Map.entry("action_attackBlock", Set.of("net/minecraft/client/network/ClientPlayerInteractionManager:attackBlock:(Lnet/minecraft/util/math/BlockPos;Lnet/minecraft/util/math/Direction;)Z")),
            Map.entry("action_breakProgress", Set.of("net/minecraft/client/network/ClientPlayerInteractionManager:updateBlockBreakingProgress:(Lnet/minecraft/util/math/BlockPos;Lnet/minecraft/util/math/Direction;)Z")),
            Map.entry("action_cancelBreaking", Set.of("net/minecraft/client/network/ClientPlayerInteractionManager:cancelBlockBreaking:()V")),
            Map.entry("action_attackEntity", Set.of("net/minecraft/client/network/ClientPlayerInteractionManager:attackEntity:(Lnet/minecraft/entity/player/PlayerEntity;Lnet/minecraft/entity/Entity;)V")),
            Map.entry("action_interactEntity", Set.of("net/minecraft/client/network/ClientPlayerInteractionManager:interactEntity:(Lnet/minecraft/entity/player/PlayerEntity;Lnet/minecraft/entity/Entity;Lnet/minecraft/util/Hand;)Lnet/minecraft/util/ActionResult;")),
            Map.entry("action_interactItem", Set.of("net/minecraft/client/network/ClientPlayerInteractionManager:interactItem:(Lnet/minecraft/entity/player/PlayerEntity;Lnet/minecraft/util/Hand;)Lnet/minecraft/util/ActionResult;")),
            Map.entry("action_stopUsing", Set.of("net/minecraft/client/network/ClientPlayerInteractionManager:stopUsingItem:(Lnet/minecraft/entity/player/PlayerEntity;)V")));
    private static final Map<String, String> GUI_ROUTES = Map.of(
            "gui_screen", "net/minecraft/client/MinecraftClient:setScreen:(Lnet/minecraft/client/gui/screen/Screen;)V",
            "gui_close", "net/minecraft/client/network/ClientPlayerEntity:closeHandledScreen:()V",
            "gui_block", "net/minecraft/client/network/ClientPlayerInteractionManager:interactBlock:(Lnet/minecraft/client/network/ClientPlayerEntity;Lnet/minecraft/util/Hand;Lnet/minecraft/util/hit/BlockHitResult;)Lnet/minecraft/util/ActionResult;",
            "gui_slot", "net/minecraft/client/network/ClientPlayerInteractionManager:clickSlot:(IIILnet/minecraft/screen/slot/SlotActionType;Lnet/minecraft/entity/player/PlayerEntity;)V",
            "gui_recipe", "net/minecraft/client/network/ClientPlayerInteractionManager:clickRecipe:(ILnet/minecraft/recipe/RecipeEntry;Z)V");
    public record Rule(String kind, String owner, String name, String descriptor, String declaration, String relay) { }
    private final Set<Rule> rules;
    public GatePolicy(Collection<Rule> rules) { this.rules = Set.copyOf(rules); }
    public static GatePolicy read(Path path) throws IOException {
        JsonObject json = JsonParser.parseString(Files.readString(path)).getAsJsonObject();
        if (json.get("schema_version").getAsInt() != 1) throw new IllegalArgumentException("GAME_GATE_POLICY_VERSION");
        List<Rule> rules = new ArrayList<>();
        for (JsonElement item : json.getAsJsonArray("rules")) {
            JsonObject row = item.getAsJsonObject();
            Rule rule = new Rule(row.get("kind").getAsString(), row.get("owner").getAsString(),
                    row.get("name").getAsString(), row.get("descriptor").getAsString(),
                    row.has("declaration") ? row.get("declaration").getAsString() : row.get("owner").getAsString(),
                    row.has("relay") ? row.get("relay").getAsString() : null);
            if (!Set.of("CALL", "FIELD").contains(rule.kind()) || rule.name().startsWith("<"))
                throw new IllegalArgumentException("GAME_GATE_POLICY_RULE");
            if (rule.relay() != null && rule.relay().startsWith("policy_")
                    && !Objects.equals(POLICY_ROUTES.get(rule.relay()),
                    rule.kind()+":"+rule.owner()+":"+rule.name()+":"+rule.descriptor()))
                throw new IllegalArgumentException("GAME_GATE_POLICY_SIGNATURE");
            if (rule.relay() != null && rule.relay().startsWith("motion_")
                    && !(rule.kind().equals("FIELD") && rule.owner().equals("baritone/utils/PlayerMovementInput")
                    && rule.declaration().equals("net/minecraft/client/input/Input")
                    && rule.relay().equals("motion_"+rule.name())
                    && (MOVEMENT_KEYS.contains(rule.name()) && rule.descriptor().equals("Z")
                    || MOVEMENT_AXES.contains(rule.name()) && rule.descriptor().equals("F"))))
                throw new IllegalArgumentException("GAME_GATE_MOTION_SIGNATURE");
            if (rule.relay() != null && rule.relay().startsWith("action_")
                    && (!rule.kind().equals("CALL") || !ACTION_ROUTES.getOrDefault(rule.relay(),Set.of()).contains(
                    rule.owner() + ":" + rule.name() + ":" + rule.descriptor())))
                throw new IllegalArgumentException("GAME_GATE_ACTION_SIGNATURE");
            if (rule.relay() != null && rule.relay().startsWith("gui_")
                    && (!rule.kind().equals("CALL") || !Objects.equals(GUI_ROUTES.get(rule.relay()),
                    rule.owner() + ":" + rule.name() + ":" + rule.descriptor())))
                throw new IllegalArgumentException("GAME_GATE_GUI_SIGNATURE");
            if ("select".equals(rule.relay()) && !(rule.kind().equals("FIELD")
                    && rule.owner().equals("net/minecraft/entity/player/PlayerInventory")
                    && rule.declaration().equals(rule.owner()) && rule.name().equals("selectedSlot")
                    && rule.descriptor().equals("I")))
                throw new IllegalArgumentException("GAME_GATE_HOTBAR_SIGNATURE");
            if ("sneaking".equals(rule.relay()) && !(rule.kind().equals("FIELD")
                    && rule.owner().equals("net/minecraft/client/input/Input") && rule.declaration().equals(rule.owner())
                    && rule.name().equals("sneaking") && rule.descriptor().equals("Z")))
                throw new IllegalArgumentException("GAME_GATE_SNEAK_SIGNATURE");
            if (rule.relay() != null && rule.relay().startsWith("option_") && !(switch (rule.relay()) {
                case "option_value" -> rule.kind().equals("CALL") && rule.owner().equals("net/minecraft/client/option/SimpleOption")
                        && rule.name().equals("setValue") && rule.descriptor().equals("(Ljava/lang/Object;)V");
                case "option_pauseOnLostFocus" -> rule.kind().equals("FIELD") && rule.owner().equals("net/minecraft/client/option/GameOptions")
                        && rule.declaration().equals(rule.owner()) && rule.name().equals("pauseOnLostFocus") && rule.descriptor().equals("Z");
                default -> false;
            })) throw new IllegalArgumentException("GAME_GATE_OPTION_SIGNATURE");
            rules.add(rule);
        }
        if (new HashSet<>(rules).size() != rules.size()) throw new IllegalArgumentException("GAME_GATE_POLICY_DUPLICATE");
        return new GatePolicy(rules);
    }
    public Rule match(String kind, String owner, String name, String descriptor) {
        return rules.stream().filter(rule -> rule.kind().equals(kind) && rule.owner().equals(owner)
                && rule.name().equals(name) && rule.descriptor().equals(descriptor)).findFirst().orElse(null);
    }
    public GatePolicy intermediary(Path mapping) throws IOException {
        List<String> lines = Files.readAllLines(mapping);
        if (lines.isEmpty() || !lines.getFirst().equals("tiny\t2\t0\tintermediary\tnamed"))
            throw new IllegalArgumentException("GAME_GATE_MAPPING_NAMESPACES");
        Map<String, String> classes = new HashMap<>();
        for (String line : lines) if (line.startsWith("c\t")) {
            String[] columns = line.split("\t", -1); classes.put(columns[2], columns[1]);
        }
        Remapper toIntermediary = new Remapper() {
            @Override public String map(String name) { return classes.getOrDefault(name, name); }
        };
        Map<String, String> toNamedClasses = new HashMap<>();
        classes.forEach((named, inter) -> toNamedClasses.put(inter, named));
        Remapper toNamed = new Remapper() {
            @Override public String map(String name) { return toNamedClasses.getOrDefault(name, name); }
        };
        Map<String, String> exact = new HashMap<>();
        Map<String, Set<String>> inherited = new HashMap<>();
        String owner = null;
        for (String line : lines) {
            String[] columns = line.split("\t", -1);
            if (line.startsWith("c\t")) owner = columns[2];
            else if (line.startsWith("\tm\t") || line.startsWith("\tf\t")) {
                String kind = columns[1].equals("m") ? "CALL" : "FIELD";
                String descriptor = kind.equals("CALL") ? toNamed.mapMethodDesc(columns[2]) : toNamed.mapDesc(columns[2]);
                String key = kind + ":" + columns[4] + ":" + descriptor;
                exact.put(owner + ":" + key, columns[3]);
                inherited.computeIfAbsent(key, ignored -> new HashSet<>()).add(columns[3]);
            }
        }
        List<Rule> mapped = new ArrayList<>();
        for (Rule rule : rules) {
            String key = rule.kind() + ":" + rule.name() + ":" + rule.descriptor();
            String member = exact.get(rule.declaration() + ":" + key);
            if (member == null && inherited.getOrDefault(key, Set.of()).size() == 1) member = inherited.get(key).iterator().next();
            if (member == null) throw new IllegalArgumentException("GAME_GATE_MEMBER_MAPPING:" + rule.owner() + ":" + rule.name());
            mapped.add(new Rule(rule.kind(), toIntermediary.mapType(rule.owner()), member,
                    rule.kind().equals("CALL") ? toIntermediary.mapMethodDesc(rule.descriptor()) : toIntermediary.mapDesc(rule.descriptor()),
                    toIntermediary.mapType(rule.declaration()), rule.relay()));
        }
        return new GatePolicy(mapped);
    }
}
