//! Godot-facing layer. Reads controllers, steps `fight_sim` at a fixed 60 Hz in
//! `physics_process`, and mirrors the simulation onto 3D nodes in `process`.
//! No gameplay rules live here — if it affects who wins, it belongs in the sim.

use fight_sim::{Cpu, Event, Fighter, Fx, Input as SimInput, Stage, State, World};
use godot::classes::animation_mixer::AnimationCallbackModeProcess;
use godot::classes::base_material_3d::{Flags, ShadingMode, Transparency};
use godot::classes::{
    AnimationPlayer, BoxMesh, Camera3D, CanvasLayer, INode3D, Input, InputEvent, InputEventJoypadButton, InputEventKey, Label, Mesh,
    MeshInstance3D, Node3D, PackedScene, SphereMesh, StandardMaterial3D,
};
use godot::global::{JoyAxis, JoyButton, Key};
use godot::prelude::*;

struct FightExtension;

#[gdextension]
unsafe impl ExtensionLibrary for FightExtension {}

/// Simulation units -> Godot meters.
const SCALE: f32 = 0.1;
const PLAYERS: usize = 2;
const STOCKS: u8 = 3;
const PLAYER_COLORS: [Color; 4] = [
    Color::from_rgb(0.90, 0.25, 0.25),
    Color::from_rgb(0.25, 0.45, 0.95),
    Color::from_rgb(0.95, 0.80, 0.20),
    Color::from_rgb(0.30, 0.80, 0.35),
];
const STICK_DEADZONE: f32 = 0.15;
/// Rigged fighter model, built by `art/fighter/build_fighter.py`. One animation per
/// `Fighter::anim()` name, keyed at 60 fps.
const FIGHTER_MODEL: &str = "res://models/fighter.glb";
/// Surfaces with this material name get the player's color.
const TINTED_MATERIAL: &str = "Body";
/// The model faces +X. Turning it this far toward the camera shows a 3/4 view, as in Smash.
const MODEL_YAW_TO_CAMERA: f32 = 25.0;
const ANIM_FPS: f64 = 60.0;

fn to_godot(x: Fx, y: Fx) -> Vector3 {
    Vector3::new(x.to_f32() * SCALE, y.to_f32() * SCALE, 0.0)
}

struct FighterView {
    root: Gd<Node3D>,
    anim: Gd<AnimationPlayer>,
    material: Gd<StandardMaterial3D>,
    color: Color,
}

struct Spark {
    node: Gd<MeshInstance3D>,
    frames_left: u32,
    size: f32,
}

#[derive(GodotClass)]
#[class(base = Node3D)]
pub struct FightWorld {
    base: Base<Node3D>,
    world: World,
    views: Vec<FighterView>,
    hitbox_pool: Vec<Gd<MeshInstance3D>>,
    sparks: Vec<Spark>,
    hud: Vec<Gd<Label>>,
    banner: Option<Gd<Label>>,
    camera: Option<Gd<Camera3D>>,
    camera_focus: Vector3,
    shake: f32,
    time: f64,
    show_hitboxes: bool,
    /// `Some` for players driven by the computer instead of a controller.
    cpus: Vec<Option<Cpu>>,
    /// Joypads seen last frame, to log (dis)connections. `None` before the first frame.
    joypads: Option<Vec<i32>>,
    paused: bool,
    advance_one_frame: bool,
}

#[godot_api]
impl INode3D for FightWorld {
    fn init(base: Base<Node3D>) -> Self {
        Self {
            base,
            world: World::new(Stage::battlefield(), PLAYERS, STOCKS),
            views: Vec::new(),
            hitbox_pool: Vec::new(),
            sparks: Vec::new(),
            hud: Vec::new(),
            banner: None,
            camera: None,
            camera_focus: Vector3::new(0.0, 2.0, 0.0),
            shake: 0.0,
            time: 0.0,
            show_hitboxes: false,
            cpus: vec![None; PLAYERS],
            joypads: None,
            paused: false,
            advance_one_frame: false,
        }
    }

    fn ready(&mut self) {
        self.camera = self.base().try_get_node_as::<Camera3D>("Camera3D");
        // FIGHT_DEMO: CPU vs CPU with hitboxes shown. FIGHT_CPU: you vs an easy CPU.
        let demo = std::env::var_os("FIGHT_DEMO").is_some();
        self.show_hitboxes = demo;
        for p in 0..PLAYERS {
            let cpu = demo || (p == PLAYERS - 1 && std::env::var_os("FIGHT_CPU").is_some());
            self.cpus[p] = cpu.then(|| Cpu::easy(p));
        }
        self.build_stage();
        self.build_fighters();
        self.build_hud();
    }

