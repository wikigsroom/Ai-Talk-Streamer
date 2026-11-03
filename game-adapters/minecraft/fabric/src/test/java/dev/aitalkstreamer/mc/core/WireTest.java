package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.Test;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assertions.*;

class WireTest {
    @Test void bothImplementedLoaderAdaptersPassButUnknownAdaptersDoNot() throws Exception {
        Wire wire = new Wire();
        JsonObject capabilities = java.util.stream.StreamSupport.stream(examples().spliterator(), false)
                .map(JsonElement::getAsJsonObject).filter(row -> row.get("name").getAsString().equals("capabilities"))
                .findFirst().orElseThrow().getAsJsonObject("value").deepCopy();
        for (String adapter : new String[]{"minecraft.fabric", "minecraft.neoforge"}) {
            capabilities.addProperty("adapter", adapter); wire.validate("Capabilities", capabilities);
        }
        capabilities.addProperty("adapter", "minecraft.unbound");
        assertThrows(Json.Rejected.class, () -> wire.validate("Capabilities", capabilities));
    }
    private JsonArray examples() throws Exception {
        try (var input = getClass().getResourceAsStream("/mc-contracts/examples.json")) {
            return JsonParser.parseString(new String(input.readAllBytes(), StandardCharsets.UTF_8)).getAsJsonObject().getAsJsonArray("cases");
        }
    }
    @Test void authoritativeExamplesPassInJava() throws Exception {
        Wire wire = new Wire(); JsonArray cases = examples(); assertTrue(cases.size() >= 40);
        for (JsonElement entry : cases) { JsonObject value = entry.getAsJsonObject(); wire.validate(value.get("definition").getAsString(), value.get("value")); }
    }
    @Test void fabricatedSuccessAndUnknownFieldsAreRejected() throws Exception {
        Wire wire = new Wire();
        for (JsonElement entry : examples()) {
            JsonObject value = entry.getAsJsonObject(); if (!value.get("name").getAsString().equals("task-complete")) continue;
            JsonObject task = value.getAsJsonObject("value").deepCopy(); task.add("evidence", new JsonArray());
            assertThrows(Json.Rejected.class, () -> wire.validate("Task", task));
            task.addProperty("shell", "not-a-game-tool"); assertThrows(Json.Rejected.class, () -> wire.validate("Task", task));
        }
    }
    @Test void directionAndBodyLimitsAreEnforced() throws Exception {
        Wire wire = new Wire();
        for (JsonElement entry : examples()) {
            JsonObject value = entry.getAsJsonObject(); if (value.get("name").getAsString().equals("bridge-hello"))
                assertThrows(Json.Rejected.class, () -> wire.incoming(value.get("value").toString()));
        }
        assertThrows(Json.Rejected.class, () -> wire.incoming(" ".repeat(Wire.MAX_BYTES + 1)));
        assertThrows(Json.Rejected.class, () -> wire.incoming("[]"));
    }
    @Test void allExamplesAndRejectionsFitWithinABoundedNativeHeap() throws Exception {
        var locations = new java.util.ArrayList<>(java.util.stream.Stream.of(WireTest.class, Wire.class, JsonObject.class,
                dev.harrel.jsonschema.Validator.class).map(type -> {
            try { return Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toString(); }
            catch (Exception error) { throw new IllegalStateException(error); }
        }).distinct().toList());
        for (String name : new String[]{"game.schema.json", "examples.json"}) {
            var resource = getClass().getResource("/mc-contracts/" + name); assertNotNull(resource);
            locations.add(Path.of(resource.toURI()).getParent().getParent().toString());
        }
        Path log = Files.createTempFile("mc-wire-heap-", ".log");
        Process process = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java.exe").toString(),
                "-Xmx256m", "-cp", String.join(java.io.File.pathSeparator, locations), HeapProbe.class.getName())
                .redirectErrorStream(true).redirectOutput(log.toFile()).start();
        try {
            assertTrue(process.waitFor(60, TimeUnit.SECONDS), "Bounded schema probe timed out");
            String output = Files.readString(log); assertEquals(0, process.exitValue(), output);
            assertTrue(output.contains("validated=" + examples().size() + ",rejected=2"), output);
        } finally {
            if (process.isAlive()) { process.destroyForcibly(); assertTrue(process.waitFor(5, TimeUnit.SECONDS)); }
            Files.deleteIfExists(log);
        }
    }
    /** Separate real JVM with only the bridge core and existing schema libraries. No Minecraft. */
    public static final class HeapProbe {
        public static void main(String[] args) throws Exception {
            Wire wire = new Wire(); JsonArray cases;
            try (var input = HeapProbe.class.getResourceAsStream("/mc-contracts/examples.json")) {
                cases = JsonParser.parseString(new String(input.readAllBytes(), StandardCharsets.UTF_8))
                        .getAsJsonObject().getAsJsonArray("cases");
            }
            for (JsonElement entry : cases) {
                JsonObject value = entry.getAsJsonObject(); wire.validate(value.get("definition").getAsString(), value.get("value"));
            }
            int rejected = 0;
            for (String definition : new String[]{"BridgeEnvelope", "Task/../Task"}) {
                try { wire.validate(definition, new JsonObject()); }
                catch (Json.Rejected expected) { rejected++; }
            }
            if (rejected != 2) throw new IllegalStateException("Invalid frames or definition were accepted");
            System.out.println("validated=" + cases.size() + ",rejected=" + rejected);
        }
    }
}
