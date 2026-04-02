import os
import glob
import time
import random
import pygame
from pygame import mixer

class MusicPlayer:
    def __init__(self, folder, shuffle=False):
        pygame.mixer.init()
        self.playlist = glob.glob(os.path.join(folder, "*.mp3"))
        if not self.playlist:
            print("⚠️ No music found.")
            return

        self.shuffle = shuffle
        if self.shuffle:
            random.shuffle(self.playlist)

        self.index = 0
        self.playing = False
        self.paused = False
        self.manual_stop = False  # ✅ Add this

        self.SONG_END = pygame.USEREVENT + 1
        pygame.mixer.music.set_endevent(self.SONG_END)

    def play_next(self):
        if not self.playlist:
            return
        self.manual_stop = False  # ✅ Reset on normal playback
        song = self.playlist[self.index]
        pygame.mixer.music.load(song)
        pygame.mixer.music.play()
        print(f"🎶 Now playing: {os.path.basename(song)}")
        self.index = (self.index + 1) % len(self.playlist)
        self.playing = True
        self.paused = False

    def stop(self):
        pygame.mixer.music.stop()
        self.manual_stop = True  # ✅ Flag so we skip next SONG_END
        self.playing = False
        self.paused = False

    def handle_event(self, event):
        if event.type == self.SONG_END:
            if self.manual_stop:
                print("⏹️ Ignored SONG_END because of manual stop.")
                self.manual_stop = False  # reset the flag
            else:
                print("🎵 SONG_END triggered: playing next.")
                self.play_next()

