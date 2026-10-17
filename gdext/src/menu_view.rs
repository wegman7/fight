//! Draws a `menu::Menu` as Control nodes on a CanvasLayer over the beach. Everything
//! is built once in `MenuView::new`; `update` only moves, recolors and shows or hides
//! nodes, except that a slot's 3D render swaps models when its character changes.

use crate::menu::{self, Menu, PORTS, Screen, SlotKind, TOKEN_RADIUS};
use crate::{ANIM_FPS, PLAYER_COLORS, SCALE, styled_label, tinted_model};
use fight_sim::{Character, StageId};
use godot::classes::control::MouseFilter;
use godot::classes::environment::AmbientSource;
use godot::classes::viewport::Msaa;
use godot::classes::{
    AnimationPlayer, Camera3D, CanvasLayer, ColorRect, Control, DirectionalLight3D, Environment, Label, Line2D, Node2D, Panel,
    Polygon2D, StyleBoxFlat, SubViewport, SubViewportContainer,
};
use godot::global::{HorizontalAlignment, VerticalAlignment};
use godot::prelude::*;

const BACKDROP: Color = Color::from_rgba(0.03, 0.05, 0.14, 0.62);
const PANEL_BG: Color = Color::from_rgba(0.08, 0.1, 0.2, 0.85);
const PANEL_BORDER: Color = Color::from_rgb(0.3, 0.35, 0.55);
const HIGHLIGHT: Color = Color::from_rgb(1.0, 0.95, 0.7);
const DIM_TEXT: Color = Color::from_rgba(1.0, 1.0, 1.0, 0.55);
/// The color portraits tint a character's `Body`, so they show no player's color.
const PORTRAIT_TINT: Color = Color::from_rgb(0.85, 0.85, 0.88);
/// How far the menu renders turn a model (built facing +X) toward the camera.
const RENDER_YAW: f32 = -55.0;
/// Classic arrow pointer, tip at the origin.
const POINTER: [Vector2; 7] = [
    Vector2::new(0.0, 0.0),
    Vector2::new(0.0, 38.0),
    Vector2::new(10.0, 29.0),
    Vector2::new(17.0, 44.0),
    Vector2::new(24.0, 41.0),
    Vector2::new(17.0, 27.0),
    Vector2::new(29.0, 27.0),
];

pub struct MenuView {
    pub layer: Gd<CanvasLayer>,
    /// One per `Screen`, in `SCREENS` order.
    screens: Vec<Gd<Control>>,
    stock_value: Gd<Label>,
    stock_dots: Gd<Label>,
    rules: Gd<Label>,
    portraits: Vec<(Gd<StyleBoxFlat>, Render)>,
    slots: Vec<SlotView>,
    tokens: Vec<(Gd<Panel>, Gd<Label>)>,
    hands: Vec<Gd<Node2D>>,
    banner: Gd<Panel>,
    cards: Vec<Gd<StyleBoxFlat>>,
    stage_name: Gd<Label>,
    stage_blurb: Gd<Label>,
    stage_cursor: Gd<Node2D>,
}

const SCREENS: [Screen; 3] = [Screen::Stocks, Screen::Characters, Screen::Stages];

struct SlotView {
    style: Gd<StyleBoxFlat>,
    toggle: Gd<StyleBoxFlat>,
    toggle_label: Gd<Label>,
    name: Gd<Label>,
    level_label: Gd<Label>,
    level_cells: Vec<(Gd<Panel>, Gd<StyleBoxFlat>)>,
    render: Render,
}

/// A character model in its own little 3D world, shown in a 2D panel.
struct Render {
    viewport: Gd<SubViewport>,
    camera: Gd<Camera3D>,
    model: Option<(Gd<Node3D>, Gd<AnimationPlayer>)>,
    shown: Option<(Character, Color)>,
}

