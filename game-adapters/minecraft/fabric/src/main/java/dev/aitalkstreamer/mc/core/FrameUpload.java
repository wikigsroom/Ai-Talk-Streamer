package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.http.*;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.Flow;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Upload only to the already-configured bridge origin, with a bounded response body. */
public final class FrameUpload {
    public static JsonObject send(HttpClient http, URI endpoint, JsonObject metadata, byte[] jpeg) {
        require(jpeg.length > 0 && jpeg.length <= FrameEncoder.MAX_BYTES, "GAME_FRAME_TOO_LARGE");
        URI target = URI.create((endpoint.getScheme().equals("wss") ? "https" : "http") + "://" + endpoint.getRawAuthority()
                + "/api/dsh/game/frames/" + str(metadata, "frame_id"));
        var request = HttpRequest.newBuilder(target).version(HttpClient.Version.HTTP_1_1).timeout(Duration.ofSeconds(5)).header("Content-Type", "image/jpeg")
                .header("X-MC-Operation-Id", str(metadata, "operation_id"))
                .header("X-MC-Bridge-Boot-Id", str(metadata, "bridge_boot_id"))
                .header("X-MC-World-Session-Id", str(metadata, "world_session_id"))
                .header("X-MC-Seq", Long.toString(num(metadata, "source_seq")))
                .header("X-MC-Captured-At", str(metadata, "captured_at"))
                .header("X-MC-Width", Long.toString(num(metadata, "width"))).header("X-MC-Height", Long.toString(num(metadata, "height")))
                .POST(HttpRequest.BodyPublishers.ofByteArray(jpeg)).build();
        CompletableFuture<HttpResponse<byte[]>> future = http.sendAsync(request, info -> new LimitedBody());
        try {
            var response = future.get(6, TimeUnit.SECONDS); require(response.statusCode() == 201, "GAME_FRAME_UPLOAD_FAILED");
            JsonObject receipt = JsonParser.parseString(new String(response.body(), java.nio.charset.StandardCharsets.UTF_8)).getAsJsonObject();
            new Wire().validate("FrameReceipt", receipt);
            for (String key : List.of("frame_id", "operation_id", "world_session_id", "source_seq", "width", "height"))
                require(receipt.get(key).equals(metadata.get(key)), "GAME_FRAME_RECEIPT_CONTEXT");
            return receipt;
        } catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new Json.Rejected("GAME_FRAME_UPLOAD_FAILED"); }
        catch (ExecutionException | TimeoutException error) { throw new Json.Rejected("GAME_FRAME_UPLOAD_FAILED"); }
        finally { if (!future.isDone()) future.cancel(true); }
    }
    private static final class LimitedBody implements HttpResponse.BodySubscriber<byte[]> {
        private final CompletableFuture<byte[]> body = new CompletableFuture<>();
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        private Flow.Subscription subscription;
        public CompletionStage<byte[]> getBody() { return body; }
        public void onSubscribe(Flow.Subscription value) { subscription = value; value.request(1); }
        public void onNext(List<ByteBuffer> chunks) {
            for (ByteBuffer chunk : chunks) {
                if (chunk.remaining() > 4096 - bytes.size()) { subscription.cancel(); body.completeExceptionally(new IOExceptionWrapper()); return; }
                byte[] copy = new byte[chunk.remaining()]; chunk.get(copy); bytes.writeBytes(copy);
            }
            subscription.request(1);
        }
        public void onError(Throwable error) { body.completeExceptionally(error); }
        public void onComplete() { body.complete(bytes.toByteArray()); }
    }
    private static final class IOExceptionWrapper extends RuntimeException { }
}
