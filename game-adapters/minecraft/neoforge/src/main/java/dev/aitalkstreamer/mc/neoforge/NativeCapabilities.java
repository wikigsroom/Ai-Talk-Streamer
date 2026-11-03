package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import java.util.List;
import static dev.aitalkstreamer.mc.core.Json.*;

/** The exact object sent by this loader; validated separately against the canonical wire contract. */
public final class NativeCapabilities {
    private NativeCapabilities() { }
    public static JsonObject report(String instance, boolean bound) {
        return obj("protocol_version", "1.0", "game_instance_id", instance, "adapter", "minecraft.neoforge",
                "game_version", "1.21.1", "mod_version", "0.1.0", "execution_profile", bound ? "native_core" : "none",
                "skills", bound ? List.of("use_item", "cancel", "navigate", "gather", "return_base", "craft") : List.of(),
                "item_uses", bound ? List.of("eat", "equip", "activate") : List.of(), "features",
                obj("recipes", true, "screenshots", true, "raw_frames", true, "local_takeover", bound, "cancel_all", bound,
                        "basic_pve", false, "survival_rules", false, "resource_chains", false, "task_ledger", true,
                        "targeted_planting", bound, "targeted_block_placement", bound, "targeted_terrain_placement", bound,
                        "autonomous_resume", bound, "autonomous_respawn", bound),
                "rule_fingerprint", null);
    }
}
