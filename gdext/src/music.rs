//! Background music: one looping track behind the menus, one behind every match. Each
//! track is loaded once and swapped onto a single `AudioStreamPlayer`, so moving between
//! the menu and a match restarts the right song without loading anything new.

use godot::classes::{AudioStream, AudioStreamMp3, AudioStreamPlayer};
use godot::prelude::*;

/// The track that plays behind the menus.
const MENU_TRACK: &str = "res://music/untitled.mp3";
/// The track that plays during a match, whatever the stage.
const STAGE_TRACK: &str = "res://music/rising_motif.mp3";
/// Default music volume, as a percentage of full scale.
const DEFAULT_VOLUME_PERCENT: u8 = 70;

pub(crate) struct Music {
    player: Gd<AudioStreamPlayer>,
    menu: Gd<AudioStream>,
    stage: Gd<AudioStream>,
    /// Music volume as a percentage, 0..=100.
    percent: u8,
}

impl Music {
    pub fn new() -> Music {
        // FIGHT_MUSIC_VOLUME=0..100 overrides the default; live `-` / `=` keys adjust it after.
        let percent = std::env::var("FIGHT_MUSIC_VOLUME")
            .ok()
            .and_then(|value| value.parse::<u8>().ok())
            .map(|value| value.min(100))
            .unwrap_or(DEFAULT_VOLUME_PERCENT);
        let mut player = AudioStreamPlayer::new_alloc();
        player.set_volume_linear(f32::from(percent) / 100.0);
        Music { player, menu: load_track(MENU_TRACK), stage: load_track(STAGE_TRACK), percent }
    }

    /// The player node, to add under the root once in `ready`.
    pub fn player(&self) -> &Gd<AudioStreamPlayer> {
        &self.player
    }

    pub fn play_menu(&mut self) {
        self.player.stop();
        self.player.set_stream(&self.menu);
        self.player.play();
    }

    pub fn play_stage(&mut self) {
        self.player.stop();
        self.player.set_stream(&self.stage);
        self.player.play();
    }

    pub fn percent(&self) -> u8 {
        self.percent
    }

    pub fn set_percent(&mut self, percent: u8) {
        self.percent = percent.min(100);
        self.player.set_volume_linear(f32::from(self.percent) / 100.0);
    }

    /// Stops playback and lets go of the streams, so the headless smoke test ends clean.
    pub fn clear(&mut self) {
        self.player.stop();
        self.player.set_stream(Gd::null_arg());
    }
}

/// Loads a track and sets it to loop from the start, so it repeats seamlessly. If a
/// track ever grows an intro, set its loop offset to skip back past it.
fn load_track(path: &str) -> Gd<AudioStream> {
    let mut stream = load::<AudioStreamMp3>(path);
    stream.set_loop(true);
    stream.set_loop_offset(0.0);
    stream.upcast()
}
