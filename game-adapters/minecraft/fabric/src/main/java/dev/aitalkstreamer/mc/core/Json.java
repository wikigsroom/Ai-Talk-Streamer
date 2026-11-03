package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.TreeMap;

public final class Json {
    public static final Gson GSON = new GsonBuilder().serializeNulls().disableHtmlEscaping().create();
    private Json() {}
    public static JsonObject obj(Object... pairs) {
        JsonObject result = new JsonObject();
        for (int i = 0; i < pairs.length; i += 2) result.add((String) pairs[i], GSON.toJsonTree(pairs[i + 1]));
        return result;
    }
    public static String str(JsonObject value, String key) { return value.get(key).getAsString(); }
    public static long num(JsonObject value, String key) { return value.get(key).getAsLong(); }
    public static String nullable(JsonObject value, String key) {
        JsonElement item = value.get(key); return item == null || item.isJsonNull() ? null : item.getAsString();
    }
    public static String canonical(JsonElement value) {
        if (value.isJsonObject()) {
            TreeMap<String, JsonElement> sorted = new TreeMap<>();
            value.getAsJsonObject().entrySet().forEach(e -> sorted.put(e.getKey(), e.getValue()));
            JsonObject result = new JsonObject(); sorted.forEach((k, v) -> result.add(k, JsonParser.parseString(canonical(v))));
            return GSON.toJson(result);
        }
        if (value.isJsonArray()) {
            JsonArray result = new JsonArray(); value.getAsJsonArray().forEach(v -> result.add(JsonParser.parseString(canonical(v))));
            return GSON.toJson(result);
        }
        return GSON.toJson(value);
    }
    public static String hash(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch (Exception error) { throw new IllegalStateException(error); }
    }
    public static void require(boolean condition, String code) { if (!condition) throw new Rejected(code); }
    public static final class Rejected extends RuntimeException {
        public final String code;
        public Rejected(String code) { super(code); this.code = code; }
    }
}