impl MenuView {
    pub fn new() -> MenuView {
        let mut layer = CanvasLayer::new_alloc();
        layer.set_layer(2);
        let mut backdrop = ColorRect::new_alloc();
        backdrop.set_color(BACKDROP);
        backdrop.set_size(menu::SCREEN);
        backdrop.set_mouse_filter(MouseFilter::IGNORE);
        layer.add_child(&backdrop);

        let mut screens: Vec<Gd<Control>> = SCREENS
            .iter()
            .map(|_| {
                let mut screen = Control::new_alloc();
                screen.set_size(menu::SCREEN);
                screen.set_mouse_filter(MouseFilter::IGNORE);
                layer.add_child(&screen);
                screen
            })
            .collect();

        // Stocks.
        let stocks = &mut screens[0];
        stocks.add_child(&text("STOCK MATCH", 56, Color::WHITE, rect(0.0, 150.0, menu::SCREEN.x, 80.0)));
        stocks.add_child(&text("How many stocks?", 26, DIM_TEXT, rect(0.0, 225.0, menu::SCREEN.x, 40.0)));
        let (box_panel, _) = panel(rect(530.0, 300.0, 540.0, 300.0), PANEL_BG, PANEL_BORDER, 3, 18);
        stocks.add_child(&box_panel);
        let stock_value = text("3", 140, Color::WHITE, rect(530.0, 320.0, 540.0, 190.0));
        stocks.add_child(&stock_value);
        for dir in [-1.0, 1.0] {
            let mut arrow = Polygon2D::new_alloc();
            let tip = 800.0 + dir * 220.0;
            let back = 800.0 + dir * 170.0;
            arrow.set_polygon(&PackedVector2Array::from(&[
                Vector2::new(tip, 415.0),
                Vector2::new(back, 380.0),
                Vector2::new(back, 450.0),
            ]));
            arrow.set_color(HIGHLIGHT);
            stocks.add_child(&arrow);
        }
        let stock_dots = text("", 30, PLAYER_COLORS[0], rect(530.0, 520.0, 540.0, 50.0));
        stocks.add_child(&stock_dots);
        stocks.add_child(&hint("Left / Right: stocks    J  ,  pad A  or  Enter / Start: continue    Esc: quit"));

        // Character select.
        let characters = &mut screens[1];
        characters.add_child(&text("CHOOSE YOUR CHARACTER", 46, Color::WHITE, rect(0.0, 30.0, menu::SCREEN.x, 70.0)));
        let rules = text("", 26, HIGHLIGHT, rect(1180.0, 46.0, 380.0, 40.0));
        rules.clone().set_horizontal_alignment(HorizontalAlignment::RIGHT);
        characters.add_child(&rules);
        let mut portraits = Vec::new();
        for (i, &character) in Character::ALL.iter().enumerate() {
            let r = menu::portrait_rect(i);
            let (mut frame, style) = panel(r, PANEL_BG, PANEL_BORDER, 4, 12);
            let mut render = Render::new(&mut frame, rect(10.0, 10.0, r.size.x - 20.0, r.size.y - 64.0));
            render.show(Some((character, PORTRAIT_TINT)));
            frame.add_child(&text(&character.name().to_uppercase(), 30, Color::WHITE, rect(0.0, r.size.y - 56.0, r.size.x, 48.0)));
            characters.add_child(&frame);
            portraits.push((style, render));
        }
        let (mut banner, _) = panel(rect(0.0, 418.0, menu::SCREEN.x, 84.0), Color::from_rgba(0.85, 0.12, 0.1, 0.92), HIGHLIGHT, 0, 0);
        banner.add_child(&text("READY TO FIGHT!", 46, Color::WHITE, rect(0.0, 0.0, menu::SCREEN.x, 58.0)));
        banner.add_child(&text("Press Start / Enter", 20, HIGHLIGHT, rect(0.0, 52.0, menu::SCREEN.x, 28.0)));
        characters.add_child(&banner);
        let slots: Vec<SlotView> = (0..PORTS).map(|s| SlotView::new(characters, s)).collect();
        let tokens: Vec<(Gd<Panel>, Gd<Label>)> = (0..PORTS)
            .map(|s| {
                let d = TOKEN_RADIUS * 2.0;
                let color = PLAYER_COLORS[s];
                let (mut coin, _) = panel(rect(0.0, 0.0, d, d), color, Color::WHITE, 3, TOKEN_RADIUS as i32);
                let label = text("", 18, Color::WHITE, rect(0.0, 0.0, d, d));
                coin.add_child(&label);
                characters.add_child(&coin);
                (coin, label)
            })
            .collect();
        let hands: Vec<Gd<Node2D>> = (0..PORTS)
            .map(|p| {
                let hand = pointer(PLAYER_COLORS[p], &format!("P{}", p + 1));
                characters.add_child(&hand);
                hand
            })
            .collect();
        characters.add_child(&hint(
            "Move your hand · J  ,  pad A: pick up / drop your coin, click HMN/CPU, set CPU level · L  /  pad B: take your coin back · Enter / Start: fight · Esc: back",
        ));

        // Stage select.
        let stages = &mut screens[2];
        stages.add_child(&text("CHOOSE A STAGE", 46, Color::WHITE, rect(0.0, 80.0, menu::SCREEN.x, 70.0)));
        let mut cards = Vec::new();
        for i in 0..menu::CARDS {
            let r = menu::card_rect(i);
            let (mut card, style) = panel(r, PANEL_BG, PANEL_BORDER, 4, 12);
            draw_stage_preview(&mut card, menu::card_stage(i), rect(15.0, 15.0, r.size.x - 30.0, 170.0));
            let name = menu::card_stage(i).map_or("Random", StageId::name);
            card.add_child(&text(&name.to_uppercase(), 30, Color::WHITE, rect(0.0, 192.0, r.size.x, 56.0)));
            stages.add_child(&card);
            cards.push(style);
        }
        let stage_name = text("", 72, Color::WHITE, rect(0.0, 520.0, menu::SCREEN.x, 100.0));
        stages.add_child(&stage_name);
        let stage_blurb = text("", 26, DIM_TEXT, rect(0.0, 615.0, menu::SCREEN.x, 40.0));
        stages.add_child(&stage_blurb);
        let stage_cursor = pointer(Color::WHITE, "");
        stages.add_child(&stage_cursor);
        stages.add_child(&hint("Any stick: move · J  ,  pad A: pick · L  /  pad B or Esc: back to characters"));

        MenuView {
            layer,
            screens,
            stock_value,
            stock_dots,
            rules,
            portraits,
            slots,
            tokens,
            hands,
            banner,
            cards,
            stage_name,
            stage_blurb,
            stage_cursor,
        }
    }

