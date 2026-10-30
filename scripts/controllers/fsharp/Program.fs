// A robot's controller in F# (WinForms). Everything about the robot is in ../robot.json, the same
// file the other languages read. Hold W A S D (Q E too, where it has them) to drive, Space to stop.
module Controller

open System
open System.Collections.Generic
open System.Drawing
open System.IO
open System.Net.Http
open System.Text
open System.Text.Json
open System.Windows.Forms

let http = new HttpClient(Timeout = TimeSpan.FromMilliseconds 1500.0)

let call (host: string) (port: int) (line: string) =
    task {
        let gap = line.IndexOf ' '
        let verb, rest = line.Substring(0, gap), line.Substring(gap + 1)
        let parts = rest.Split('|', 2)
        let url = $"http://{host}:{port}{parts.[0]}"
        try
            let! r =
                if verb = "POST" then
                    http.PostAsync(url, new StringContent((if parts.Length > 1 then parts.[1] else ""), Encoding.UTF8, "application/json"))
                else
                    http.GetAsync url
            let! body = r.Content.ReadAsStringAsync()
            return Some body
        with _ -> return None
    }

let tile (status: JsonElement) (key: string) =
    let step (v: JsonElement option) (k: string) =
        match v with
        | Some e when e.ValueKind = JsonValueKind.Object ->
            match e.TryGetProperty k with
            | true, x -> Some x
            | _ -> None
        | _ -> None
    match key.Split '.' |> Array.fold step (Some status) with
    | Some e -> e.ToString()
    | None -> "--"

[<EntryPoint; STAThread>]
let main args =
    let spec = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "robot.json"))).RootElement
    let text (k: string) = spec.GetProperty(k).GetString()
    let name, stop, port = text "name", text "stop", spec.GetProperty("port").GetInt32()
    let colour (k: string) = ColorTranslator.FromHtml(text k)
    let keys = dict [ for k in spec.GetProperty("keys").EnumerateObject() -> Char.ToUpperInvariant k.Name.[0], k.Value.GetString() ]

    Application.EnableVisualStyles()
    let form = new Form(Text = name + " controller", ClientSize = Size(620, 400), BackColor = colour "background", ForeColor = colour "text", KeyPreview = true)
    let flow = new FlowLayoutPanel(Dock = DockStyle.Fill, Padding = Padding 14)
    form.Controls.Add flow
    let title = new Label(Text = name, ForeColor = colour "accent", Font = new Font("Consolas", 22f, FontStyle.Bold), AutoSize = true)
    flow.Controls.Add title
    flow.SetFlowBreak(title, true)
    let address = new TextBox(Text = (if args.Length > 0 then args.[0] else text "host"), Width = 200)
    flow.Controls.Add address
    let send (line: string) = call address.Text port line |> ignore
    let button (label: string) (act: unit -> unit) =
        let b = new Button(Text = label, AutoSize = true, FlatStyle = FlatStyle.Flat, TabStop = false)
        b.FlatAppearance.BorderColor <- colour "accent"
        b.Click.Add(fun _ -> act (); form.ActiveControl <- null)
        flow.Controls.Add b
        b
    let connect = button "CONNECT" (fun () -> for c in spec.GetProperty("connect").EnumerateArray() do send (c.GetString()))
    flow.SetFlowBreak(connect, true)
    let state = new Label(Text = "no answer", AutoSize = true)
    flow.Controls.Add state
    flow.SetFlowBreak(state, true)
    for b in spec.GetProperty("buttons").EnumerateArray() do
        let line = b.[1].GetString()
        button (b.[0].GetString()) (fun () -> send line) |> ignore
    flow.SetFlowBreak(button "STOP" (fun () -> send stop), true)
    let tiles =
        [ for t in spec.GetProperty("tiles").EnumerateArray() do
              let label = new Label(AutoSize = true, Padding = Padding 8, BorderStyle = BorderStyle.FixedSingle, Text = t.[0].GetString() + "\n--")
              flow.Controls.Add label
              yield label, t.[0].GetString(), t.[1].GetString(), t.[2].GetString() ]

    let held = HashSet<char>()
    let mutable driving: string option = None
    form.KeyDown.Add(fun e ->
        if not address.Focused then
            if e.KeyCode = Keys.Space then
                held.Clear()
                send stop
                e.Handled <- true
            elif keys.ContainsKey(char e.KeyValue) then
                held.Add(char e.KeyValue) |> ignore)
    form.KeyUp.Add(fun e -> held.Remove(char e.KeyValue) |> ignore)
    form.Deactivate.Add(fun _ -> held.Clear())

    let repeat = new Timer(Interval = 200)
    repeat.Tick.Add(fun _ ->
        let want = if held.Count > 0 then Some keys.[Seq.last held] else None
        match want, driving with
        | Some line, _ -> send line
        | None, Some _ -> send stop
        | None, None -> ()
        driving <- want)
    repeat.Start()
    let poll = new Timer(Interval = 500)
    poll.Tick.Add(fun _ ->
        task {
            let! body = call address.Text port ("GET " + text "status")
            match body with
            | None -> state.Text <- "no answer"
            | Some b ->
                state.Text <- "connected"
                try
                    let d = JsonDocument.Parse(b).RootElement
                    for (label, name, key, suffix) in tiles do
                        label.Text <- name + "\n" + tile d key + suffix
                with :? JsonException -> ()
        } |> ignore)
    poll.Start()
    form.Shown.Add(fun _ -> if address.Text.Length > 0 then connect.PerformClick())
    Application.Run form
    0