    fn physics_process(&mut self, _delta: f64) {
        if self.paused && !self.advance_one_frame {
            return;
        }
        self.advance_one_frame = false;

        let joypads: Vec<i32> = Input::singleton().get_connected_joypads().iter_shared().map(|id| id as i32).collect();
        if self.joypads.as_ref() != Some(&joypads) {
            for &id in &joypads {
                godot_print!("Joypad {id}: {}", Input::singleton().get_joy_name(id));
            }
            if joypads.is_empty() {
                godot_print!("No joypads connected");
            }
            self.joypads = Some(joypads.clone());
        }
        // Pads go to human players in order, so with P2 as CPU the first pad is P1's.
        let mut pads = joypads.into_iter();
        let mut inputs = Vec::with_capacity(PLAYERS);
        for p in 0..PLAYERS {
            inputs.push(match &mut self.cpus[p] {
                Some(cpu) => cpu.think(&self.world),
                None => read_input(p, pads.next()),
            });
        }
        self.world.step(&inputs);

        for event in self.world.events.clone() {
            match event {
                Event::Hit { x, y, knockback, .. } => {
                    let kb = knockback.to_f32();
                    self.spawn_spark(to_godot(x, y), 0.3 + kb / 150.0);
                    self.shake = self.shake.max((kb - 40.0).max(0.0) / 400.0);
                }
                Event::Ko { fighter } => {
                    self.shake = 0.6;
                    godot_print!("P{} KO'd ({} stocks left)", fighter + 1, self.world.fighters[fighter].stocks);
                }
            }
        }
    }

    fn process(&mut self, delta: f64) {
        self.time += delta;
        self.update_fighters();
        self.update_hitboxes();
        self.update_sparks();
        self.update_hud();
        self.update_camera(delta as f32);
    }

    fn unhandled_input(&mut self, event: Gd<InputEvent>) {
        let event = match event.try_cast::<InputEventJoypadButton>() {
            Ok(button) => {
                if button.is_pressed() {
                    match button.get_button_index() {
                        JoyButton::START => self.new_match(),
                        JoyButton::BACK => self.toggle_cpu(),
                        _ => {}
                    }
                }
                return;
            }
            Err(event) => event,
        };
        let Ok(key) = event.try_cast::<InputEventKey>() else { return };
        if !key.is_pressed() || key.is_echo() {
            return;
        }
        match key.get_physical_keycode() {
            Key::H => self.show_hitboxes = !self.show_hitboxes,
            Key::P => self.paused = !self.paused,
            Key::F => {
                self.paused = true;
                self.advance_one_frame = true;
            }
            Key::R => self.new_match(),
            Key::C => self.toggle_cpu(),
            Key::ESCAPE => self.base().get_tree().quit(),
            _ => {}
        }
    }
}

impl FightWorld {
    fn new_match(&mut self) {
        self.world = World::new(Stage::battlefield(), PLAYERS, STOCKS);
        for (p, cpu) in self.cpus.iter_mut().enumerate() {
            if cpu.is_some() {
                *cpu = Some(Cpu::easy(p));
            }
        }
    }

    /// Switches the last player between human and CPU, and starts over.
    fn toggle_cpu(&mut self) {
        let p = PLAYERS - 1;
        self.cpus[p] = if self.cpus[p].is_some() { None } else { Some(Cpu::easy(p)) };
        self.new_match();
    }

    fn player_name(&self, p: usize) -> String {
        if self.cpus[p].is_some() { format!("CPU{}", p + 1) } else { format!("P{}", p + 1) }
    }

    fn build_stage(&mut self) {
        let stage = self.world.stage.clone();
        for plat in &stage.platforms {
            let width = (plat.right - plat.left).to_f32() * SCALE;
            let (thickness, depth, color) = if plat.soft {
                (0.15, 3.0, Color::from_rgb(0.55, 0.60, 0.70))
            } else {
                (1.6, 5.0, Color::from_rgb(0.35, 0.38, 0.45))
            };
            let mut mesh = BoxMesh::new_gd();
            mesh.set_size(Vector3::new(width, thickness, depth));
            let (mut node, _) = mesh_instance(mesh.upcast(), color);
            let center_x = (plat.left + plat.right).to_f32() * 0.5 * SCALE;
            node.set_position(Vector3::new(center_x, plat.y.to_f32() * SCALE - thickness * 0.5, 0.0));
            self.base_mut().add_child(&node);
        }
    }

