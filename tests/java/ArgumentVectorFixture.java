import java.nio.charset.StandardCharsets;
import java.util.Base64;

/** Argument-file boundary fixture only. Never loads Minecraft or changes a save. */
public final class ArgumentVectorFixture {
    public static void main(String[] args) {
        System.out.println(args.length);
        for (String arg : args) {
            System.out.println(Base64.getEncoder().encodeToString(arg.getBytes(StandardCharsets.UTF_8)));
        }
    }
}
