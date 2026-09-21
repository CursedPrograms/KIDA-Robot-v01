// Command fleet-heartbeat announces this KIDA instance to the RIFT/NORA
// fleet registry — a standalone Go rewrite of scripts/fleet_register.py's
// behavior, with no dependency on the Python robot process. Runs as its
// own process (systemd unit, or launched by run.sh) instead of a thread
// inside server.py.
//
// NORA (https://github.com/CursedPrograms/NORA-Robot-v00) hosts the fleet
// registry (/register, /robots on port 5000) that RIFT
// (https://github.com/CursedPrograms/RIFT) reads from. This mirrors the
// Python client's exact request shape (form-encoded name/type/capabilities
// POSTed every interval) so KIDA shows up as a full fleet member.
//
// Safe if NORA is unreachable: retries forever on the same interval,
// never exits on a failed request.
package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"time"
)

func main() {
	host := flag.String("host", "192.168.4.1", "NORA fleet-registry host")
	port := flag.Int("port", 5000, "NORA fleet-registry port")
	name := flag.String("name", "KIDA01", "this robot's fleet name")
	capsFlag := flag.String("capabilities",
		"camera,object_detection,voice_assistant,autonomous_drive,sensors",
		"comma-separated capability list")
	// Must stay under NORA's FLEET_TTL_MS (20s) or the registry entry
	// flaps — same constraint as fleet_register.py's HEARTBEAT_SECS.
	interval := flag.Duration("interval", 10*time.Second, "heartbeat interval")
	timeout := flag.Duration("timeout", 2*time.Second, "per-request timeout")
	flag.Parse()

	client := &http.Client{Timeout: *timeout}
	endpoint := fmt.Sprintf("http://%s:%d/register", *host, *port)
	form := url.Values{
		"name":         {*name},
		"type":         {"robot"},
		"capabilities": {*capsFlag},
	}

	log.Printf("fleet-heartbeat: announcing %q to %s every %s", *name, endpoint, *interval)

	// Only log on state transitions (up->down, down->up), not every tick —
	// at a 10s interval that would otherwise flood the journal.
	up := true
	for {
		if err := announce(client, endpoint, form); err != nil {
			if up {
				log.Printf("fleet-heartbeat: lost contact with %s: %v", endpoint, err)
				up = false
			}
		} else if !up {
			log.Printf("fleet-heartbeat: reconnected to %s", endpoint)
			up = true
		}
		time.Sleep(*interval)
	}
}

func announce(client *http.Client, endpoint string, form url.Values) error {
	resp, err := client.PostForm(endpoint, form)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("unexpected status %s", resp.Status)
	}
	return nil
}