    fn build_fighters(&mut self) {
        let scene = load::<PackedScene>(FIGHTER_MODEL);
        for i in 0..self.world.fighters.len() {
            let color = PLAYER_COLORS[i % PLAYER_COLORS.len()];
            let mut material = StandardMaterial3D::new_gd();
            material.set_albedo(color);
            material.set_roughness(0.6);

            let model = scene.instantiate_as::<Node3D>();
            for node in model.find_children_ex("*").type_("MeshInstance3D").done().iter_shared() {
                let mut mesh_node = node.cast::<MeshInstance3D>();
                let Some(mesh) = mesh_node.get_mesh() else { continue };
                for s in 0..mesh.get_surface_count() {
                    if mesh.surface_get_material(s).is_some_and(|m| m.get_name() == TINTED_MATERIAL) {
                        mesh_node.set_surface_override_material(s, &material);
                    }
                }
            }
            // Posed by hand from the sim state every frame (see `update_fighters`), never free-running.
            let mut anim = model.get_node_as::<AnimationPlayer>("AnimationPlayer");
            anim.set_callback_mode_process(AnimationCallbackModeProcess::MANUAL);

            let mut root = Node3D::new_alloc();
            root.add_child(&model);
            self.base_mut().add_child(&root);
            self.views.push(FighterView { root, anim, material, color });
        }
    }

    fn build_hud(&mut self) {
        let mut layer = CanvasLayer::new_alloc();
        for i in 0..self.world.fighters.len() {
            let mut label = styled_label(36, PLAYER_COLORS[i % PLAYER_COLORS.len()]);
            label.set_position(Vector2::new(480.0 + 420.0 * i as f32, 760.0));
            layer.add_child(&label);
            self.hud.push(label);
        }
        let mut banner = styled_label(64, Color::WHITE);
        banner.set_position(Vector2::new(560.0, 360.0));
        layer.add_child(&banner);
        self.banner = Some(banner);

        let mut help = styled_label(16, Color::from_rgba(1.0, 1.0, 1.0, 0.7));
        help.set_text(
            "P1: WASD move · J attack · K jump    P2: arrows · , attack · . jump    Pads: stick · A attack · X/Y jump\n\
             C (pad: View) toggle P2 human/CPU · R (pad: Menu) reset · H hitboxes · P pause · F frame-advance · Esc quit",
        );
        help.set_position(Vector2::new(16.0, 12.0));
        layer.add_child(&help);
        self.base_mut().add_child(&layer);
    }

    fn update_fighters(&mut self) {
        let frame = self.world.frame;
        for (view, f) in self.views.iter_mut().zip(&self.world.fighters) {
            let hidden = matches!(f.state, State::Respawning { .. } | State::Eliminated);
            let blinking = f.intangible > 0 && (frame / 4).is_multiple_of(2);
            view.root.set_visible(!hidden && !blinking);
            view.root.set_position(to_godot(f.x, f.y));
            let yaw = if f.facing < 0 { 180.0 + MODEL_YAW_TO_CAMERA } else { -MODEL_YAW_TO_CAMERA };
            view.root.set_rotation_degrees(Vector3::new(0.0, yaw, 0.0));
            if !hidden {
                pose(&mut view.anim, f, frame);
            }

            let color = match f.state {
                State::Hitstun { .. } if f.hitlag > 0 => Color::WHITE,
                State::Hitstun { .. } => view.color.lerp(Color::WHITE, 0.35),
                State::Attack { .. } => view.color.lightened(0.15),
                _ => view.color,
            };
            view.material.set_albedo(color);
        }
    }

