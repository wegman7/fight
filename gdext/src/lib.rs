//! Godot-facing layer. Reads controllers, steps `fight_sim` at a fixed 60 Hz in
//! `physics_process`, and mirrors the simulation onto 3D nodes in `process`.
//! No gameplay rules live here — if it affects who wins, it belongs in the sim.

use fight_sim::{Character, Cpu, DodgeKind, Event, Fighter, Fx, Input as SimInput, SHIELD_MAX, STATE_ANIMS, Stage, State, World};
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
/// Right stick pushed this far acts as the C-stick: one smash attack (or aerial) in its direction.
const CSTICK_THRESHOLD: f32 = 0.5;
const TRIGGER_THRESHOLD: f32 = 0.3;
/// How a sim `Character` is drawn.
struct Look {
    /// Rigged model with an animation for every name its character's `Fighter::anim()`
    /// can return, keyed at 60 fps.
    model: &'static str,
    /// How its neutral special's projectile is drawn.
    shot: Shot,
}

#[derive(Clone, Copy, PartialEq)]
enum Shot {
    /// A glowing ball in this color, mixed a little with the player's.
    Orb(Color),
    /// A model built facing +X, turned the way it flies and tilted with its arc, drawn
    /// at `scale`. It bursts into blobs of `splat` where it hits or lands.
    Model { path: &'static str, scale: f32, splat: Color },
}

fn look(character: Character) -> Look {
    match character {
        // Both built by art/fighter/build_fighter.py. The pie is 0.26 m across as built;
        // drawn a bit bigger in flight, a little inside its 0.6 m hitbox.
        Character::Chef => Look {
            model: "res://models/fighter.glb",
            shot: Shot::Model { path: "res://models/pie.glb", scale: 1.5, splat: Color::from_rgb(0.98, 0.96, 0.9) },
        },
        // Built by art/pug/build_pug.py. Its projectile is a sneeze cloud.
        Character::Pug => Look { model: "res://models/pug.glb", shot: Shot::Orb(Color::from_rgb(0.85, 0.95, 0.8)) },
    }
}
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
    /// The model under `root`, jittered while charging a smash attack.
    model: Gd<Node3D>,
    anim: Gd<AnimationPlayer>,
    material: Gd<StandardMaterial3D>,
    shield: Gd<MeshInstance3D>,
    shield_material: Gd<StandardMaterial3D>,
    color: Color,
}

struct Spark {
    node: Gd<MeshInstance3D>,
    frames_left: u32,
    size: f32,
}

struct ProjectileView {
    node: Gd<Node3D>,
    /// The orb's material, to color it each frame. `None` for models.
    material: Option<Gd<StandardMaterial3D>>,
    shot: Shot,
}

/// A blob of cream from a pie splat: flies out, falls and shrinks away. Blobs with a
/// `floor` stop on it.
struct Splat {
    node: Gd<MeshInstance3D>,
    velocity: Vector3,
    size: Vector3,
    floor: Option<f32>,
    frames_left: u32,
    life: u32,
}

const SPLAT_GRAVITY: f32 = 0.004;

#[derive(GodotClass)]
#[class(base = Node3D)]
pub struct FightWorld {
    base: Base<Node3D>,
    world: World,
    views: Vec<FighterView>,
    hitbox_pool: Vec<(Gd<MeshInstance3D>, Gd<StandardMaterial3D>)>,
    projectile_pool: Vec<ProjectileView>,
    sparks: Vec<Spark>,
    splats: Vec<Splat>,
    hud: Vec<Gd<Label>>,
    banner: Option<Gd<Label>>,
    camera: Option<Gd<Camera3D>>,
    camera_focus: Vector3,
    shake: f32,
    time: f64,
    show_hitboxes: bool,
    /// Per player: who they play. Changing it starts a new match.
    characters: Vec<Character>,
    /// `Some` for players driven by the computer instead of a controller.
    cpus: Vec<Option<Cpu>>,
    /// Per player: right stick was out last frame, so it only fires once per push.
    cstick_out: Vec<bool>,
    /// Joypads seen last frame, to log (dis)connections. `None` before the first frame.
    joypads: Option<Vec<i32>>,
    paused: bool,
    advance_one_frame: bool,
}

