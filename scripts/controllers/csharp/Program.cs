// A robot's controller in C# (WinForms). Everything about the robot is in ../robot.json, the same
// file the other languages read. Hold W A S D (Q E too, where it has them) to drive, Space to stop.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows.Forms;

static class Program
{
    static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromMilliseconds(1500) };

    static async Task<string> Call(string host, int port, string line)
    {
        int gap = line.IndexOf(' ');
        string verb = line.Substring(0, gap), rest = line.Substring(gap + 1);
        string[] parts = rest.Split('|', 2);
        string url = "http://" + host + ":" + port + parts[0];
        try
        {
            HttpResponseMessage r = verb == "POST"
                ? await Http.PostAsync(url, new StringContent(parts.Length > 1 ? parts[1] : "", Encoding.UTF8, "application/json"))
                : await Http.GetAsync(url);
            return await r.Content.ReadAsStringAsync();
        }
        catch (Exception) { return null; }
    }

    static string Tile(JsonElement status, string key)
    {
        foreach (string k in key.Split('.'))
        {
            if (status.ValueKind != JsonValueKind.Object || !status.TryGetProperty(k, out status)) return "--";
        }
        return status.ToString();
    }

    [STAThread]
    static void Main(string[] args)
    {
        JsonElement spec = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "robot.json"))).RootElement;
        string name = spec.GetProperty("name").GetString(), stop = spec.GetProperty("stop").GetString();
        int port = spec.GetProperty("port").GetInt32();
        Color back = ColorTranslator.FromHtml(spec.GetProperty("background").GetString());
        Color text = ColorTranslator.FromHtml(spec.GetProperty("text").GetString());
        Color accent = ColorTranslator.FromHtml(spec.GetProperty("accent").GetString());
        var keys = spec.GetProperty("keys").EnumerateObject().ToDictionary(k => k.Name.ToUpperInvariant()[0], k => k.Value.GetString());

        Application.EnableVisualStyles();
        var form = new Form { Text = name + " controller", ClientSize = new Size(620, 400), BackColor = back, ForeColor = text, KeyPreview = true };
        var flow = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(14), FlowDirection = FlowDirection.LeftToRight };
        form.Controls.Add(flow);
        var title = new Label { Text = name, ForeColor = accent, Font = new Font("Consolas", 22, FontStyle.Bold), AutoSize = true };
        flow.Controls.Add(title);
        flow.SetFlowBreak(title, true);
        var address = new TextBox { Text = args.Length > 0 ? args[0] : spec.GetProperty("host").GetString(), Width = 200 };
        flow.Controls.Add(address);

        Button Btn(string label, Action act)
        {
            var b = new Button { Text = label, AutoSize = true, FlatStyle = FlatStyle.Flat, TabStop = false };
            b.FlatAppearance.BorderColor = accent;
            b.Click += (s, e) => { act(); form.ActiveControl = null; };
            flow.Controls.Add(b);
            return b;
        }
        void Send(string line) { _ = Call(address.Text, port, line); }

        Button connect = Btn("CONNECT", () =>
        {
            foreach (JsonElement c in spec.GetProperty("connect").EnumerateArray()) Send(c.GetString());
        });
        flow.SetFlowBreak(connect, true);
        var state = new Label { Text = "no answer", AutoSize = true };
        flow.Controls.Add(state);
        flow.SetFlowBreak(state, true);
        Control lastButton = null;
        foreach (JsonElement b in spec.GetProperty("buttons").EnumerateArray())
        {
            string line = b[1].GetString();
            lastButton = Btn(b[0].GetString(), () => Send(line));
        }
        flow.SetFlowBreak(Btn("STOP", () => Send(stop)), true);

        var tiles = new List<(Label label, string key, string suffix, string title)>();
        foreach (JsonElement t in spec.GetProperty("tiles").EnumerateArray())
        {
            var l = new Label { AutoSize = true, Padding = new Padding(8), BorderStyle = BorderStyle.FixedSingle, Text = t[0].GetString() + "\n--" };
            flow.Controls.Add(l);
            tiles.Add((l, t[1].GetString(), t[2].GetString(), t[0].GetString()));
        }

        var held = new HashSet<char>();
        string driving = null;
        form.KeyDown += (s, e) =>
        {
            if (address.Focused) return;
            if (e.KeyCode == Keys.Space) { held.Clear(); Send(stop); e.Handled = true; }
            else if (keys.ContainsKey((char)e.KeyValue)) held.Add((char)e.KeyValue);
        };
        form.KeyUp += (s, e) => held.Remove((char)e.KeyValue);
        form.Deactivate += (s, e) => held.Clear();

        var repeat = new Timer { Interval = 200 };
        repeat.Tick += (s, e) =>
        {
            string want = held.Count > 0 ? keys[held.Last()] : null;
            if (want != null) Send(want);
            else if (driving != null) Send(stop);
            driving = want;
        };
        repeat.Start();
        var poll = new Timer { Interval = 500 };
        poll.Tick += async (s, e) =>
        {
            string body = await Call(address.Text, port, "GET " + spec.GetProperty("status").GetString());
            state.Text = body == null ? "no answer" : "connected";
            if (body == null) return;
            try
            {
                JsonElement d = JsonDocument.Parse(body).RootElement;
                foreach (var t in tiles) t.label.Text = t.title + "\n" + Tile(d, t.key) + t.suffix;
            }
            catch (JsonException) { }
        };
        poll.Start();
        form.Shown += (s, e) => { if (address.Text.Length > 0) connect.PerformClick(); };
        Application.Run(form);
    }
}