    pub fn set_visible(&mut self, visible: bool) {
        self.layer.set_visible(visible);
    }

    pub fn update(&mut self, menu: &Menu) {
        for (screen, node) in SCREENS.iter().zip(&mut self.screens) {
            node.set_visible(*screen == menu.screen);
        }
        match menu.screen {
            Screen::Stocks => {
                self.stock_value.set_text(&menu.stocks.to_string());
                let dots = usize::from(menu.stocks).min(12);
                let more = if menu.stocks > 12 { " …" } else { "" };
                self.stock_dots.set_text(&format!("{}{more}", "● ".repeat(dots)));
            }
            Screen::Characters => self.update_characters(menu),
            Screen::Stages => self.update_stages(menu),
        }
    }

    fn update_characters(&mut self, menu: &Menu) {
        let plural = if menu.stocks == 1 { "" } else { "S" };
        self.rules.set_text(&format!("{} STOCK{plural}", menu.stocks));
        let present_hands: Vec<Vector2> = menu.hands.iter().filter(|h| h.present).map(|h| h.pos).collect();
        for (i, (style, render)) in self.portraits.iter_mut().enumerate() {
            let hovered = present_hands.iter().any(|&p| menu::portrait_rect(i).contains_point(p));
            set_border(style, if hovered { HIGHLIGHT } else { PANEL_BORDER }, if hovered { 6 } else { 4 });
            render.animate(menu.frame);
        }
        for (s, view) in self.slots.iter_mut().enumerate() {
            let hovered = present_hands.iter().any(|&p| menu::toggle_rect(s).contains_point(p));
            view.update(s, &menu.slots[s], hovered, menu.frame);
        }
        for (s, (coin, label)) in self.tokens.iter_mut().enumerate() {
            let slot = &menu.slots[s];
            let carrier = menu.hands.iter().find(|h| h.holding == Some(s)).map(|h| h.pos);
            let at = slot.token.or(carrier).filter(|_| slot.kind != SlotKind::Off);
            coin.set_visible(at.is_some());
            if let Some(at) = at {
                coin.set_position(at - Vector2::splat(TOKEN_RADIUS));
                // Lifted a little while carried, like Melee's.
                coin.set_scale(Vector2::splat(if carrier.is_some() { 1.12 } else { 1.0 }));
                coin.set_pivot_offset(Vector2::splat(TOKEN_RADIUS));
            }
            label.set_text(&if slot.kind == SlotKind::Cpu { "CP".to_string() } else { format!("{}", s + 1) });
        }
        for (hand, state) in self.hands.iter_mut().zip(&menu.hands) {
            hand.set_visible(state.present);
            hand.set_position(state.pos);
        }
        self.banner.set_visible(menu.ready());
        let pulse = 0.85 + 0.15 * (menu.frame as f32 * 0.12).sin();
        self.banner.set_modulate(Color::from_rgba(1.0, 1.0, 1.0, pulse));
    }

