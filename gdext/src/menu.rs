//! Melee-style menus: stock count, then character select (hand cursors carrying coins
//! onto portraits, a HMN / CPU / N/A button and a CPU level slider per player), then
//! stage select. Pure state and layout, no nodes, so it's unit tested; `menu_view.rs`
//! draws it. Choosing a match isn't gameplay: the sim only sees the `MatchSetup` that
//! comes out.

use fight_sim::{Character, CpuLevel, StageId};
use godot::builtin::{Rect2, Vector2};

/// Controller ports, like Melee's four. Port `p` drives player slot `p`.
pub const PORTS: usize = 4;
pub const MAX_STOCKS: u8 = 99;
pub const DEFAULT_STOCKS: u8 = 3;
pub const DEFAULT_CPU_LEVEL: u8 = 3;
/// Pixels per frame with the stick all the way over.
const HAND_SPEED: f32 = 15.0;
const STICK_DEADZONE: f32 = 0.2;
pub const TOKEN_RADIUS: f32 = 26.0;
/// Holding left / right on the stock screen repeats after this many frames, then every `REPEAT_EVERY`.
const REPEAT_AFTER: u32 = 18;
const REPEAT_EVERY: u32 = 4;

/// One port's controls this frame, as held (not pressed) states. `stick` is in screen
/// space: +x right, +y down, each axis -1..=1.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct PortInput {
    /// A controller is connected to this port, so it has a hand.
    pub present: bool,
    pub stick: Vector2,
    /// Melee's A: click with the hand.
    pub confirm: bool,
    /// Melee's B: take your coin back.
    pub back: bool,
    /// Start: on to the next screen.
    pub start: bool,
    /// Back to the previous screen (quits from the first).
    pub exit: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Screen {
    Stocks,
    Characters,
    Stages,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SlotKind {
    Human,
    Cpu,
    Off,
}

impl SlotKind {
    pub fn label(self) -> &'static str {
        match self {
            SlotKind::Human => "HMN",
            SlotKind::Cpu => "CPU",
            SlotKind::Off => "N/A",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Slot {
    pub kind: SlotKind,
    /// Set while the slot's coin sits on a portrait.
    pub character: Option<Character>,
    pub cpu_level: u8,
    /// Where the coin sits. `None` while a hand carries it (or the slot is off).
    pub token: Option<Vector2>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Hand {
    pub present: bool,
    /// The fingertip, in screen pixels.
    pub pos: Vector2,
    /// The slot whose coin this hand carries.
    pub holding: Option<usize>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Player {
    /// Port and color: P2 stays blue even with P1 off.
    pub port: usize,
    pub character: Character,
    /// `Some(level)` for a CPU.
    pub cpu: Option<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MatchSetup {
    pub stocks: u8,
    pub stage: StageId,
    pub players: Vec<Player>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MenuEvent {
    StartMatch(MatchSetup),
    Quit,
}

// Layout, in the 1600x900 viewport (`godot/project.godot`). Shared by hit tests and drawing.
pub const SCREEN: Vector2 = Vector2::new(1600.0, 900.0);
const PORTRAIT_SIZE: Vector2 = Vector2::new(220.0, 250.0);
const PORTRAIT_GAP: f32 = 30.0;
const PORTRAIT_TOP: f32 = 140.0;
pub const SLOT_SIZE: Vector2 = Vector2::new(330.0, 330.0);
const SLOT_GAP: f32 = 30.0;
const SLOT_TOP: f32 = 520.0;
pub const CARD_SIZE: Vector2 = Vector2::new(330.0, 260.0);
const CARD_GAP: f32 = 30.0;
const CARD_TOP: f32 = 200.0;
/// Number of CPU level cells, one per level.
pub const LEVELS: u8 = CpuLevel::MAX;

/// Lays out `n` boxes of `size` in a centered row at `top`.
fn row(i: usize, n: usize, size: Vector2, gap: f32, top: f32) -> Rect2 {
    let width = n as f32 * size.x + (n - 1) as f32 * gap;
    let left = (SCREEN.x - width) / 2.0;
    Rect2::new(Vector2::new(left + i as f32 * (size.x + gap), top), size)
}

pub fn portrait_rect(i: usize) -> Rect2 {
    row(i, Character::ALL.len(), PORTRAIT_SIZE, PORTRAIT_GAP, PORTRAIT_TOP)
}

pub fn slot_rect(slot: usize) -> Rect2 {
    row(slot, PORTS, SLOT_SIZE, SLOT_GAP, SLOT_TOP)
}

/// The HMN / CPU / N/A button at the top left of a slot's panel.
pub fn toggle_rect(slot: usize) -> Rect2 {
    Rect2::new(slot_rect(slot).position + Vector2::new(12.0, 12.0), Vector2::new(96.0, 40.0))
}

/// Cell `level` (1-based) of a CPU slot's level slider.
pub fn level_rect(slot: usize, level: u8) -> Rect2 {
    let x = 92.0 + f32::from(level - 1) * 24.0;
    Rect2::new(slot_rect(slot).position + Vector2::new(x, 62.0), Vector2::new(22.0, 26.0))
}

/// Stage cards: one per `StageId::ALL`, then Random.
pub const CARDS: usize = StageId::ALL.len() + 1;

pub fn card_rect(i: usize) -> Rect2 {
    row(i, CARDS, CARD_SIZE, CARD_GAP, CARD_TOP)
}

/// The stage card `i` stands for, `None` for Random.
pub fn card_stage(i: usize) -> Option<StageId> {
    StageId::ALL.get(i).copied()
}

pub fn portrait_at(pos: Vector2) -> Option<usize> {
    (0..Character::ALL.len()).find(|&i| portrait_rect(i).contains_point(pos))
}

pub fn card_at(pos: Vector2) -> Option<usize> {
    (0..CARDS).find(|&i| card_rect(i).contains_point(pos))
}

/// Where a slot's coin goes when it's placed for you: spread out on the portrait so
/// coins don't stack.
fn default_token_pos(slot: usize, portrait: usize) -> Vector2 {
    let rect = portrait_rect(portrait);
    let offset = Vector2::new(if slot.is_multiple_of(2) { -40.0 } else { 40.0 }, if slot < 2 { -50.0 } else { 10.0 });
    rect.center() + offset
}

fn default_character(slot: usize) -> usize {
    slot % Character::ALL.len()
}

pub struct Menu {
    pub screen: Screen,
    pub stocks: u8,
    pub slots: [Slot; PORTS],
    pub hands: [Hand; PORTS],
    /// Stage select's single cursor, which every port moves.
    pub stage_cursor: Vector2,
    /// Counts up every update, for animation and picking a random stage.
    pub frame: u32,
    prev: [PortInput; PORTS],
    /// Frames left / right has been held on the stock screen.
    repeat: u32,
    /// The screen was just entered: buttons still held from before don't count as presses.
    fresh: bool,
}

impl Default for Menu {
    fn default() -> Self {
        Self::new()
    }
}

impl Menu {
    /// P1 and P2 human with their coins in hand, P3 and P4 off.
    pub fn new() -> Menu {
        let slots = std::array::from_fn(|p| Slot {
            kind: if p < 2 { SlotKind::Human } else { SlotKind::Off },
            character: None,
            cpu_level: DEFAULT_CPU_LEVEL,
            token: None,
        });
        let hands = std::array::from_fn(|p| Hand {
            present: false,
            pos: slot_rect(p).center() - Vector2::new(0.0, 60.0),
            holding: (p < 2).then_some(p),
        });
        Menu {
            screen: Screen::Stocks,
            stocks: DEFAULT_STOCKS,
            slots,
            hands,
            stage_cursor: card_rect(0).center(),
            frame: 0,
            prev: [PortInput::default(); PORTS],
            repeat: 0,
            fresh: true,
        }
    }

    /// Goes to `screen`. Buttons held at that moment are ignored until released.
    pub fn enter(&mut self, screen: Screen) {
        self.screen = screen;
        self.fresh = true;
        self.repeat = 0;
        if screen == Screen::Stages {
            self.stage_cursor = card_rect(0).center();
        }
    }

    /// Sets the menus to show `setup`'s choices (for a match started without them),
    /// with every coin placed.
    pub fn load(&mut self, setup: &MatchSetup) {
        self.stocks = setup.stocks;
        for hand in &mut self.hands {
            hand.holding = None;
        }
        for (s, slot) in self.slots.iter_mut().enumerate() {
            let player = setup.players.iter().find(|p| p.port == s);
            slot.kind = player.map_or(SlotKind::Off, |p| if p.cpu.is_some() { SlotKind::Cpu } else { SlotKind::Human });
            slot.cpu_level = player.and_then(|p| p.cpu).unwrap_or(DEFAULT_CPU_LEVEL);
            slot.character = player.map(|p| p.character);
            slot.token = player.and_then(|p| Character::ALL.iter().position(|&c| c == p.character)).map(|i| default_token_pos(s, i));
        }
    }

    /// Every active slot has a character, and at least two are playing.
    pub fn ready(&self) -> bool {
        let active: Vec<&Slot> = self.slots.iter().filter(|s| s.kind != SlotKind::Off).collect();
        active.len() >= 2 && active.iter().all(|s| s.character.is_some())
    }

    pub fn setup(&self, stage: StageId) -> MatchSetup {
        let players = (0..PORTS)
            .filter_map(|port| {
                let slot = &self.slots[port];
                let character = slot.character.filter(|_| slot.kind != SlotKind::Off)?;
                Some(Player { port, character, cpu: (slot.kind == SlotKind::Cpu).then_some(slot.cpu_level) })
            })
            .collect();
        MatchSetup { stocks: self.stocks, stage, players }
    }

    /// One frame (60 Hz) of menu input.
    pub fn update(&mut self, inputs: &[PortInput; PORTS]) -> Option<MenuEvent> {
        self.frame = self.frame.wrapping_add(1);
        for (p, input) in inputs.iter().enumerate() {
            self.hands[p].present = input.present;
            if !input.present {
                self.release(p);
            }
        }
        if self.fresh {
            self.fresh = false;
            self.prev = *inputs;
            return None;
        }
        let pressed = |f: fn(&PortInput) -> bool| -> [bool; PORTS] {
            std::array::from_fn(|p| inputs[p].present && f(&inputs[p]) && !f(&self.prev[p]))
        };
        let (confirm, back, start, exit) =
            (pressed(|i| i.confirm), pressed(|i| i.back), pressed(|i| i.start), pressed(|i| i.exit));
        self.prev = *inputs;
        let any = |presses: [bool; PORTS]| presses.contains(&true);

        match self.screen {
            Screen::Stocks => {
                if any(exit) {
                    return Some(MenuEvent::Quit);
                }
                self.change_stocks(inputs);
                if any(confirm) || any(start) {
                    self.enter(Screen::Characters);
                }
            }
            Screen::Characters => {
                for p in 0..PORTS {
                    if !self.hands[p].present {
                        continue;
                    }
                    let hand = &mut self.hands[p];
                    hand.pos = (hand.pos + deadzone(inputs[p].stick) * HAND_SPEED).clamp(Vector2::ZERO, SCREEN);
                    if confirm[p] {
                        self.click(p);
                    } else if back[p] {
                        self.take_back(p);
                    }
                }
                if any(exit) {
                    self.enter(Screen::Stocks);
                } else if any(start) && self.ready() {
                    self.enter(Screen::Stages);
                }
            }
            Screen::Stages => {
                let push = inputs.iter().filter(|i| i.present).fold(Vector2::ZERO, |sum, i| sum + deadzone(i.stick));
                let push = push.clamp(Vector2::new(-1.0, -1.0), Vector2::ONE);
                self.stage_cursor = (self.stage_cursor + push * HAND_SPEED).clamp(Vector2::ZERO, SCREEN);
                if any(exit) || any(back) {
                    self.enter(Screen::Characters);
                } else if any(confirm) || any(start) {
                    let card = card_at(self.stage_cursor)?;
                    let stage = card_stage(card).unwrap_or(StageId::ALL[self.frame as usize % StageId::ALL.len()]);
                    return Some(MenuEvent::StartMatch(self.setup(stage)));
                }
            }
        }
        None
    }

    fn change_stocks(&mut self, inputs: &[PortInput; PORTS]) {
        let x = inputs.iter().filter(|i| i.present).map(|i| i.stick.x).fold(0.0, |a: f32, b| if b.abs() > a.abs() { b } else { a });
        if x.abs() < 0.5 {
            self.repeat = 0;
            return;
        }
        let fire = self.repeat == 0 || (self.repeat >= REPEAT_AFTER && (self.repeat - REPEAT_AFTER).is_multiple_of(REPEAT_EVERY));
        self.repeat += 1;
        if fire {
            self.stocks = if x > 0.0 { self.stocks % MAX_STOCKS + 1 } else if self.stocks <= 1 { MAX_STOCKS } else { self.stocks - 1 };
        }
    }

    /// Hand `p` presses A where it is.
    fn click(&mut self, p: usize) {
        let pos = self.hands[p].pos;
        let holding = self.hands[p].holding;
        if let Some(slot) = holding
            && let Some(portrait) = portrait_at(pos)
        {
            self.place(slot, portrait, pos);
            self.hands[p].holding = None;
            return;
        }
        // Pick up a coin: your own, or any CPU's. The last drawn is on top.
        let grabbable = |s: usize, slot: &Slot| {
            (s == p || slot.kind == SlotKind::Cpu) && slot.token.is_some_and(|t| t.distance_to(pos) <= TOKEN_RADIUS)
        };
        if holding.is_none()
            && let Some(s) = (0..PORTS).rev().find(|&s| grabbable(s, &self.slots[s]))
        {
            self.slots[s].token = None;
            self.slots[s].character = None;
            self.hands[p].holding = Some(s);
            return;
        }
        if let Some(s) = (0..PORTS).find(|&s| toggle_rect(s).contains_point(pos)) {
            self.toggle(s);
            return;
        }
        for s in (0..PORTS).filter(|&s| self.slots[s].kind == SlotKind::Cpu) {
            if let Some(level) = (1..=LEVELS).find(|&l| level_rect(s, l).contains_point(pos)) {
                self.slots[s].cpu_level = level;
                return;
            }
        }
        // A shortcut Melee doesn't have: click a portrait to move your own coin there
        // (joining if your slot was off).
        if let Some(portrait) = portrait_at(pos)
            && !self.carried(p)
        {
            if self.slots[p].kind == SlotKind::Off {
                self.slots[p].kind = SlotKind::Human;
            }
            self.place(p, portrait, pos);
        }
    }

    /// B: your placed coin jumps back into your hand.
    fn take_back(&mut self, p: usize) {
        let slot = &mut self.slots[p];
        if self.hands[p].holding.is_none() && slot.kind != SlotKind::Off && slot.token.is_some() {
            slot.token = None;
            slot.character = None;
            self.hands[p].holding = Some(p);
        }
    }

    /// HMN → CPU → N/A → HMN. A port with no controller skips HMN.
    fn toggle(&mut self, s: usize) {
        let next = match self.slots[s].kind {
            SlotKind::Human => SlotKind::Cpu,
            SlotKind::Cpu => SlotKind::Off,
            SlotKind::Off if self.hands[s].present => SlotKind::Human,
            SlotKind::Off => SlotKind::Cpu,
        };
        self.set_kind(s, next);
    }

    pub fn set_kind(&mut self, s: usize, kind: SlotKind) {
        for hand in self.hands.iter_mut().filter(|h| h.holding == Some(s)) {
            hand.holding = None;
        }
        let slot = &mut self.slots[s];
        slot.kind = kind;
        match kind {
            SlotKind::Off => (slot.character, slot.token) = (None, None),
            _ if slot.character.is_some() => {}
            // A new human gets their coin in hand, Melee-style, if the hand is free.
            SlotKind::Human if self.hands[s].present && self.hands[s].holding.is_none() => self.hands[s].holding = Some(s),
            _ => {
                let portrait = default_character(s);
                self.place(s, portrait, default_token_pos(s, portrait));
            }
        }
    }

    /// Hand `p` lets go of whatever coin it has; the coin goes onto that slot's default character.
    fn release(&mut self, p: usize) {
        if let Some(s) = self.hands[p].holding.take() {
            let portrait = default_character(s);
            self.place(s, portrait, default_token_pos(s, portrait));
        }
    }

    /// Someone's hand is carrying slot `s`'s coin.
    fn carried(&self, s: usize) -> bool {
        self.hands.iter().any(|h| h.holding == Some(s))
    }

    fn place(&mut self, s: usize, portrait: usize, pos: Vector2) {
        let rect = portrait_rect(portrait).grow(-TOKEN_RADIUS);
        let slot = &mut self.slots[s];
        slot.character = Some(Character::ALL[portrait]);
        slot.token = Some(pos.clamp(rect.position, rect.end()));
    }
}

fn deadzone(stick: Vector2) -> Vector2 {
    let axis = |v: f32| if v.abs() < STICK_DEADZONE { 0.0 } else { v.clamp(-1.0, 1.0) };
    Vector2::new(axis(stick.x), axis(stick.y))
}

#[cfg(test)]
mod tests {
    use super::*;

    const IDLE: PortInput = PortInput { present: true, stick: Vector2::ZERO, confirm: false, back: false, start: false, exit: false };

    /// A menu with P1 and P2 plugged in, past the first (ignored) frame.
    fn menu() -> Menu {
        let mut m = Menu::new();
        step(&mut m, &[]);
        m
    }

    fn inputs(held: &[(usize, PortInput)]) -> [PortInput; PORTS] {
        let mut all = [PortInput::default(), PortInput::default(), PortInput::default(), PortInput::default()];
        all[0] = IDLE;
        all[1] = IDLE;
        for &(p, input) in held {
            all[p] = input;
        }
        all
    }

    fn step(m: &mut Menu, held: &[(usize, PortInput)]) -> Option<MenuEvent> {
        m.update(&inputs(held))
    }

    /// Presses and releases a button on port `p`. Returns the event from the press.
    fn tap(m: &mut Menu, p: usize, button: fn(&mut PortInput)) -> Option<MenuEvent> {
        let mut input = IDLE;
        button(&mut input);
        let event = step(m, &[(p, input)]);
        step(m, &[]);
        event
    }

    fn confirm(i: &mut PortInput) {
        i.confirm = true;
    }

    fn start(i: &mut PortInput) {
        i.start = true;
    }

    fn click_at(m: &mut Menu, p: usize, pos: Vector2) -> Option<MenuEvent> {
        m.hands[p].pos = pos;
        tap(m, p, confirm)
    }

    #[test]
    fn stocks_wrap_and_repeat_while_held() {
        let mut m = menu();
        let right = PortInput { stick: Vector2::new(1.0, 0.0), ..IDLE };
        step(&mut m, &[(0, right)]);
        assert_eq!(m.stocks, 4);
        for _ in 0..REPEAT_AFTER {
            step(&mut m, &[(0, right)]);
        }
        assert_eq!(m.stocks, 5, "repeats once the hold passes REPEAT_AFTER frames");
        step(&mut m, &[]);
        m.stocks = 1;
        step(&mut m, &[(1, PortInput { stick: Vector2::new(-1.0, 0.0), ..IDLE })]);
        assert_eq!(m.stocks, MAX_STOCKS);
    }

    #[test]
    fn first_frame_on_a_screen_ignores_held_buttons() {
        let mut m = Menu::new();
        let held = PortInput { confirm: true, ..IDLE };
        step(&mut m, &[(0, held)]);
        step(&mut m, &[(0, held)]);
        assert_eq!(m.screen, Screen::Stocks, "a button held from before isn't a press");
        step(&mut m, &[]);
        step(&mut m, &[(0, held)]);
        assert_eq!(m.screen, Screen::Characters);
    }

    #[test]
    fn humans_start_holding_their_coins_and_place_them_on_portraits() {
        let mut m = menu();
        tap(&mut m, 0, start);
        assert!(!m.ready(), "nobody has picked yet");
        assert_eq!(m.hands[0].holding, Some(0));
        click_at(&mut m, 0, portrait_rect(1).center());
        assert_eq!(m.slots[0].character, Some(Character::ALL[1]));
        assert_eq!(m.hands[0].holding, None);
        click_at(&mut m, 1, portrait_rect(0).center());
        assert!(m.ready());
    }

    #[test]
    fn b_takes_your_coin_back() {
        let mut m = menu();
        tap(&mut m, 0, start);
        click_at(&mut m, 0, portrait_rect(0).center());
        tap(&mut m, 0, |i| i.back = true);
        assert_eq!((m.slots[0].character, m.hands[0].holding), (None, Some(0)));
    }

    #[test]
    fn toggle_cycles_human_cpu_off_and_cpus_get_a_character() {
        let mut m = menu();
        tap(&mut m, 0, start);
        click_at(&mut m, 0, toggle_rect(1).center());
        assert_eq!(m.slots[1].kind, SlotKind::Cpu);
        assert_eq!(m.hands[1].holding, None, "the coin left P2's hand");
        assert!(m.slots[1].character.is_some(), "a CPU always has a character");
        click_at(&mut m, 0, toggle_rect(1).center());
        assert_eq!((m.slots[1].kind, m.slots[1].character), (SlotKind::Off, None));
        click_at(&mut m, 0, toggle_rect(1).center());
        assert_eq!(m.slots[1].kind, SlotKind::Human);
        // P4 has no controller, so it goes N/A → CPU → N/A.
        click_at(&mut m, 0, toggle_rect(3).center());
        click_at(&mut m, 0, toggle_rect(3).center());
        click_at(&mut m, 0, toggle_rect(3).center());
        assert_eq!(m.slots[3].kind, SlotKind::Cpu);
    }

    #[test]
    fn cpu_coins_can_be_moved_and_levels_set() {
        let mut m = menu();
        tap(&mut m, 0, start);
        // P1 puts its own coin down out of the way first.
        click_at(&mut m, 0, portrait_rect(0).position + Vector2::new(30.0, 220.0));
        click_at(&mut m, 0, toggle_rect(1).center());
        let coin = m.slots[1].token.unwrap();
        let before = m.slots[1].character.unwrap();
        click_at(&mut m, 0, coin);
        assert_eq!(m.hands[0].holding, Some(1), "picked up the CPU's coin");
        let other = Character::ALL.iter().position(|&c| c != before).unwrap();
        click_at(&mut m, 0, portrait_rect(other).center());
        assert_eq!(m.slots[1].character, Some(Character::ALL[other]));
        assert_eq!(m.hands[0].holding, None);

        click_at(&mut m, 0, level_rect(1, 9).center());
        assert_eq!(m.slots[1].cpu_level, 9);
    }

    #[test]
    fn humans_cannot_take_each_others_coins() {
        let mut m = menu();
        tap(&mut m, 0, start);
        click_at(&mut m, 1, portrait_rect(0).center());
        let coin = m.slots[1].token.unwrap();
        click_at(&mut m, 0, coin);
        assert_eq!(m.slots[0].character, Some(Character::ALL[0]), "P1 dropped its own coin there instead");
        assert!(m.slots[1].character.is_some(), "P2's coin stayed put");
    }

    #[test]
    fn start_needs_everyone_ready_then_stage_choice_starts_the_match() {
        let mut m = menu();
        tap(&mut m, 0, start);
        click_at(&mut m, 0, portrait_rect(0).center());
        tap(&mut m, 0, start);
        assert_eq!(m.screen, Screen::Characters, "P2 hasn't picked");
        click_at(&mut m, 0, toggle_rect(1).center());
        click_at(&mut m, 0, level_rect(1, 7).center());
        tap(&mut m, 1, start);
        assert_eq!(m.screen, Screen::Stages);

        m.stage_cursor = card_rect(1).center();
        let event = tap(&mut m, 0, confirm);
        let Some(MenuEvent::StartMatch(setup)) = event else { panic!("no match: {event:?}") };
        assert_eq!(setup.stage, StageId::ALL[1]);
        assert_eq!(setup.stocks, DEFAULT_STOCKS);
        assert_eq!(setup.players.len(), 2);
        assert_eq!(setup.players[0], Player { port: 0, character: Character::ALL[0], cpu: None });
        assert_eq!(setup.players[1].cpu, Some(7));
    }

    #[test]
    fn off_slots_are_skipped_but_keep_their_port() {
        let mut m = menu();
        tap(&mut m, 0, start);
        m.set_kind(0, SlotKind::Off);
        m.set_kind(2, SlotKind::Cpu);
        click_at(&mut m, 1, portrait_rect(0).center());
        let setup = m.setup(StageId::ALL[0]);
        assert_eq!(setup.players.iter().map(|p| p.port).collect::<Vec<_>>(), vec![1, 2]);
    }

    #[test]
    fn exit_goes_back_a_screen_and_quits_from_the_first() {
        let mut m = menu();
        tap(&mut m, 0, start);
        tap(&mut m, 0, |i| i.exit = true);
        assert_eq!(m.screen, Screen::Stocks);
        assert_eq!(tap(&mut m, 0, |i| i.exit = true), Some(MenuEvent::Quit));
    }

    #[test]
    fn unplugging_drops_the_coin_on_a_default_character() {
        let mut m = menu();
        tap(&mut m, 0, start);
        step(&mut m, &[(1, PortInput::default())]);
        assert_eq!(m.hands[1].holding, None);
        assert!(m.slots[1].character.is_some());
    }

    #[test]
    fn layout_fits_on_screen_without_overlaps() {
        let screen = Rect2::new(Vector2::ZERO, SCREEN);
        let mut rects: Vec<Rect2> = (0..Character::ALL.len()).map(portrait_rect).chain((0..PORTS).map(slot_rect)).collect();
        for r in &rects {
            assert!(screen.encloses(*r), "{r:?} off screen");
        }
        while let Some(r) = rects.pop() {
            assert!(rects.iter().all(|o| !o.intersects(r)), "{r:?} overlaps");
        }
        for s in 0..PORTS {
            assert!(slot_rect(s).encloses(level_rect(s, LEVELS)), "level slider leaves panel {s}");
        }
        assert!(screen.encloses(card_rect(CARDS - 1)));
    }
}
