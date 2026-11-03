package dev.aitalkstreamer.mc.neoforge;

/** Client-thread receipts for completed render events, never proof of desktop presentation. */
final class NativeWorldFrames {
    static final int REQUIRED_FRAMES = 3;
    private Object world, player, connection;
    private int frames;
    private long generation;
    private void observe(Object nextWorld, Object nextPlayer, Object nextConnection) {
        if (world != nextWorld || player != nextPlayer || connection != nextConnection) {
            world = nextWorld; player = nextPlayer; connection = nextConnection; frames = 0; generation++;
        }
    }
    void rendered(Object nextWorld, Object nextPlayer, Object nextConnection, boolean eligible) {
        observe(nextWorld, nextPlayer, nextConnection);
        if (world == null || player == null || connection == null || frames >= REQUIRED_FRAMES) return;
        frames = eligible ? frames + 1 : 0;
    }
    boolean ready(Object nextWorld, Object nextPlayer, Object nextConnection) {
        observe(nextWorld, nextPlayer, nextConnection);
        return world != null && player != null && connection != null && frames >= REQUIRED_FRAMES;
    }
    int frames() { return frames; }
    long generation() { return generation; }
}