#[godot_api]
impl INode3D for FightWorld {
    fn init(base: Base<Node3D>) -> Self {
        // P1 starts as the chef, P2 as the pug; 1 / 2 cycle them in game.
        let characters: Vec<Character> = (0..PLAYERS).map(|p| Character::ALL[p % Character::ALL.len()]).collect();
        Self {
            base,
            world: World::new(Stage::battlefield(), &characters, STOCKS),
            views: Vec::new(),
            hitbox_pool: Vec::new(),
            projectile_pool: Vec::new(),
            sparks: Vec::new(),
            splats: Vec::new(),
            hud: Vec::new(),
            banner: None,
            camera: None,
            camera_focus: Vector3::new(0.0, 2.0, 0.0),
            shake: 0.0,
            time: 0.0,
            show_hitboxes: false,
            characters,
            cpus: vec![None; PLAYERS],
            cstick_out: vec![false; PLAYERS],
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
                None => read_input(p, pads.next(), &mut self.cstick_out[p]),
            });
        }
        self.world.step(&inputs);

        for event in self.world.events.clone() {
            match event {
                Event::Hit { attacker, x, y, knockback, projectile, .. } => {
                    let kb = knockback.to_f32();
                    match self.splat_color(attacker, projectile) {
                        Some(cream) => self.spawn_splat(to_godot(x, y), cream, None),
                        None => self.spawn_spark(to_godot(x, y), 0.3 + kb / 150.0),
                    }
                    self.shake = self.shake.max((kb - 40.0).max(0.0) / 400.0);
                }
                Event::ShieldHit { attacker, x, y, projectile, .. } => match self.splat_color(attacker, projectile) {
                    Some(cream) => self.spawn_splat(to_godot(x, y), cream, None),
                    None => self.spawn_spark(to_godot(x, y), 0.25),
                },
                Event::ProjectileLanded { owner, x, y } => {
                    if let Some(cream) = self.splat_color(owner, true) {
                        let at = to_godot(x, y);
                        self.spawn_splat(at, cream, Some(at.y));
                    }
                }
                Event::ShieldBreak { fighter } => {
                    self.shake = 0.4;
                    godot_print!("P{} shield break!", fighter + 1);
                }
                Event::Grab { .. } => {}
                Event::Counter { x, y, .. } => {
                    self.spawn_spark(to_godot(x, y), 0.6);
                    self.shake = self.shake.max(0.15);
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
        self.update_projectiles();
        self.update_sparks();
        self.update_splats();
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
            Key::KEY_1 => self.next_character(0),
            Key::KEY_2 => self.next_character(1),
            Key::ESCAPE => self.base().get_tree().quit(),
            _ => {}
        }
    }
}

