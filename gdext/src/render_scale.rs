//! 3D render resolution. The 3D scene is drawn at no more than about 4K's worth of
//! pixels and upscaled to the window with FSR 1, so a 5K or 8K window (or macOS's
//! scaled modes, which render a 4K monitor's "looks like 2560x1440" at 5120x2880) costs
//! the GPU no more than native 4K. 2D (menus, HUD) is drawn at the full window size and
//! stays sharp. Presentation only: the sim never sees it.

use godot::classes::Window;
use godot::classes::viewport::Scaling3DMode;
use godot::prelude::*;

/// The most pixels the 3D scene is drawn at: 3840x2160.
const MAX_3D_PIXELS: f32 = 3840.0 * 2160.0;
/// The range `FIGHT_RENDER_SCALE` is clamped to.
const MIN_SCALE: f32 = 0.25;
const MAX_SCALE: f32 = 1.0;

/// The 3D scale that fits a `width` x `height` (physical pixels) window into
/// `MAX_3D_PIXELS`, or 1.0 if it already fits.
pub(crate) fn auto_scale(width: i32, height: i32) -> f32 {
    let pixels = width.max(0) as f32 * height.max(0) as f32;
    if pixels <= MAX_3D_PIXELS { 1.0 } else { (MAX_3D_PIXELS / pixels).sqrt() }
}

/// Parses a `FIGHT_RENDER_SCALE` value: a fixed scale, clamped to `MIN_SCALE..=MAX_SCALE`.
fn parse_forced(value: &str) -> Option<f32> {
    value.trim().parse::<f32>().ok().filter(|s| s.is_finite()).map(|s| s.clamp(MIN_SCALE, MAX_SCALE))
}

pub(crate) struct RenderScale {
    /// `FIGHT_RENDER_SCALE`: a fixed scale instead of the automatic one.
    forced: Option<f32>,
    /// The window size the scale was last set for.
    size: Option<Vector2i>,
}

impl RenderScale {
    pub fn new() -> RenderScale {
        RenderScale { forced: std::env::var("FIGHT_RENDER_SCALE").ok().as_deref().and_then(parse_forced), size: None }
    }

    /// Call every frame: sets the window's 3D scale when its size changes (resize, fullscreen).
    pub fn update(&mut self, window: &mut Gd<Window>) {
        let size = window.get_size();
        if self.size == Some(size) {
            return;
        }
        self.size = Some(size);
        let scale = self.forced.unwrap_or_else(|| auto_scale(size.x, size.y));
        // At 1.0 Godot skips the FSR pass, so a window that fits costs nothing extra.
        window.set_scaling_3d_mode(Scaling3DMode::FSR);
        window.set_scaling_3d_scale(scale);
        godot_print!("3D render scale {scale:.2} for a {}x{} window", size.x, size.y);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn up_to_4k_renders_native() {
        assert_eq!(auto_scale(1600, 900), 1.0);
        assert_eq!(auto_scale(1920, 1080), 1.0);
        assert_eq!(auto_scale(3840, 2160), 1.0);
        // Ultrawide 3440x1440 is fewer pixels than 4K.
        assert_eq!(auto_scale(3440, 1440), 1.0);
    }

    #[test]
    fn bigger_windows_draw_4k_worth_of_pixels() {
        // macOS "looks like 2560x1440" on a 4K monitor renders at 5K.
        assert!((auto_scale(5120, 2880) - 0.75).abs() < 1e-6);
        assert!((auto_scale(7680, 4320) - 0.5).abs() < 1e-6);
        let s = auto_scale(6016, 3384);
        let pixels = 6016.0 * s * 3384.0 * s;
        assert!((pixels - MAX_3D_PIXELS).abs() / MAX_3D_PIXELS < 1e-4);
    }

    #[test]
    fn empty_window_is_native() {
        // A minimized window can report 0x0.
        assert_eq!(auto_scale(0, 0), 1.0);
        assert_eq!(auto_scale(-1, 100), 1.0);
    }

    #[test]
    fn forced_scale_is_clamped() {
        assert_eq!(parse_forced("0.6"), Some(0.6));
        assert_eq!(parse_forced(" 1 "), Some(1.0));
        assert_eq!(parse_forced("3"), Some(MAX_SCALE));
        assert_eq!(parse_forced("0"), Some(MIN_SCALE));
        assert_eq!(parse_forced("NaN"), None);
        assert_eq!(parse_forced("auto"), None);
    }
}