    fn update_stages(&mut self, menu: &Menu) {
        let hovered = menu::card_at(menu.stage_cursor);
        for (i, style) in self.cards.iter_mut().enumerate() {
            let on = hovered == Some(i);
            set_border(style, if on { HIGHLIGHT } else { PANEL_BORDER }, if on { 7 } else { 4 });
        }
        let (name, blurb) = match hovered.map(menu::card_stage) {
            Some(Some(stage)) => (stage.name(), stage_blurb(stage)),
            Some(None) => ("Random", "Let the tide decide"),
            None => ("", ""),
        };
        self.stage_name.set_text(&name.to_uppercase());
        self.stage_blurb.set_text(blurb);
        self.stage_cursor.set_position(menu.stage_cursor);
    }
}

fn stage_blurb(stage: StageId) -> &'static str {
    match stage {
        StageId::Boardwalk => "Three driftwood rafts over the boardwalk",
        StageId::Sandbar => "One long, flat stage. No platforms, no excuses.",
        StageId::Driftwood => "A smaller stage under a single raft",
    }
}

impl SlotView {
    fn new(parent: &mut Gd<Control>, s: usize) -> SlotView {
        let r = menu::slot_rect(s);
        let (mut frame, style) = panel(r, PANEL_BG, PLAYER_COLORS[s], 4, 14);
        let render = Render::new(&mut frame, rect(15.0, 92.0, r.size.x - 30.0, 190.0));
        let toggle_rect = menu::toggle_rect(s);
        let (mut toggle_panel, toggle) =
            panel(Rect2::new(toggle_rect.position - r.position, toggle_rect.size), PANEL_BG, Color::WHITE, 2, 8);
        let toggle_label = text("", 24, Color::WHITE, Rect2::new(Vector2::ZERO, toggle_rect.size));
        toggle_panel.add_child(&toggle_label);
        frame.add_child(&toggle_panel);
        frame.add_child(&{
            let mut port = text(&format!("P{}", s + 1), 34, PLAYER_COLORS[s], rect(r.size.x - 112.0, 10.0, 100.0, 44.0));
            port.set_horizontal_alignment(HorizontalAlignment::RIGHT);
            port
        });
        let level_label = text("", 20, Color::WHITE, rect(12.0, 62.0, 76.0, 26.0));
        frame.add_child(&level_label);
        let level_cells = (1..=menu::LEVELS)
            .map(|level| {
                let cell = menu::level_rect(s, level);
                let (node, style) = panel(Rect2::new(cell.position - r.position, cell.size), PANEL_BG, Color::WHITE, 2, 4);
                frame.add_child(&node);
                (node, style)
            })
            .collect();
        let name = text("", 32, Color::WHITE, rect(0.0, r.size.y - 50.0, r.size.x, 44.0));
        frame.add_child(&name);
        parent.add_child(&frame);
        SlotView { style, toggle, toggle_label, name, level_label, level_cells, render }
    }