impl FightWorld {
    fn new_match(&mut self) {
        self.world = World::new(Stage::battlefield(), &self.characters, STOCKS);
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
            // Driftwood platforms over a weathered stone block, to suit the beach backdrop.
            let (thickness, depth, color) = if plat.soft {
                (0.15, 3.0, Color::from_rgb(0.45, 0.32, 0.22))
            } else {
                (1.6, 5.0, Color::from_rgb(0.46, 0.40, 0.34))
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
        for i in 0..self.world.fighters.len() {
            let view = self.build_view(i);
            self.views.push(view);
        }
    }

    fn build_view(&mut self, i: usize) -> FighterView {
        let character = self.characters[i];
        let color = PLAYER_COLORS[i % PLAYER_COLORS.len()];
        let mut material = StandardMaterial3D::new_gd();
        material.set_albedo(color);
        material.set_roughness(0.6);

        let model = load::<PackedScene>(look(character).model).instantiate_as::<Node3D>();
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
        let moves = character.moves();
        let names = STATE_ANIMS.iter().copied().chain(moves.iter().map(|m| m.data().name)).chain(DodgeKind::ALL.iter().map(|d| d.data().name));
        for name in names {
            if !anim.has_animation(name) {
                godot_error!("{} has no animation '{name}': that pose won't show", look(character).model);
            }
        }

        let mut root = Node3D::new_alloc();
        root.add_child(&model);
        self.base_mut().add_child(&root);

        let (shield, shield_material) = sphere_instance(Color { a: 0.35, ..color });
        self.base_mut().add_child(&shield);
        FighterView { root, model, anim, material, shield, shield_material, color }
    }

    /// Switches player `p` to the next character and starts a new match, since
    /// characters play differently.
    fn next_character(&mut self, p: usize) {
        if p >= self.views.len() {
            return;
        }
        let next = (Character::ALL.iter().position(|&c| c == self.characters[p]).unwrap_or(0) + 1) % Character::ALL.len();
        self.characters[p] = Character::ALL[next];
        let mut view = self.build_view(p);
        std::mem::swap(&mut self.views[p], &mut view);
        view.root.queue_free();
        view.shield.queue_free();
        self.new_match();
        godot_print!("P{} is now the {}", p + 1, self.characters[p].name());
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
            "P1: WASD move · J attack · K jump · L special · ; shield · U grab · I smash\n\
             P2: arrows · , attack · . jump · / special · M shield · N grab · B smash\n\
             Pads: stick · A attack · B special · X/Y jump · LT/RT shield · LB/RB grab · right stick smash\n\
             C (pad: View) toggle P2 human/CPU · 1 / 2 change P1 / P2 character · R (pad: Menu) reset\n\
             H hitboxes · P pause · F frame-advance · Esc quit",
        );
        help.set_position(Vector2::new(16.0, 12.0));
        layer.add_child(&help);
        self.base_mut().add_child(&layer);
    }

