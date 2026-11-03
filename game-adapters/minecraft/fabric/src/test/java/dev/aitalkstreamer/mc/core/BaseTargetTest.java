package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.Test;
import java.util.List;
import static dev.aitalkstreamer.mc.core.Json.*;
import static org.junit.jupiter.api.Assertions.*;

class BaseTargetTest {
    final JsonObject goal = obj("skill", "return_base", "base_id", "base-1");
    static JsonObject snapshot() {
        return obj("game_instance_id", "instance-1", "world_id", "world-1", "base_id", "base-1", "base_revision", 2,
                "world_revision", 4, "position", obj("dimension", "minecraft:overworld", "x", 10, "y", 64, "z", 0),
                "radius", 3, "source", "operator_observed", "registered_world_session_id", "old-session-1", "registered_seq", 8);
    }
    final JsonObject observation = obj("game_instance_id", "instance-1", "world_id", "world-1", "world_session_id", "new-session-2",
            "player", obj("position", obj("dimension", "minecraft:overworld", "x", 0, "y", 64, "z", 0)));
    private BaseTarget resolve(JsonObject raw) { return BaseTarget.resolve(goal, raw, null, observation); }
    @Test void anOlderRegistrationSessionDoesNotMakeAStableWorldBaseInvalid() {
        var target = resolve(snapshot()); assertEquals("base-1", target.baseId()); assertEquals(2, target.baseRevision());
        assertEquals(4, target.worldRevision()); assertEquals(10, target.x()); assertEquals(3, target.radius());
    }
    @Test void callerAndReturnedJsonMutationCannotRetargetTheSnapshot() {
        var raw = snapshot(); var target = resolve(raw); raw.getAsJsonObject("position").addProperty("x", 100);
        target.json().getAsJsonObject("position").addProperty("x", 200); target.reference().addProperty("base_revision", 90);
        assertEquals(10, target.x()); assertEquals(2, target.baseRevision());
    }
    @Test void missingOrNullBaseTargetIsRejected() {
        assertEquals("GAME_BASE_TARGET_REQUIRED", assertThrows(Rejected.class, () -> resolve(null)).code);
        assertThrows(Rejected.class, () -> BaseTarget.resolve(goal, JsonNull.INSTANCE, null, observation));
    }
    @Test void everyRegistryIdentityAndRevisionInTheExpectedReferenceIsBound() {
        var raw = snapshot(); var ref = resolve(raw).reference();
        for (String key : List.of("game_instance_id", "world_id", "base_id", "base_revision", "world_revision")) {
            var changed = ref.deepCopy();
            if (key.endsWith("revision")) changed.addProperty(key, 99); else changed.addProperty(key, "other-1");
            assertEquals("GAME_BASE_CHANGED", assertThrows(Rejected.class, () -> BaseTarget.resolve(goal, raw, changed, observation)).code);
        }
    }
    @Test void currentInstanceWorldAndGoalBaseCannotBorrowAnotherBasePosition() {
        for (String key : List.of("game_instance_id", "world_id", "base_id")) {
            var changed = snapshot(); changed.addProperty(key, "other-1");
            assertEquals("GAME_BASE_CONTEXT_INVALID", assertThrows(Rejected.class, () -> resolve(changed)).code);
        }
    }
    @Test void currentDimensionMustMatchButCoordinatesMayBeFarFromTheBase() {
        var raw = snapshot(); raw.getAsJsonObject("position").addProperty("dimension", "minecraft:the_nether");
        assertEquals("GAME_BASE_DIMENSION_CHANGED", assertThrows(Rejected.class, () -> resolve(raw)).code);
        assertDoesNotThrow(() -> resolve(snapshot()));
    }
    @Test void sourceCoordinatesRadiusAndRevisionBoundsUseThePackagedContract() {
        for (String key : List.of("source", "radius", "base_revision", "world_revision")) {
            var raw = snapshot(); if (key.equals("source")) raw.addProperty(key, "model_guessed"); else raw.addProperty(key, 0);
            assertThrows(Rejected.class, () -> resolve(raw));
        }
        var raw = snapshot(); raw.getAsJsonObject("position").addProperty("x", 30000001); assertThrows(Rejected.class, () -> resolve(raw));
    }
    @Test void unrelatedSkillsCannotSmuggleARegisteredTargetOrReference() {
        var gather = obj("skill", "gather", "item_id", "minecraft:oak_log", "count", 4);
        assertNull(BaseTarget.resolve(gather, null, null, observation));
        assertThrows(Rejected.class, () -> BaseTarget.resolve(gather, snapshot(), null, observation));
        assertThrows(Rejected.class, () -> BaseTarget.resolve(gather, null, resolve(snapshot()).reference(), observation));
    }
    @Test void arrivalRequiresTheRegisteredThreeDimensionalRadiusAndDimension() {
        var base = resolve(snapshot()); var p = obj("dimension", "minecraft:overworld", "x", 13, "y", 64, "z", 0);
        assertTrue(base.reached(p)); p.addProperty("y", 65); assertFalse(base.reached(p));
        p.addProperty("y", 64); p.addProperty("dimension", "minecraft:the_nether"); assertFalse(base.reached(p));
        assertFalse(base.reached(null));
    }
}
