import pygame
import os
import config
import leds

# -----------------------------
# Global playlist state
# -----------------------------
playlist = []
current_track = -1
music_enabled = True

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# -----------------------------
# Initialization
# -----------------------------
def init_music():
    """Initialize the pygame mixer and load playlist."""
    pygame.mixer.init()
    load_playlist()
    pygame.mixer.music.set_endevent(pygame.USEREVENT)
    print("🎵 Music system initialized.")

def load_playlist():
    """Load all supported tracks from the configured folder."""
    global playlist
    playlist = [
        os.path.join(config.MUSIC_FOLDER, f)
        for f in os.listdir(config.MUSIC_FOLDER)
        if f.lower().endswith(config.SUPPORTED_FORMATS)
    ]
    playlist.sort()
    print(f"🎶 Playlist loaded: {len(playlist)} tracks.")

# -----------------------------
# Core playback functions
# -----------------------------
def play_track(index):
    """Play a specific track by index without incrementing."""
    global current_track
    if not playlist:
        print("⚠️ No tracks found.")
        return

    current_track = index % len(playlist)
    track = playlist[current_track]
    pygame.mixer.music.load(track)
    pygame.mixer.music.play()
    leds.start_music_wave()
    print(f"▶️ Playing: {track}")

def play_next_track():
    """Play the next track in the playlist if music is enabled."""
    global current_track, music_enabled
    if not playlist:
        print("⚠️ No tracks found.")
        return

    if not music_enabled:
        # Auto-play blocked by stop
        return

    next_index = (current_track + 1) % len(playlist)
    play_track(next_index)

# -----------------------------
# Control functions
# -----------------------------
def start_music():
    """Reset the playlist and start music from the first track."""
    global music_enabled, current_track
    if not playlist:
        print("⚠️ No tracks to play.")
        return

    music_enabled = True      # Enable music and auto-play
    current_track = 0         # Reset playlist to first track
    play_track(current_track) # Force play first track

def stop_music():
    """Stop music playback and LEDs."""
    global music_enabled
    music_enabled = False
    pygame.mixer.music.stop()
    leds.stop_music_wave()
    print("⏹️ Music stopped.")

def skip_music():
    """Skip current track, even if music is stopped."""
    global music_enabled
    if not playlist:
        print("⚠️ No tracks to skip.")
        return

    # Stop current track and LEDs
    pygame.mixer.music.stop()
    leds.stop_music_wave()

    # Enable music for auto-play and play next track
    music_enabled = True
    play_next_track()

# -----------------------------
# Utility
# -----------------------------
def is_music_playing():
    """Return True if music is currently playing."""
    return pygame.mixer.music.get_busy()

def handle_music_event(event):
    """Handle pygame USEREVENT when a track finishes."""
    if event.type == pygame.USEREVENT and music_enabled:
        play_next_track()