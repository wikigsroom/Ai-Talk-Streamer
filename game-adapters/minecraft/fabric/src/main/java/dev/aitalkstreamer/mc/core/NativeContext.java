package dev.aitalkstreamer.mc.core;

/** Actual client objects accepted by one input scope; equal names cannot replace their identities. */
public record NativeContext(Object world, Object player, Object connection, Object interactions) {
    public NativeContext {
        if (world == null || player == null || connection == null || interactions == null)
            throw new IllegalStateException("GAME_INPUT_CONTEXT_UNAVAILABLE");
    }
    public void require(Object actualWorld, Object actualPlayer, Object actualConnection, Object actualInteractions) {
        if (world != actualWorld || player != actualPlayer || connection != actualConnection || interactions != actualInteractions)
            throw new IllegalStateException("GAME_INPUT_CONTEXT_CHANGED");
    }
}
