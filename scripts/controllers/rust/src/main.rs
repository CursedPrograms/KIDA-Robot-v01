// A robot's controller in Rust (egui). Everything about the robot is in ../robot.json, the same
// file the other languages read. Hold W A S D (Q E too, where it has them) to drive, Space to stop.
#![windows_subsystem = "windows"]
use eframe::egui;
use serde_json::Value;
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

const SPEC: &str = include_str!("../../robot.json");
const REPEAT: Duration = Duration::from_millis(200);

fn call(host: &str, port: u64, line: &str) -> Option<String> {
    let (verb, rest) = line.split_once(' ')?;
    let (path, body) = rest.split_once('|').unwrap_or((rest, ""));
    let url = format!("http://{host}:{port}{path}");
    let agent = ureq::AgentBuilder::new().timeout(Duration::from_millis(1500)).build();
    let r = if verb == "POST" {
        agent.post(&url).set("Content-Type", "application/json").send_string(body)
    } else {
        agent.get(&url).call()
    };
    r.ok().and_then(|r| r.into_string().ok())
}

fn colour(hex: &str) -> egui::Color32 {
    let n = u32::from_str_radix(hex.trim_start_matches('#'), 16).unwrap_or(0);
    egui::Color32::from_rgb((n >> 16) as u8, (n >> 8) as u8, n as u8)
}

fn path<'a>(v: &'a Value, key: &str) -> Option<&'a Value> {
    key.split('.').try_fold(v, |v, k| v.get(k))
}

struct App {
    spec: Value,
    host: Arc<Mutex<String>>,
    edit: String,
    status: Arc<Mutex<Option<Value>>>,
    send: mpsc::Sender<String>,
    held: Option<String>,
    last: Instant,
}

impl App {
    fn queue(&self, line: &str) {
        let _ = self.send.send(line.to_string());
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        ctx.request_repaint_after(Duration::from_millis(100));
        let accent = colour(self.spec["accent"].as_str().unwrap_or("#888888"));
        let mut want = None;
        ctx.input(|i| {
            for (k, name) in [(egui::Key::W, "w"), (egui::Key::S, "s"), (egui::Key::A, "a"),
                              (egui::Key::D, "d"), (egui::Key::Q, "q"), (egui::Key::E, "e")] {
                if i.key_down(k) {
                    want = self.spec["keys"][name].as_str().map(str::to_string);
                }
            }
        });
        let editing = ctx.wants_keyboard_input();
        if editing {
            want = None;
        }
        if want != self.held {
            if want.is_none() {
                self.queue(self.spec["stop"].as_str().unwrap_or(""));
            }
            self.held = want;
            self.last = Instant::now() - REPEAT;
        }
        if let Some(line) = self.held.clone() {
            if self.last.elapsed() >= REPEAT {
                self.queue(&line);
                self.last = Instant::now();
            }
        }
        if !editing && ctx.input(|i| i.key_pressed(egui::Key::Space)) {
            self.queue(self.spec["stop"].as_str().unwrap_or(""));
        }

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading(egui::RichText::new(self.spec["name"].as_str().unwrap_or("")).color(accent).size(26.0));
            ui.horizontal(|ui| {
                ui.text_edit_singleline(&mut self.edit);
                if ui.button("CONNECT").clicked() {
                    *self.host.lock().unwrap() = self.edit.clone();
                    for line in self.spec["connect"].as_array().into_iter().flatten() {
                        self.queue(line.as_str().unwrap_or(""));
                    }
                }
            });
            let status = self.status.lock().unwrap().clone();
            ui.label(if status.is_some() { "connected" } else { "no answer" });
            ui.separator();
            ui.horizontal_wrapped(|ui| {
                for b in self.spec["buttons"].as_array().into_iter().flatten() {
                    if ui.button(b[0].as_str().unwrap_or("")).clicked() {
                        self.queue(b[1].as_str().unwrap_or(""));
                    }
                }
                if ui.button("STOP").clicked() {
                    self.queue(self.spec["stop"].as_str().unwrap_or(""));
                }
            });
            ui.separator();
            ui.horizontal_wrapped(|ui| {
                for t in self.spec["tiles"].as_array().into_iter().flatten() {
                    let value = status.as_ref().and_then(|s| path(s, t[1].as_str().unwrap_or("")))
                        .map(|v| v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string()))
                        .unwrap_or_else(|| "--".into());
                    ui.group(|ui| {
                        ui.vertical(|ui| {
                            ui.small(t[0].as_str().unwrap_or(""));
                            ui.strong(format!("{value}{}", t[2].as_str().unwrap_or("")));
                        });
                    });
                }
            });
            ui.separator();
            ui.small("Hold W A S D to drive, Space to stop");
        });
    }
}

fn main() -> eframe::Result<()> {
    let spec: Value = serde_json::from_str(SPEC).expect("robot.json");
    let port = spec["port"].as_u64().unwrap_or(80);
    let start = std::env::args().nth(1).unwrap_or_else(|| spec["host"].as_str().unwrap_or("").to_string());
    let host = Arc::new(Mutex::new(start.clone()));
    let status = Arc::new(Mutex::new(None));
    let (send, recv) = mpsc::channel::<String>();
    if !start.is_empty() {
        for line in spec["connect"].as_array().into_iter().flatten() {
            let _ = send.send(line.as_str().unwrap_or("").to_string());
        }
    }
    let h = host.clone();
    std::thread::spawn(move || {
        while let Ok(line) = recv.recv() {
            let target = h.lock().unwrap().clone();
            let _ = call(&target, port, &line);
        }
    });
    let (h, s, line) = (host.clone(), status.clone(), format!("GET {}", spec["status"].as_str().unwrap_or("/status")));
    std::thread::spawn(move || loop {
        let target = h.lock().unwrap().clone();
        let now = call(&target, port, &line).and_then(|b| serde_json::from_str(&b).ok());
        *s.lock().unwrap() = now;
        std::thread::sleep(Duration::from_millis(500));
    });
    let title = format!("{} controller", spec["name"].as_str().unwrap_or(""));
    let app = App { spec, host, edit: start, status, send, held: None, last: Instant::now() };
    let options = eframe::NativeOptions { viewport: egui::ViewportBuilder::default().with_inner_size([560.0, 340.0]), ..Default::default() };
    eframe::run_native(&title, options, Box::new(|_| Ok(Box::new(app))))
}
