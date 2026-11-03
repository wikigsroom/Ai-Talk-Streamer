package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import javax.imageio.ImageIO;
import java.io.ByteArrayInputStream;
import java.net.*;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicReference;
import static dev.aitalkstreamer.mc.core.Json.*;
import static org.junit.jupiter.api.Assertions.*;

class FrameTest {
    @Test void cpuJpegRoundtripHasExactDimensionsAndColour() throws Exception {
        int[] pixels = new int[32 * 18]; Arrays.fill(pixels, 0xd04020);
        var capture = new FrameEncoder.Capture(32, 18, pixels); pixels[0] = 0;
        byte[] bytes = FrameEncoder.jpeg(capture); assertTrue(bytes.length < FrameEncoder.MAX_BYTES);
        var image = ImageIO.read(new ByteArrayInputStream(bytes)); assertEquals(32, image.getWidth()); assertEquals(18, image.getHeight());
        int rgb = image.getRGB(0, 0); assertTrue(Math.abs((rgb >> 16 & 255) - 208) < 8); assertTrue((rgb & 255) < 40);
    }
    @Test void impossibleCaptureSizeIsRejectedBeforeEncoding() {
        assertThrows(Json.Rejected.class, () -> new FrameEncoder.Capture(1921, 1, new int[1921]));
        assertThrows(Json.Rejected.class, () -> new FrameEncoder.Capture(1, 1081, new int[1081]));
        assertThrows(Json.Rejected.class, () -> new FrameEncoder.Capture(32, 18, new int[1]));
    }
    private JsonObject metadata() {
        return obj("frame_id", "frame-test", "operation_id", "operation-test", "bridge_boot_id", "boot-test",
                "world_session_id", "world-test", "source_seq", 9, "captured_at", Instant.now().toString(), "width", 32, "height", 18);
    }
    private JsonObject receipt(JsonObject value) {
        return obj("frame_id", value.get("frame_id"), "operation_id", value.get("operation_id"), "world_session_id", value.get("world_session_id"),
                "source_seq", value.get("source_seq"), "width", 32, "height", 18, "content_type", "image/jpeg", "byte_length", 12,
                "received_at", Instant.now().toString(), "expires_at", Instant.now().plusSeconds(30).toString());
    }
    @Test void uploadUsesConfiguredOriginAndAllCorrelationHeaders() throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0); var metadata = metadata();
        var seen = new AtomicReference<JsonObject>();
        server.createContext("/api/dsh/game/frames/frame-test", exchange -> {
            seen.set(obj("method", exchange.getRequestMethod(), "operation", exchange.getRequestHeaders().getFirst("X-MC-Operation-Id"),
                    "boot", exchange.getRequestHeaders().getFirst("X-MC-Bridge-Boot-Id"), "seq", exchange.getRequestHeaders().getFirst("X-MC-Seq"),
                    "bytes", exchange.getRequestBody().readAllBytes().length));
            byte[] body = GSON.toJson(receipt(metadata)).getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(201, body.length); exchange.getResponseBody().write(body); exchange.close();
        }); server.start();
        try (var client = HttpClient.newHttpClient()) {
            FrameUpload.send(client, URI.create("ws://127.0.0.1:" + server.getAddress().getPort() + "/api/dsh/game/bridge"), metadata, new byte[12]);
            assertEquals("POST", str(seen.get(), "method")); assertEquals("operation-test", str(seen.get(), "operation"));
            assertEquals("boot-test", str(seen.get(), "boot")); assertEquals("9", str(seen.get(), "seq")); assertEquals(12, num(seen.get(), "bytes"));
        } finally { server.stop(0); }
    }
    @Test void uploadRejectsOversizedResponseAndWrongReceiptContext() throws Exception {
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0); var metadata = metadata();
        var body = new AtomicReference<>("x".repeat(4097));
        server.createContext("/api/dsh/game/frames/frame-test", exchange -> {
            exchange.getRequestBody().readAllBytes(); byte[] bytes = body.get().getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(201, bytes.length); exchange.getResponseBody().write(bytes); exchange.close();
        }); server.start();
        try (var client = HttpClient.newHttpClient()) {
            URI endpoint = URI.create("ws://127.0.0.1:" + server.getAddress().getPort() + "/api/dsh/game/bridge");
            assertThrows(Json.Rejected.class, () -> FrameUpload.send(client, endpoint, metadata, new byte[12]));
            var wrong = receipt(metadata); wrong.addProperty("source_seq", 10); body.set(GSON.toJson(wrong));
            var error = assertThrows(Json.Rejected.class, () -> FrameUpload.send(client, endpoint, metadata, new byte[12]));
            assertEquals("GAME_FRAME_RECEIPT_CONTEXT", error.code);
        } finally { server.stop(0); }
    }
}