    fn update(&mut self, s: usize, slot: &menu::Slot, toggle_hovered: bool, frame: u32) {
        let color = PLAYER_COLORS[s];
        let (bg, border) = match slot.kind {
            SlotKind::Human => (color.darkened(0.55), color),
            SlotKind::Cpu => (Color::from_rgb(0.22, 0.23, 0.27).lerp(color, 0.15), color.darkened(0.3)),
            SlotKind::Off => (Color::from_rgba(0.05, 0.05, 0.08, 0.75), Color::from_rgb(0.25, 0.25, 0.3)),
        };
        self.style.set_bg_color(Color { a: 0.92, ..bg });
        self.style.set_border_color(border);
        self.toggle.set_bg_color(if toggle_hovered { color.darkened(0.2) } else { Color::from_rgba(0.0, 0.0, 0.0, 0.45) });
        self.toggle_label.set_text(slot.kind.label());

        let cpu = slot.kind == SlotKind::Cpu;
        self.level_label.set_visible(cpu);
        self.level_label.set_text(&format!("LV {}", slot.cpu_level));
        for (i, (node, style)) in self.level_cells.iter_mut().enumerate() {
            node.set_visible(cpu);
            let filled = i < usize::from(slot.cpu_level);
            style.set_bg_color(if filled { color.lightened(0.15) } else { Color::from_rgba(0.0, 0.0, 0.0, 0.4) });
        }

        let name = match (slot.kind, slot.character) {
            (SlotKind::Off, _) => String::new(),
            (_, Some(c)) => c.name().to_uppercase(),
            (_, None) => "· · ·".to_string(),
        };
        self.name.set_text(&name);
        let shown = slot.character.filter(|_| slot.kind != SlotKind::Off);
        self.render.show(shown.map(|c| (c, color)));
        self.render.animate(frame);
    }
}

impl Render {
    fn new(parent: &mut Gd<impl Inherits<Node>>, r: Rect2) -> Render {
        let mut container = SubViewportContainer::new_alloc();
        container.set_stretch(true);
        container.set_position(r.position);
        container.set_size(r.size);
        container.set_mouse_filter(MouseFilter::IGNORE);
        let mut viewport = SubViewport::new_alloc();
        viewport.set_size(Vector2i::new(r.size.x as i32, r.size.y as i32));
        viewport.set_use_own_world_3d(true);
        viewport.set_transparent_background(true);
        viewport.set_msaa_3d(Msaa::MSAA_4X);

        let mut env = Environment::new_gd();
        env.set_ambient_source(AmbientSource::COLOR);
        env.set_ambient_light_color(Color::from_rgb(0.75, 0.8, 0.9));
        env.set_ambient_light_energy(0.7);
        let mut camera = Camera3D::new_alloc();
        camera.set_fov(30.0);
        camera.set_environment(&env);
        let mut light = DirectionalLight3D::new_alloc();
        light.set_rotation_degrees(Vector3::new(-35.0, -30.0, 0.0));
        light.set_param(godot::classes::light_3d::Param::ENERGY, 1.3);
        viewport.add_child(&camera);
        viewport.add_child(&light);
        container.add_child(&viewport);
        parent.clone().upcast::<Node>().add_child(&container);
        Render { viewport, camera, model: None, shown: None }
    }

    /// Shows `character` with its `Body` in the color, or nothing. Only reloads on a change.
    fn show(&mut self, wanted: Option<(Character, Color)>) {
        if self.shown == wanted {
            return;
        }
        self.shown = wanted;
        if let Some((model, _)) = self.model.take() {
            model.free();
        }
        let Some((character, color)) = wanted else { return };
        let (mut model, _) = tinted_model(character, color);
        model.set_rotation_degrees(Vector3::new(0.0, RENDER_YAW, 0.0));
        let mut anim = model.get_node_as::<AnimationPlayer>("AnimationPlayer");
        anim.set_callback_mode_process(godot::classes::animation_mixer::AnimationCallbackModeProcess::MANUAL);
        self.viewport.add_child(&model);
        // Frame the whole fighter, whatever its size.
        let height = character.params().height.to_f32() * SCALE;
        self.camera.set_position(Vector3::new(0.0, height * 0.6, height * 2.5));
        self.camera.set_rotation_degrees(Vector3::new(-4.0, 0.0, 0.0));
        self.model = Some((model, anim));
    }

    /// Loops the idle pose on the menu's clock (the player is never left free-running).
    fn animate(&mut self, frame: u32) {
        let Some((_, anim)) = &mut self.model else { return };
        let Some(clip) = anim.get_animation("idle") else { return };
        let length = ((clip.get_length() * ANIM_FPS).round() as u32).max(1);
        if anim.get_current_animation() != "idle" {
            anim.play_ex().name("idle").done();
        }
        anim.seek_ex(f64::from(frame % length) / ANIM_FPS).update(true).done();
    }
}

