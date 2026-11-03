package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class LocalTaskFailureTest {
    @Test void fixedStorageRejectionsAreClassifiedButNearMatchesRemainPrivate() {
        for(var reason:LocalTaskFailure.Reason.values())if(reason.name().startsWith("STORAGE_")) {
            String code="GAME_"+reason.name();assertEquals(code,LocalTaskFailure.executionReason(new Json.Rejected(code)));
        }
        assertEquals("GAME_EXECUTOR_FAILED",LocalTaskFailure.executionReason(new Json.Rejected("GAME_STORAGE_SERVER_TIMEOUT private")));
        assertEquals("GAME_EXECUTOR_FAILED",LocalTaskFailure.executionReason(new IllegalStateException("GAME_STORAGE_SERVER_DIVERGED")));
    }
    @Test void knownMissingMaterialRejectionHasAStablePublicReason() {
        assertEquals("GAME_CRAFT_MATERIALS_MISSING", LocalTaskFailure.executionReason(new Json.Rejected("GAME_CRAFT_MATERIALS_MISSING")));
    }
    @Test void reservationLimitSurvivesStartupClassification() {
        assertEquals("GAME_MATERIAL_RESERVATION_LIMIT", LocalTaskFailure.startReason(new LocalTaskFailure(LocalTaskFailure.Reason.MATERIAL_RESERVATION_LIMIT)));
    }
    @Test void fixedCursorAndServerFailureRejectionsAreClassified() {
        assertEquals("GAME_RESOURCE_CRAFT_CURSOR_BUSY", LocalTaskFailure.executionReason(new Json.Rejected("GAME_RESOURCE_CRAFT_CURSOR_BUSY")));
        assertEquals("GAME_CRAFT_SERVER_DIVERGED", LocalTaskFailure.executionReason(new Json.Rejected("GAME_CRAFT_SERVER_DIVERGED")));
        assertEquals("GAME_RESOURCE_MATERIAL_CYCLE", LocalTaskFailure.executionReason(new Json.Rejected("GAME_RESOURCE_MATERIAL_CYCLE")));
        assertEquals("GAME_RESOURCE_CRAFT_SEARCH_LIMIT", LocalTaskFailure.executionReason(new Json.Rejected("GAME_RESOURCE_CRAFT_SEARCH_LIMIT")));
        assertEquals("GAME_RESOURCE_CRAFT_RECIPE_SET_INVALID", LocalTaskFailure.executionReason(new Json.Rejected("GAME_RESOURCE_CRAFT_RECIPE_SET_INVALID")));
    }
    @Test void anExceptionMessageCannotMasqueradeAsARecognizedCode() {
        assertEquals("GAME_EXECUTOR_FAILED", LocalTaskFailure.executionReason(new IllegalStateException("GAME_CRAFT_MATERIALS_MISSING")));
    }
    @Test void arbitraryRejectionTextIsNeverPublished() {
        assertEquals("GAME_EXECUTOR_FAILED", LocalTaskFailure.executionReason(new Json.Rejected("private path or account information")));
    }
    @Test void similarlyPrefixedOrExtendedCodesRemainUnknown() {
        for (String code : new String[]{"GAME_CRAFT_UNKNOWN", "GAME_MATERIAL_ALLOCATION_LIMIT private", "GAME_CRAFT_SERVER_TIMEOUT\nprivate"})
            assertEquals("GAME_EXECUTOR_FAILED", LocalTaskFailure.executionReason(new Json.Rejected(code)));
    }
    @Test void aWrappedOrSuppressedKnownFailureDoesNotOverrideTheActualError() {
        var wrapper = new IllegalStateException("private", new Json.Rejected("GAME_CRAFT_SERVER_TIMEOUT"));
        wrapper.addSuppressed(new LocalTaskFailure(LocalTaskFailure.Reason.CRAFT_MATERIALS_MISSING));
        assertEquals("GAME_EXECUTOR_FAILED", LocalTaskFailure.executionReason(wrapper));
    }
    @Test void absentCodeAndFatalErrorsUseTheFixedFallback() {
        assertEquals("GAME_EXECUTOR_FAILED", LocalTaskFailure.executionReason(new Json.Rejected(null)));
        assertEquals("GAME_EXECUTOR_START_FAILED", LocalTaskFailure.startReason(new AssertionError("private")));
    }
    @Test void earlierTypedSurvivalFailuresKeepTheirReason() {
        assertEquals("GAME_SHIELD_TIMEOUT", LocalTaskFailure.executionReason(new LocalTaskFailure(LocalTaskFailure.Reason.SHIELD_TIMEOUT)));
    }

    @Test void allFixedCookingRejectionsRemainStableAcrossTheSharedExecutor() {
        for(var reason:LocalTaskFailure.Reason.values()) if(reason.name().startsWith("COOKING_")) {
            String code="GAME_"+reason.name();assertEquals(code,LocalTaskFailure.executionReason(new Json.Rejected(code)));
        }
    }
    @Test void fixedSmeltingFailuresAreClassifiedWithoutAcceptingArbitraryCookingText() {
        for(String code:new String[]{"GAME_RESOURCE_SMELTING_RECIPE_UNSUPPORTED","GAME_RESOURCE_SMELTING_FUEL_UNAVAILABLE"})assertEquals(code,LocalTaskFailure.executionReason(new Json.Rejected(code)));
        assertEquals("GAME_EXECUTOR_FAILED",LocalTaskFailure.executionReason(new Json.Rejected("GAME_COOKING_UNKNOWN")));
        assertEquals("GAME_EXECUTOR_FAILED",LocalTaskFailure.executionReason(new Json.Rejected("GAME_COOKING_REVOKED private")));
    }

}
