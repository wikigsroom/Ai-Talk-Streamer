package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import dev.harrel.jsonschema.ValidatorFactory;
import dev.harrel.jsonschema.Validator;
import dev.harrel.jsonschema.providers.GsonNode;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.net.URI;
import static dev.aitalkstreamer.mc.core.Json.*;

/** The packaged schema is copied from the repository authority at build time. */
public final class Wire {
    public static final int MAX_BYTES = 128 * 1024;
    private static final Set<String> INCOMING = Set.of("hello_ack", "heartbeat", "ack", "snapshot_request", "control_request",
            "lease_grant", "task_start", "task_cancel", "query", "protocol_error");
    private final Validator validator = new ValidatorFactory().withJsonNodeFactory(new GsonNode.Factory()).createValidator();
    private final Map<String, URI> schemas = new HashMap<>();
    public Wire() {
        try (InputStream input = getClass().getResourceAsStream("/mc-contracts/game.schema.json")) {
            if (input == null) throw new IllegalStateException("Packaged game contract missing");
            JsonObject schema = JsonParser.parseString(new String(input.readAllBytes(), StandardCharsets.UTF_8)).getAsJsonObject();
            // Register the authority once. Repeating all $defs in a wrapper for
            // every message type retains many complete schema evaluator graphs.
            URI contract = validator.registerSchema(schema.toString());
            for (String name : schema.getAsJsonObject("$defs").keySet()) {
                String pointer = "/$defs/" + name.replace("~", "~0").replace("/", "~1");
                String fragment = new URI(null, null, pointer).getRawFragment();
                schemas.put(name, URI.create(contract + "#" + fragment));
            }
        } catch (Exception error) { throw new IllegalStateException("Cannot load game contract", error); }
    }
    public synchronized void validate(String definition, JsonElement value) {
        URI definitionUri = schemas.get(definition);
        require(definitionUri != null, "GAME_SCHEMA_INVALID");
        require(validator.validate(definitionUri, value).isValid(), "GAME_SCHEMA_INVALID");
    }
    public JsonObject incoming(String text) {
        require(text.getBytes(StandardCharsets.UTF_8).length <= MAX_BYTES, "GAME_FRAME_TOO_LARGE");
        JsonObject frame;
        try { frame = JsonParser.parseString(text).getAsJsonObject(); }
        catch (RuntimeException error) { throw new Json.Rejected("GAME_JSON_INVALID"); }
        validate("BridgeEnvelope", frame);
        require(INCOMING.contains(str(frame, "type")), "GAME_DIRECTION_INVALID"); return frame;
    }
}