/// A schematic of the stage: sky, sea, the main stage on its rock and the soft platforms.
/// Random gets a big question mark.
fn draw_stage_preview(card: &mut Gd<Panel>, stage: Option<StageId>, area: Rect2) {
    let mut add_rect = |r: Rect2, color: Color| {
        let mut node = ColorRect::new_alloc();
        node.set_position(r.position);
        node.set_size(r.size);
        node.set_color(color);
        node.set_mouse_filter(MouseFilter::IGNORE);
        card.add_child(&node);
    };
    add_rect(area, Color::from_rgb(0.45, 0.7, 0.92));
    add_rect(rect(area.position.x, area.end().y - 26.0, area.size.x, 26.0), Color::from_rgb(0.12, 0.45, 0.62));
    let Some(stage) = stage else {
        card.add_child(&text("?", 120, Color::WHITE, area));
        return;
    };
    let stage = stage.stage();
    let to_px = |x: f32, y: f32| Vector2::new(area.center().x + x * 1.05, area.position.y + 112.0 - y * 1.35);
    for p in &stage.platforms {
        let left = to_px(p.left.to_f32(), p.y.to_f32());
        let width = (p.right - p.left).to_f32() * 1.05;
        if p.soft {
            add_rect(Rect2::new(left, Vector2::new(width, 5.0)), Color::from_rgb(0.62, 0.45, 0.28));
        } else {
            add_rect(Rect2::new(left + Vector2::new(width * 0.12, 8.0), Vector2::new(width * 0.76, 24.0)), Color::from_rgb(0.72, 0.6, 0.45));
            add_rect(Rect2::new(left, Vector2::new(width, 9.0)), Color::from_rgb(0.55, 0.38, 0.22));
        }
    }
}

/// A mouse-pointer-shaped hand with an outline and a tag.
fn pointer(color: Color, tag: &str) -> Gd<Node2D> {
    let mut hand = Node2D::new_alloc();
    let points = PackedVector2Array::from(&POINTER);
    let mut fill = Polygon2D::new_alloc();
    fill.set_polygon(&points);
    fill.set_color(color);
    hand.add_child(&fill);
    let mut outline = Line2D::new_alloc();
    outline.set_points(&points);
    outline.set_closed(true);
    outline.set_width(3.0);
    outline.set_default_color(Color::BLACK);
    hand.add_child(&outline);
    if !tag.is_empty() {
        let mut label = styled_label(20, color);
        label.set_text(tag);
        label.set_position(Vector2::new(24.0, 34.0));
        hand.add_child(&label);
    }
    hand
}

fn rect(x: f32, y: f32, w: f32, h: f32) -> Rect2 {
    Rect2::new(Vector2::new(x, y), Vector2::new(w, h))
}

/// A centered, outlined label filling `r`.
fn text(content: &str, size: i32, color: Color, r: Rect2) -> Gd<Label> {
    let mut label = styled_label(size, color);
    label.set_text(content);
    label.set_position(r.position);
    label.set_size(r.size);
    label.set_horizontal_alignment(HorizontalAlignment::CENTER);
    label.set_vertical_alignment(VerticalAlignment::CENTER);
    label.set_mouse_filter(MouseFilter::IGNORE);
    label
}

fn hint(content: &str) -> Gd<Label> {
    let mut label = text(content, 18, DIM_TEXT, rect(0.0, 858.0, menu::SCREEN.x, 36.0));
    label.set_autowrap_mode(godot::classes::text_server::AutowrapMode::WORD_SMART);
    label
}

/// A rounded box. Returns its style too, to recolor it later.
fn panel(r: Rect2, bg: Color, border: Color, border_width: i32, radius: i32) -> (Gd<Panel>, Gd<StyleBoxFlat>) {
    let mut style = StyleBoxFlat::new_gd();
    style.set_bg_color(bg);
    style.set_border_color(border);
    style.set_border_width_all(border_width);
    style.set_corner_radius_all(radius);
    let mut node = Panel::new_alloc();
    node.add_theme_stylebox_override("panel", &style);
    node.set_position(r.position);
    node.set_size(r.size);
    node.set_mouse_filter(MouseFilter::IGNORE);
    (node, style)
}

fn set_border(style: &mut Gd<StyleBoxFlat>, color: Color, width: i32) {
    style.set_border_color(color);
    style.set_border_width_all(width);
}
