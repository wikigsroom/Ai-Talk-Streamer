package dev.aitalkstreamer.mc.survival;

import net.fabricmc.loader.api.entrypoint.PreLaunchEntrypoint;

/** This engineering candidate must not be mistaken for an accepted execution profile. */
public final class SurvivalLaunchGuard implements PreLaunchEntrypoint {
    @Override public void onPreLaunch() {
        throw new IllegalStateException("GAME_SURVIVAL_RUNTIME_UNACCEPTED: input/view/GUI/Baritone binding and real-client acceptance remain incomplete. This build is not installable.");
    }
}