    fn update_hitboxes(&mut self) {
        let active = if self.show_hitboxes { self.world.active_hitboxes() } else { Vec::new() };
        while self.hitbox_pool.len() < active.len() {
            let mut sphere = SphereMesh::new_gd();
            sphere.set_radius(0.5);
            sphere.set_height(1.0);
            let (node, mut mat) = mesh_instance(sphere.upcast(), Color::from_rgba(1.0, 0.1, 0.1, 0.5));
            mat.set_flag(Flags::DISABLE_DEPTH_TEST, true);
            self.base_mut().add_child(&node);
            self.hitbox_pool.push(node);
        }
        for (i, node) in self.hitbox_pool.iter_mut().enumerate() {
            match active.get(i) {
                Some(hb) => {
                    let diameter = hb.radius.to_f32() * 2.0 * SCALE;
                    node.set_position(to_godot(hb.x, hb.y));
                    node.set_scale(Vector3::splat(diameter));
                    node.set_visible(true);
                }
                None => node.set_visible(false),
            }
        }
    }

    fn spawn_spark(&mut self, at: Vector3, size: f32) {
        let mut sphere = SphereMesh::new_gd();
        sphere.set_radius(0.5);
        sphere.set_height(1.0);
        let (mut node, mut mat) = mesh_instance(sphere.upcast(), Color::from_rgba(1.0, 0.9, 0.4, 0.9));
        mat.set_emission_energy_multiplier(4.0);
        mat.set_feature(godot::classes::base_material_3d::Feature::EMISSION, true);
        mat.set_emission(Color::from_rgb(1.0, 0.7, 0.2));
        node.set_position(at + Vector3::new(0.0, 0.0, 0.3));
        self.base_mut().add_child(&node);
        self.sparks.push(Spark { node, frames_left: 10, size });
    }

    fn update_sparks(&mut self) {
        for spark in &mut self.sparks {
            spark.frames_left = spark.frames_left.saturating_sub(1);
            let t = 1.0 - spark.frames_left as f32 / 10.0;
            spark.node.set_scale(Vector3::splat(spark.size * (0.5 + t)));
        }
        self.sparks.retain_mut(|spark| {
            let alive = spark.frames_left > 0;
            if !alive {
                spark.node.queue_free();
            }
            alive
        });
    }

    fn update_hud(&mut self) {
        let names: Vec<String> = (0..self.world.fighters.len()).map(|p| self.player_name(p)).collect();
        for ((label, f), name) in self.hud.iter_mut().zip(&self.world.fighters).zip(&names) {
            let stocks = "● ".repeat(f.stocks as usize);
            label.set_text(&format!("{name}  {}%\n{}", f.percent, stocks));
        }
        let alive: Vec<usize> = (0..self.world.fighters.len())
            .filter(|&i| self.world.fighters[i].state != State::Eliminated)
            .collect();
        let text = match alive.as_slice() {
            [winner] if self.world.fighters.len() > 1 => format!("{} WINS!\nPress R", names[*winner]),
            _ if self.paused => "PAUSED".to_string(),
            _ => String::new(),
        };
        if let Some(banner) = &mut self.banner {
            banner.set_text(&text);
        }
    }

    /// Frames every active fighter, Smash-style: zoom out as they spread apart.
    fn update_camera(&mut self, delta: f32) {
        let Some(camera) = &mut self.camera else { return };
        let points: Vec<Vector3> = self
            .world
            .fighters
            .iter()
            .filter(|f| !matches!(f.state, State::Respawning { .. } | State::Eliminated))
            .map(|f| to_godot(f.x, f.y))
            .collect();
        let (mut min, mut max) = (Vector3::new(-4.0, 0.0, 0.0), Vector3::new(4.0, 2.0, 0.0));
        if !points.is_empty() {
            min = points.iter().fold(points[0], |a, &b| a.coord_min(b));
            max = points.iter().fold(points[0], |a, &b| a.coord_max(b));
        }
        let center = (min + max) * 0.5 + Vector3::new(0.0, 1.2, 0.0);
        let spread = (max.x - min.x).max((max.y - min.y) * 1.8);
        let distance = (spread * 0.9 + 9.0).clamp(13.0, 38.0);

        let follow = 1.0 - (-delta * 4.0).exp();
        let target = Vector3::new(center.x, center.y, distance);
        self.camera_focus = self.camera_focus.lerp(target, follow);

        self.shake *= (-delta * 8.0).exp();
        let t = self.time as f32;
        let jitter = Vector3::new((t * 61.0).sin(), (t * 47.0).cos(), 0.0) * self.shake;
        let eye = self.camera_focus + Vector3::new(0.0, 2.8, 0.0) + jitter;
        camera.set_position(eye);
        camera.look_at(Vector3::new(self.camera_focus.x, self.camera_focus.y, 0.0) + jitter);
    }
}

