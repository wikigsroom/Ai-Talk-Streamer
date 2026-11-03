package dev.aitalkstreamer.mc.core;

import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.IIOImage;
import javax.imageio.stream.MemoryCacheImageOutputStream;
import java.awt.image.BufferedImage;
import java.io.*;
import static dev.aitalkstreamer.mc.core.Json.require;

/** CPU-only encoding. Call outside the Minecraft/render and control actor threads. */
public final class FrameEncoder {
    public static final int MAX_BYTES = 4 * 1024 * 1024;
    public record Capture(int width, int height, int[] rgb) {
        public Capture {
            require(width > 0 && width <= 1920 && height > 0 && height <= 1080
                    && rgb != null && rgb.length == (long) width * height, "GAME_FRAME_DIMENSIONS");
            rgb = rgb.clone();
        }
    }
    public static byte[] jpeg(Capture capture) throws IOException {
        BufferedImage image = new BufferedImage(capture.width(), capture.height(), BufferedImage.TYPE_INT_RGB);
        image.setRGB(0, 0, capture.width(), capture.height(), capture.rgb(), 0, capture.width());
        ByteArrayOutputStream bytes = new ByteArrayOutputStream() {
            @Override public synchronized void write(byte[] value, int offset, int length) {
                require(length <= MAX_BYTES - count, "GAME_FRAME_TOO_LARGE"); super.write(value, offset, length);
            }
            @Override public synchronized void write(int value) { require(count < MAX_BYTES, "GAME_FRAME_TOO_LARGE"); super.write(value); }
        };
        var writer = ImageIO.getImageWritersByFormatName("jpeg").next();
        try (var output = new MemoryCacheImageOutputStream(bytes)) {
            writer.setOutput(output); var params = writer.getDefaultWriteParam();
            params.setCompressionMode(ImageWriteParam.MODE_EXPLICIT); params.setCompressionQuality(.85f);
            writer.write(null, new IIOImage(image, null, null), params); output.flush();
            require(bytes.size() > 0 && bytes.size() <= MAX_BYTES, "GAME_FRAME_TOO_LARGE"); return bytes.toByteArray();
        } finally { writer.dispose(); image.flush(); }
    }
}
