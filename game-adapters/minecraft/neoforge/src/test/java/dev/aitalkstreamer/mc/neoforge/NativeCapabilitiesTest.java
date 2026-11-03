package dev.aitalkstreamer.mc.neoforge;

import dev.aitalkstreamer.mc.core.Wire;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class NativeCapabilitiesTest {
    @Test void actualBoundReportPassesTheCanonicalContractAndDoesNotAdvertiseSurvival() {
        var value = NativeCapabilities.report("game-native-contract-test", true);
        assertDoesNotThrow(() -> new Wire().validate("Capabilities", value));
        assertEquals("native_core", value.get("execution_profile").getAsString());
        assertEquals("use_item", value.getAsJsonArray("skills").get(0).getAsString());
        assertEquals("cancel", value.getAsJsonArray("skills").get(1).getAsString());
        assertEquals(java.util.List.of("use_item", "cancel", "navigate", "gather", "return_base", "craft"),
                value.getAsJsonArray("skills").asList().stream().map(element -> element.getAsString()).toList());
        var features = value.getAsJsonObject("features");
        assertTrue(features.get("cancel_all").getAsBoolean());
        assertTrue(features.get("local_takeover").getAsBoolean());
        for (String key : new String[]{"basic_pve", "survival_rules", "resource_chains"}) assertFalse(features.get(key).getAsBoolean());
    }
    @Test void missingRuntimeHooksStillYieldAValidUnboundReportWithNoInputCapability() {
        var value = NativeCapabilities.report("game-native-contract-test", false);
        assertDoesNotThrow(() -> new Wire().validate("Capabilities", value));
        assertEquals("none", value.get("execution_profile").getAsString());
        assertTrue(value.getAsJsonArray("skills").isEmpty()); assertTrue(value.getAsJsonArray("item_uses").isEmpty());
        assertFalse(value.getAsJsonObject("features").get("local_takeover").getAsBoolean());
        assertFalse(value.getAsJsonObject("features").get("cancel_all").getAsBoolean());
    }
}
