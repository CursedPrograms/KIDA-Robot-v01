// A robot's controller in Go (Ebitengine). Everything about the robot is in ../robot.json, the same
// file the other languages read. Hold W A S D (Q E too, where it has them) to drive, Space to stop.
package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"image/color"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/hajimehoshi/ebiten/v2"
	"github.com/hajimehoshi/ebiten/v2/ebitenutil"
	"github.com/hajimehoshi/ebiten/v2/inpututil"
	"github.com/hajimehoshi/ebiten/v2/vector"
)

//go:embed robot.json
var specFile []byte

type spec struct {
	Name, Host, Status, Stop, Background string
	Port                                 int
	Connect                              []string
	Keys                                 map[string]string
	Buttons, Tiles                       [][]string
}

var client = http.Client{Timeout: 1500 * time.Millisecond}

func call(host string, port int, line string) []byte {
	verb, rest, _ := strings.Cut(line, " ")
	path, body, _ := strings.Cut(rest, "|")
	url := fmt.Sprintf("http://%s:%d%s", host, port, path)
	var r *http.Response
	var err error
	if verb == "POST" {
		r, err = client.Post(url, "application/json", strings.NewReader(body))
	} else {
		r, err = client.Get(url)
	}
	if err != nil {
		return nil
	}
	defer r.Body.Close()
	data, _ := io.ReadAll(r.Body)
	return data
}

func tile(status map[string]any, key string) string {
	var v any = status
	for _, k := range strings.Split(key, ".") {
		m, ok := v.(map[string]any)
		if !ok {
			return "--"
		}
		if v, ok = m[k]; !ok {
			return "--"
		}
	}
	return fmt.Sprint(v)
}

type game struct {
	s       spec
	host    string
	mu      sync.Mutex
	status  map[string]any
	out     chan string
	held    string
	last    time.Time
	back    color.Color
}

var driveKeys = map[string]ebiten.Key{"w": ebiten.KeyW, "s": ebiten.KeyS, "a": ebiten.KeyA, "d": ebiten.KeyD, "q": ebiten.KeyQ, "e": ebiten.KeyE}

func (g *game) box(i int) (int, int) { return 12 + (i%4)*150, 90 + (i/4)*36 }

func (g *game) Update() error {
	want := ""
	for name, key := range driveKeys {
		if line, ok := g.s.Keys[name]; ok && ebiten.IsKeyPressed(key) {
			want = line
		}
	}
	if want != g.held {
		if want == "" {
			g.out <- g.s.Stop
		}
		g.held, g.last = want, time.Time{}
	}
	if g.held != "" && time.Since(g.last) >= 200*time.Millisecond {
		g.out <- g.held
		g.last = time.Now()
	}
	if inpututil.IsKeyJustPressed(ebiten.KeySpace) {
		g.out <- g.s.Stop
	}
	if inpututil.IsMouseButtonJustPressed(ebiten.MouseButtonLeft) {
		x, y := ebiten.CursorPosition()
		for i, b := range g.s.Buttons {
			bx, by := g.box(i)
			if x >= bx && x < bx+140 && y >= by && y < by+28 {
				g.out <- b[1]
			}
		}
	}
	return nil
}

func (g *game) Draw(screen *ebiten.Image) {
	screen.Fill(g.back)
	g.mu.Lock()
	status := g.status
	g.mu.Unlock()
	state := "no answer"
	if status != nil {
		state = "connected"
	}
	ebitenutil.DebugPrintAt(screen, fmt.Sprintf("%s  %s:%d  %s", g.s.Name, g.host, g.s.Port, state), 12, 12)
	ebitenutil.DebugPrintAt(screen, "Hold W A S D to drive, Space to stop. Click a button.", 12, 40)
	for i, b := range g.s.Buttons {
		x, y := g.box(i)
		vector.StrokeRect(screen, float32(x), float32(y), 140, 28, 1, color.White, false)
		ebitenutil.DebugPrintAt(screen, b[0], x+8, y+6)
	}
	y := 110 + (len(g.s.Buttons)/4+1)*36
	for i, t := range g.s.Tiles {
		ebitenutil.DebugPrintAt(screen, fmt.Sprintf("%s: %s%s", t[0], tile(status, t[1]), t[2]), 12, y+i*20)
	}
}

func (g *game) Layout(_, _ int) (int, int) { return 620, 400 }

func main() {
	var s spec
	if err := json.Unmarshal(specFile, &s); err != nil {
		panic(err)
	}
	g := &game{s: s, host: s.Host, out: make(chan string, 32)}
	if len(os.Args) > 1 {
		g.host = os.Args[1]
	}
	var r, gr, b uint8
	fmt.Sscanf(s.Background, "#%02x%02x%02x", &r, &gr, &b)
	g.back = color.RGBA{r, gr, b, 255}
	for _, c := range s.Connect {
		g.out <- c
	}
	go func() {
		for line := range g.out {
			call(g.host, s.Port, line)
		}
	}()
	go func() {
		for {
			var now map[string]any
			if body := call(g.host, s.Port, "GET "+s.Status); body != nil {
				json.Unmarshal(body, &now)
			}
			g.mu.Lock()
			g.status = now
			g.mu.Unlock()
			time.Sleep(500 * time.Millisecond)
		}
	}()
	ebiten.SetWindowSize(620, 400)
	ebiten.SetWindowTitle(s.Name + " controller")
	if err := ebiten.RunGame(g); err != nil {
		panic(err)
	}
}