    fn update_fighters(&mut self) {
        let frame = self.world.frame;
        let flash = (frame / 3).is_multiple_of(2);
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
            // Shake in place while charging a smash attack.
            let jitter = if f.charging() { if flash { 0.02 } else { -0.02 } } else { 0.0 };
            view.model.set_position(Vector3::new(jitter, 0.0, 0.0));

            let color = match f.state {
                State::Hitstun { .. } if f.hitlag > 0 => Color::WHITE,
                State::Hitstun { .. } => view.color.lerp(Color::WHITE, 0.35),
                _ if f.dodge_invincible() => view.color.lerp(Color::from_rgb(0.7, 0.9, 1.0), 0.6),
                _ if f.charging() && flash => view.color.lightened(0.45),
                State::ShieldBreak { .. } if flash => view.color.lerp(Color::from_rgb(1.0, 0.9, 0.2), 0.5),
                State::Attack { .. } => view.color.lightened(0.15),
                _ => view.color,
            };
            view.material.set_albedo(color);

            // The shield bubble shrinks as it takes damage, like Smash's.
            view.shield.set_visible(!hidden && f.shielding());
            if f.shielding() {
                let health = (f.shield.to_f32() / SHIELD_MAX.to_f32()).clamp(0.0, 1.0);
                let diameter = (f.params.height.to_f32() + 3.0) * SCALE * (0.35 + 0.65 * health);
                let center = to_godot(f.x, f.y + f.params.height / Fx::int(2));
                view.shield.set_position(center);
                view.shield.set_scale(Vector3::splat(diameter));
                let stunned = matches!(f.state, State::ShieldStun { .. });
                let alpha = if stunned { 0.6 } else { 0.25 + 0.2 * health };
                view.shield_material.set_albedo(Color { a: alpha, ..view.color.lightened(0.3) });
            }
        }
    }

    /// Debug view: hitboxes red, grab boxes purple.
    fn update_hitboxes(&mut self) {
        let active = if self.show_hitboxes { self.world.active_hitboxes() } else { Vec::new() };
        while self.hitbox_pool.len() < active.len() {
            let (node, mut mat) = sphere_instance(Color::from_rgba(1.0, 0.1, 0.1, 0.5));
            mat.set_flag(Flags::DISABLE_DEPTH_TEST, true);
            self.base_mut().add_child(&node);
            self.hitbox_pool.push((node, mat));
        }
        for (i, (node, mat)) in self.hitbox_pool.iter_mut().enumerate() {
            match active.get(i) {
                Some(hb) => {
                    let diameter = hb.radius.to_f32() * 2.0 * SCALE;
                    node.set_position(to_godot(hb.x, hb.y));
                    node.set_scale(Vector3::splat(diameter));
                    node.set_visible(true);
                    mat.set_albedo(if hb.grab { Color::from_rgba(0.7, 0.2, 1.0, 0.5) } else { Color::from_rgba(1.0, 0.1, 0.1, 0.5) });
                }
                None => node.set_visible(false),
            }
        }
    }

    /// Each projectile as its owner's `Shot`: the pug's sneeze is a pale glowing puff,
    /// the chef's pie a model flying cream first.
    fn update_projectiles(&mut self) {
        let projectiles = self.world.projectiles.clone();
        for (i, p) in projectiles.iter().enumerate() {
            let shot = look(self.world.fighters[p.owner].character).shot;
            if self.projectile_pool.get(i).is_none_or(|view| view.shot != shot) {
                let view = self.projectile_view(shot);
                self.base_mut().add_child(&view.node);
                if i < self.projectile_pool.len() {
                    std::mem::replace(&mut self.projectile_pool[i], view).node.queue_free();
                } else {
                    self.projectile_pool.push(view);
                }
            }
            let frame = self.world.frame as f32;
            let view = &mut self.projectile_pool[i];
            view.node.set_position(to_godot(p.x, p.y));
            view.node.set_visible(true);
            match shot {
                Shot::Orb(tint) => {
                    let color = tint.lerp(PLAYER_COLORS[p.owner % PLAYER_COLORS.len()], 0.2);
                    let pulse = 1.0 + 0.1 * ((self.time * 30.0).sin() as f32);
                    view.node.set_scale(Vector3::splat(p.radius().to_f32() * 2.0 * SCALE * pulse));
                    if let Some(mat) = &mut view.material {
                        mat.set_albedo(color);
                        mat.set_emission(color);
                    }
                }
                Shot::Model { scale, .. } => {
                    // Turned well toward the camera (more than the fighters, so the pie's
                    // face shows), nose up or down with its arc, wobbling a little.
                    let (vx, vy) = (p.vx.to_f32(), p.vy.to_f32());
                    let to_camera = MODEL_YAW_TO_CAMERA + 30.0;
                    let yaw = if vx < 0.0 { 180.0 + to_camera } else { -to_camera };
                    let tilt = vy.atan2(vx.abs());
                    let wobble = 0.25 * (frame * 0.35).sin();
                    view.node.set_basis(Basis::from_euler(EulerOrder::YZX, Vector3::new(wobble, yaw.to_radians(), tilt)));
                    view.node.set_scale(Vector3::splat(scale));
                }
            }
        }
        for view in self.projectile_pool.iter_mut().skip(projectiles.len()) {
            view.node.set_visible(false);
        }
    }

    fn projectile_view(&self, shot: Shot) -> ProjectileView {
        match shot {
            Shot::Orb(_) => {
                let (node, mut mat) = sphere_instance(Color::WHITE);
                mat.set_feature(godot::classes::base_material_3d::Feature::EMISSION, true);
                mat.set_emission_energy_multiplier(3.0);
                ProjectileView { node: node.upcast(), material: Some(mat), shot }
            }
            Shot::Model { path, .. } => ProjectileView { node: load::<PackedScene>(path).instantiate_as::<Node3D>(), material: None, shot },
        }
    }

    /// The cream color if `attacker`'s hit came from a projectile that splats.
    fn splat_color(&self, attacker: usize, projectile: bool) -> Option<Color> {
        match look(self.world.fighters[attacker].character).shot {
            Shot::Model { splat, .. } if projectile => Some(splat),
            _ => None,
        }
    }

    /// A burst of cream blobs at `at`. With a `floor`, they land on it around a puddle.
    fn spawn_splat(&mut self, at: Vector3, color: Color, floor: Option<f32>) {
        let mut blobs = Vec::new();
        if let Some(y) = floor {
            blobs.push((Vector3::new(at.x, y + 0.01, at.z), Vector3::ZERO, Vector3::new(0.5, 0.06, 0.4), 90));
        } else {
            blobs.push((at, Vector3::ZERO, Vector3::splat(0.45), 10));
        }
        let up = if floor.is_some() { 0.05 } else { 0.03 };
        for k in 0..10 {
            // Spread evenly with a little variety; purely cosmetic.
            let angle = (k as f32 * 36.0 + (k * 17 % 11) as f32 * 3.0).to_radians();
            let speed = 0.03 + 0.004 * (k * 7 % 5) as f32;
            let velocity = Vector3::new(angle.cos() * speed, up + angle.sin().abs() * speed * 0.6, ((k * 13 % 7) as f32 - 3.0) * 0.006);
            let size = 0.06 + 0.012 * (k * 5 % 4) as f32;
            blobs.push((at + Vector3::new(0.0, 0.05, 0.0), velocity, Vector3::splat(size), if floor.is_some() { 70 } else { 28 }));
        }
        for (position, velocity, size, life) in blobs {
            let (mut node, mut mat) = sphere_instance(color);
            // Unshaded, or the sky's blue ambient light turns small blobs blue.
            mat.set_shading_mode(ShadingMode::UNSHADED);
            node.set_position(position);
            node.set_scale(size);
            self.base_mut().add_child(&node);
            self.splats.push(Splat { node, velocity, size, floor, frames_left: life, life });
        }
    }

    fn update_splats(&mut self) {
        for splat in &mut self.splats {
            splat.frames_left = splat.frames_left.saturating_sub(1);
            // Blobs at rest (puddles, and ones that have landed) stay put.
            let moving = splat.velocity != Vector3::ZERO;
            let mut position = splat.node.get_position() + splat.velocity;
            if moving {
                splat.velocity.y -= SPLAT_GRAVITY;
            }
            if let Some(floor) = splat.floor
                && moving
                && position.y < floor
            {
                // Lands and flattens into a dab.
                position.y = floor;
                splat.velocity = Vector3::ZERO;
                splat.size = Vector3::new(splat.size.x * 1.4, splat.size.y * 0.35, splat.size.z * 1.4);
            }
            splat.node.set_position(position);
            // Full size for the first 60% of its life, then shrinks away.
            let left = splat.frames_left as f32 / splat.life as f32;
            splat.node.set_scale(splat.size * (left / 0.4).min(1.0));
        }
        self.splats.retain_mut(|splat| {
            let alive = splat.frames_left > 0;
            if !alive {
                splat.node.queue_free();
            }
            alive
        });
    }

    fn spawn_spark(&mut self, at: Vector3, size: f32) {
        let (mut node, mut mat) = sphere_instance(Color::from_rgba(1.0, 0.9, 0.4, 0.9));
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
            label.set_text(&format!("{name} {}  {}%\n{}", f.character.name(), f.percent, stocks));
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
        State::Dodge { frame, .. } => u32::from(frame).saturating_sub(1),
        // Counts down, so play the clip's end: it always finishes back on the idle pose.
        State::Landing { frames_left } => length.saturating_sub(u32::from(frames_left)),
        _ => world_frame % length.max(1),
    };
    if anim.get_current_animation() != name {
        anim.play_ex().name(&name).done();
    }
    anim.seek_ex(f64::from(frame.min(length)) / ANIM_FPS).update(true).done();
}

