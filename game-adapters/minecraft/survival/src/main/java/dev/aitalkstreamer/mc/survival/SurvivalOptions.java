package dev.aitalkstreamer.mc.survival;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.GameOptions;
import net.minecraft.client.option.SimpleOption;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.require;

/** The pinned navigation code may change only these three client settings, under its original root. */
public final class SurvivalOptions {
    private static Binding binding;
    private static final class Binding {
        final SurvivalAuthority.Session owner;
        final GameOptions options;
        final Map<SimpleOption<?>, SettingLease<Object>> values = new IdentityHashMap<>();
        final SettingLease<Boolean> pause;
        Binding(SurvivalAuthority.Session owner, GameOptions options) {
            this.owner = owner; this.options = options;
            pause = new SettingLease<>(() -> options.pauseOnLostFocus, value -> options.pauseOnLostFocus = value);
        }
        @SuppressWarnings("unchecked")
        SettingLease<Object> value(SimpleOption<?> option) {
            return values.computeIfAbsent(option, key -> new SettingLease<>(key::getValue,
                    value -> ((SimpleOption<Object>) key).setValue(value)));
        }
        void close() {
            MinecraftClient client = client(false);
            if (client.options != options) {
                values.values().forEach(SettingLease::discard); pause.discard();
            } else {
                List<Runnable> restore = new ArrayList<>(); values.values().forEach(value -> restore.add(value::release)); restore.add(pause::release);
                Throwable failure = null;
                for (Runnable action : restore) try { action.run(); }
                catch (RuntimeException | Error error) { if (failure == null) failure = error; else if (failure != error) failure.addSuppressed(error); }
                if (failure instanceof RuntimeException error) throw error;
                if (failure instanceof Error error) throw error;
            }
            values.clear(); if (binding == this) binding = null;
        }
    }
    private SurvivalOptions() { }
    private static MinecraftClient client(boolean gameplay) {
        MinecraftClient client = MinecraftClient.getInstance();
        require(client != null && client.isOnThread(), "GAME_WRONG_THREAD");
        require(client.options != null, "GAME_OPTION_CONTEXT_CHANGED");
        if (gameplay) require(client.world != null && client.player != null && client.isWindowFocused() && !client.isPaused(), "GAME_GUI_BLOCKED");
        return client;
    }
    private static Binding owner(MinecraftClient client) {
        var session = SurvivalAuthority.session();
        if (binding == null) {
            Binding created = new Binding(session, client.options);
            SurvivalAuthority.owned(created::close); binding = created;
        }
        require(binding.owner == session && binding.options == client.options, "GAME_OPTION_CONTEXT_CHANGED");
        return binding;
    }
    private static void valid(MinecraftClient client, SimpleOption<?> option, Object value) {
        require(option != null, "GAME_OPTION_UNSUPPORTED");
        if (option == client.options.getAutoJump()) require(value instanceof Boolean, "GAME_OPTION_VALUE_INVALID");
        else if (option == client.options.getGamma())
            require(value instanceof Double number && Double.isFinite(number) && number >= 0 && number <= 1, "GAME_OPTION_VALUE_INVALID");
        else throw new IllegalStateException("GAME_OPTION_UNSUPPORTED");
    }
    private static boolean closing() {
        if (SurvivalAuthority.inScope() || !SurvivalAuthority.hasScope()) return false;
        // Upstream stop/pop may try to apply stale internal settings after the
        // permit was revoked. Only our registered leases perform actual restore.
        SurvivalAuthority.requireOwnerScope(); return true;
    }
    public static void value(SimpleOption<?> option, Object next) {
        if (closing()) return;
        if (!SurvivalAuthority.inScope()) {
            var client = client(false); valid(client, option, next);
            require(Objects.equals(option.getValue(), next), "GAME_OPTION_NO_TASK"); return;
        }
        SurvivalAuthority.write(() -> {
            var client = client(true); valid(client, option, next); owner(client).value(option).replace(next);
        });
    }
    public static void pauseOnLostFocus(GameOptions requested, boolean next) {
        if (closing()) return;
        if (!SurvivalAuthority.inScope()) {
            var client = client(false); require(client.options == requested, "GAME_OPTION_CONTEXT_CHANGED");
            require(requested.pauseOnLostFocus == next, "GAME_OPTION_NO_TASK"); return;
        }
        SurvivalAuthority.write(() -> {
            var client = client(true); require(client.options == requested, "GAME_OPTION_CONTEXT_CHANGED"); owner(client).pause.replace(next);
        });
    }
    public static void checkpoint() {
        SurvivalAuthority.requireScope(); Binding current = binding;
        if (current == null) return;
        var client = client(true); require(current.owner == SurvivalAuthority.session() && current.options == client.options, "GAME_OPTION_CONTEXT_CHANGED");
        current.values.values().forEach(SettingLease::check); current.pause.check();
    }
}
