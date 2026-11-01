# KIDA-01's controllers in other languages

Python and the Windows exe are KIDA-01's main controllers. These are the same small controller in five languages, all reading `robot.json`, which holds KIDA-01's commands, buttons and sensors. Change it there and they all change.

Hold W / S to drive forward and back, A / D to turn. Space or STOP stops it in any mode. These have no keys, click them in the window: DRIVE, HELLO, DANCE, PHOTO, MUSIC, STOP MUSIC, LOCK. Pass the address as the first argument, or type it in.

| Language | UI | Run |
|---|---|---|
| C# | WinForms | `dotnet run --project csharp` |
| F# | WinForms | `dotnet run --project fsharp` |
| Rust | egui | `cargo run --release --manifest-path rust/Cargo.toml` |
| Go | Ebitengine | `cd go && go run .` (Go builds its own copy of `robot.json` in, so change both) |
| Julia | GLMakie | `julia julia/controller.jl` |