/// A unit-diameter sphere; scale it to size.
fn sphere_instance(color: Color) -> (Gd<MeshInstance3D>, Gd<StandardMaterial3D>) {
    let mut sphere = SphereMesh::new_gd();
    sphere.set_radius(0.5);
    sphere.set_height(1.0);
    mesh_instance(sphere.upcast(), color)
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

/// Merges keyboard and (optionally) a gamepad into one sim input. `cstick_out`
/// remembers whether the right stick was pushed last frame.
fn read_input(player: usize, joypad: Option<i32>, cstick_out: &mut bool) -> SimInput {
    let input = Input::singleton();
    let key = |k: Key| input.is_physical_key_pressed(k);
    // left, right, up, down, attack, jump, special, shield, grab, smash
    let keys = match player {
        0 => [Key::A, Key::D, Key::W, Key::S, Key::J, Key::K, Key::L, Key::SEMICOLON, Key::U, Key::I],
        _ => [Key::LEFT, Key::RIGHT, Key::UP, Key::DOWN, Key::COMMA, Key::PERIOD, Key::SLASH, Key::M, Key::N, Key::B],
    };
    let [left, right, up, down, attack, jump, special, shield, grab, smash] = keys.map(key);
    let mut x = right as i32 as f32 - left as i32 as f32;
    let mut y = up as i32 as f32 - down as i32 as f32;
    let mut buttons = [
        (attack, SimInput::ATTACK),
        (jump || (player == 0 && key(Key::SPACE)), SimInput::JUMP),
        (special, SimInput::SPECIAL),
        (shield, SimInput::SHIELD),
        (grab, SimInput::GRAB),
        (smash, SimInput::SMASH),
    ]
    .into_iter()
    .fold(0, |bits, (held, bit)| if held { bits | bit } else { bits });

    if let Some(device) = joypad {
        let button = |b: JoyButton| input.is_joy_button_pressed(device, b);
        let axis = |a: JoyAxis| input.get_joy_axis(device, a);
        let (jx, jy) = (axis(JoyAxis::LEFT_X), -axis(JoyAxis::LEFT_Y));
        let dx = button(JoyButton::DPAD_RIGHT) as i32 as f32 - button(JoyButton::DPAD_LEFT) as i32 as f32;
        let dy = button(JoyButton::DPAD_UP) as i32 as f32 - button(JoyButton::DPAD_DOWN) as i32 as f32;
        // Whichever source is pushed furthest wins.
        let strongest = |keyboard: f32, analog: [f32; 2]| {
            analog.into_iter().fold(keyboard, |acc, a| if a.abs() > STICK_DEADZONE && a.abs() > acc.abs() { a } else { acc })
        };
        x = strongest(x, [jx, dx]);
        y = strongest(y, [jy, dy]);
        let pad = [
            (button(JoyButton::A), SimInput::ATTACK),
            (button(JoyButton::B), SimInput::SPECIAL),
            (button(JoyButton::X) || button(JoyButton::Y), SimInput::JUMP),
            (axis(JoyAxis::TRIGGER_LEFT) > TRIGGER_THRESHOLD || axis(JoyAxis::TRIGGER_RIGHT) > TRIGGER_THRESHOLD, SimInput::SHIELD),
            (button(JoyButton::LEFT_SHOULDER) || button(JoyButton::RIGHT_SHOULDER), SimInput::GRAB),
        ];
        buttons = pad.into_iter().fold(buttons, |bits, (held, bit)| if held { bits | bit } else { bits });

        // C-stick: on the frame it's pushed, a smash press aimed by the right stick
        // instead of the left. Holding it does nothing more (C-stick smashes don't charge).
        let (cx, cy) = (axis(JoyAxis::RIGHT_X), -axis(JoyAxis::RIGHT_Y));
        let out = cx.abs().max(cy.abs()) > CSTICK_THRESHOLD;
        if out && !*cstick_out {
            buttons |= SimInput::SMASH;
            (x, y) = if cx.abs() > cy.abs() { (cx.signum(), 0.0) } else { (0.0, cy.signum()) };
        }
        *cstick_out = out;
    }

    let axis = |v: f32| (v.clamp(-1.0, 1.0) * 100.0).round() as i8;
    SimInput { stick_x: axis(x), stick_y: axis(y), buttons }
}