/// Shows the animation named by `Fighter::anim()` at the frame the sim is on, so the
/// pose always matches the frame data (and survives rollback). Moves are keyed on
/// their 1-based sim frames; poses without a frame counter loop on the world clock.
fn pose(anim: &mut Gd<AnimationPlayer>, f: &Fighter, world_frame: u32) {
    let name = StringName::from(f.anim());
    let Some(clip) = anim.get_animation(&name) else { return };
    let length = (clip.get_length() * ANIM_FPS).round() as u32;
    let frame = match f.state {
        State::Attack { frame, .. } => u32::from(frame).saturating_sub(1),
        State::JumpSquat { frame } => u32::from(frame),
        // Counts down, so play the clip's end: it always finishes back on the idle pose.
        State::Landing { frames_left } => length.saturating_sub(u32::from(frames_left)),
        _ => world_frame % length.max(1),
    };
    if anim.get_current_animation() != name {
        anim.play_ex().name(&name).done();
    }
    anim.seek_ex(f64::from(frame.min(length)) / ANIM_FPS).update(true).done();
}

fn mesh_instance(mesh: Gd<Mesh>, color: Color) -> (Gd<MeshInstance3D>, Gd<StandardMaterial3D>) {
    let mut material = StandardMaterial3D::new_gd();
    material.set_albedo(color);
    if color.a < 1.0 {
        material.set_transparency(Transparency::ALPHA);
        material.set_shading_mode(ShadingMode::UNSHADED);
    }
    let mut node = MeshInstance3D::new_alloc();
    node.set_mesh(&mesh);
    node.set_material_override(&material);
    (node, material)
}

fn styled_label(size: i32, color: Color) -> Gd<Label> {
    let mut label = Label::new_alloc();
    label.add_theme_font_size_override("font_size", size);
    label.add_theme_color_override("font_color", color);
    label.add_theme_color_override("font_outline_color", Color::BLACK);
    label.add_theme_constant_override("outline_size", (size / 5).max(4));
    label
}

/// Merges keyboard and (optionally) a gamepad into one sim input.
fn read_input(player: usize, joypad: Option<i32>) -> SimInput {
    let input = Input::singleton();
    let key = |k: Key| input.is_physical_key_pressed(k);
    let (left, right, up, down, attack, jump) = match player {
        0 => (Key::A, Key::D, Key::W, Key::S, Key::J, Key::K),
        _ => (Key::LEFT, Key::RIGHT, Key::UP, Key::DOWN, Key::COMMA, Key::PERIOD),
    };
    let mut x = key(right) as i32 as f32 - key(left) as i32 as f32;
    let mut y = key(up) as i32 as f32 - key(down) as i32 as f32;
    let mut attack = key(attack);
    let mut jump = key(jump) || (player == 0 && key(Key::SPACE));

    if let Some(device) = joypad {
        let button = |b: JoyButton| input.is_joy_button_pressed(device, b);
        let (jx, jy) = (input.get_joy_axis(device, JoyAxis::LEFT_X), -input.get_joy_axis(device, JoyAxis::LEFT_Y));
        let dx = button(JoyButton::DPAD_RIGHT) as i32 as f32 - button(JoyButton::DPAD_LEFT) as i32 as f32;
        let dy = button(JoyButton::DPAD_UP) as i32 as f32 - button(JoyButton::DPAD_DOWN) as i32 as f32;
        // Whichever source is pushed furthest wins.
        let strongest = |keyboard: f32, analog: [f32; 2]| {
            analog.into_iter().fold(keyboard, |acc, a| if a.abs() > STICK_DEADZONE && a.abs() > acc.abs() { a } else { acc })
        };
        x = strongest(x, [jx, dx]);
        y = strongest(y, [jy, dy]);
        attack |= button(JoyButton::A);
        jump |= button(JoyButton::X) || button(JoyButton::Y);
    }

    let axis = |v: f32| (v.clamp(-1.0, 1.0) * 100.0).round() as i8;
    let mut buttons = 0;
    if attack {
        buttons |= SimInput::ATTACK;
    }
    if jump {
        buttons |= SimInput::JUMP;
    }
    SimInput { stick_x: axis(x), stick_y: axis(y), buttons }
}
