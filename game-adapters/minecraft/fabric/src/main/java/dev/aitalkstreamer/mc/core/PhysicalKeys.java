package dev.aitalkstreamer.mc.core;

import java.util.*;
import java.util.function.IntPredicate;

/** Maps only actual GLFW callback key/scancode pairs; never probes invalid key codes. */
public final class PhysicalKeys {
    private final long window;
    private final Map<Integer, Integer> codes = new HashMap<>();
    private final Set<Integer> down = new HashSet<>();
    public PhysicalKeys(long window) { this.window = window; }
    public void event(long window, int key, int scancode, int action) {
        if (window != this.window || scancode < 0) return;
        if (key >= 0) codes.put(scancode, key);
        if (action == 0) down.remove(scancode);
        else if (action == 1 || action == 2) down.add(scancode);
    }
    public boolean held(int scancode, IntPredicate pollKey) {
        Integer key = codes.get(scancode); return key != null ? pollKey.test(key) : down.contains(scancode);
    }
    public void lostFocus() { down.clear(); }
}
