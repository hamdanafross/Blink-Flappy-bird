import cv2
import mediapipe as mp
import numpy as np
import pygame
import random
import sys
import json
import os
import math
import time

# ============================================================
#  CONFIGURATION
# ============================================================
CFG = {
    "screen_w": 480,
    "screen_h": 680,
    "gravity": 0.35,
    "jump_strength": -7.5,
    "fps": 60,
    "ear_threshold": 0.21,   # overwritten after calibration
    "cam_w": 320,
    "cam_h": 240,
    # Difficulty presets  [gravity, jump, pipe_speed, pipe_gap, pipe_interval]
    "difficulty": {
        "Easy":   [0.28, -7.0, 2.8, 185, 230],
        "Medium": [0.35, -7.5, 3.4, 160, 210],
        "Hard":   [0.44, -8.2, 4.2, 130, 185],
    },
    "selected_diff": "Medium",
    "save_file": os.path.join(os.path.dirname(__file__), "blink_bird_save.json"),
}

# ============================================================
#  PALETTE  (Retro arcade – amber / teal / midnight)
# ============================================================
C = {
    "sky_top":    (15,  25,  60),
    "sky_bot":    (30,  80, 130),
    "ground":     (218, 190,  90),
    "ground_alt": (180, 155,  65),
    "grass":      ( 60, 180,  75),
    "pipe":       ( 42, 190,  85),
    "pipe_dark":  ( 20, 130,  55),
    "pipe_shine": (120, 230, 140),
    "bird_body":  (255, 215,   0),
    "bird_hi":    (255, 240, 120),
    "bird_eye":   (255, 255, 255),
    "bird_pupil": ( 10,  10,  10),
    "bird_beak":  (255, 110,  20),
    "bird_wing":  (230, 175,   0),
    "white":      (255, 255, 255),
    "black":      (  0,   0,   0),
    "amber":      (255, 195,   0),
    "red":        (220,  50,  50),
    "ui_bg":      ( 10,  20,  50, 200),
    "ui_border":  (255, 195,   0),
    "cloud":      (200, 220, 255),
    "star":       (255, 255, 200),
    "hud_blink":  ( 80, 255, 120),
    "hud_idle":   (200, 200, 200),
}

# ============================================================
#  SAVE / LOAD
# ============================================================
def load_save():
    try:
        with open(CFG["save_file"], "r") as f:
            return json.load(f)
    except Exception:
        return {"high_scores": {"Easy": 0, "Medium": 0, "Hard": 0}, "total_blinks": 0}

def write_save(data):
    try:
        with open(CFG["save_file"], "w") as f:
            json.dump(data, f)
    except Exception:
        pass

# ============================================================
#  PYGAME + MEDIAPIPE INIT
# ============================================================
pygame.init()
pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
screen = pygame.display.set_mode((CFG["screen_w"], CFG["screen_h"]))
pygame.display.set_caption("Blink Flappy Bird")
clock = pygame.time.Clock()

# Fonts
F_TITLE  = pygame.font.SysFont("Trebuchet MS", 42, bold=True)
F_HEAD   = pygame.font.SysFont("Trebuchet MS", 28, bold=True)
F_MED    = pygame.font.SysFont("Trebuchet MS", 20, bold=True)
F_SMALL  = pygame.font.SysFont("Arial", 15)
F_MICRO  = pygame.font.SysFont("Arial", 12)

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)
LEFT_EYE  = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33,  160, 158, 133, 153, 144]

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CFG["cam_w"])
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CFG["cam_h"])

# ============================================================
#  SOUND GENERATOR  (pure pygame.mixer – no audio files needed)
# ============================================================
def _make_sound(freq, duration_ms, wave="square", volume=0.25):
    sr = 44100
    n  = int(sr * duration_ms / 1000)
    t  = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    if wave == "square":
        s = np.sign(np.sin(2 * np.pi * freq * t))
    elif wave == "sine":
        s = np.sin(2 * np.pi * freq * t)
    else:
        s = 2 * (t * freq % 1) - 1          # sawtooth
    # fade out
    fade = np.linspace(1, 0, n)
    s = (s * fade * volume * 32767).astype(np.int16)
    s = np.column_stack([s, s])   # mono → stereo (L, R)
    snd = pygame.sndarray.make_sound(s)
    return snd

SFX = {
    "jump":  _make_sound(520, 80,  "square", 0.18),
    "score": _make_sound(880, 120, "sine",   0.20),
    "die":   _make_sound(200, 300, "saw",    0.25),
}
MUTED = False

def play(name):
    if not MUTED:
        SFX[name].play()

# ============================================================
#  PARTICLES
# ============================================================
class Particle:
    def __init__(self, x, y, color, vx=None, vy=None):
        self.x  = x
        self.y  = y
        self.vx = vx if vx is not None else random.uniform(-3, 3)
        self.vy = vy if vy is not None else random.uniform(-4, 0)
        self.life = random.randint(15, 30)
        self.max_life = self.life
        self.r = random.randint(2, 5)
        self.color = color

    def update(self):
        self.x   += self.vx
        self.y   += self.vy
        self.vy  += 0.2
        self.life -= 1

    def draw(self, surf):
        alpha = int(255 * self.life / self.max_life)
        col   = (*self.color[:3], alpha)
        s     = pygame.Surface((self.r * 2, self.r * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, col, (self.r, self.r), self.r)
        surf.blit(s, (int(self.x - self.r), int(self.y - self.r)))

particles: list[Particle] = []

def spawn_particles(x, y, color, n=12):
    for _ in range(n):
        particles.append(Particle(x, y, color))

# ============================================================
#  BACKGROUND ELEMENTS
# ============================================================
class Star:
    def __init__(self):
        self.x    = random.randint(0, CFG["screen_w"])
        self.y    = random.randint(0, CFG["screen_h"] // 2)
        self.size = random.choice([1, 1, 1, 2])
        self.twinkle_offset = random.uniform(0, math.pi * 2)

    def draw(self, surf, t):
        brightness = int(160 + 80 * math.sin(t * 2 + self.twinkle_offset))
        col = (brightness, brightness, int(brightness * 0.9))
        pygame.draw.circle(surf, col, (self.x, self.y), self.size)

class Cloud:
    def __init__(self, x=None, speed=None):
        self.x     = x if x is not None else random.randint(0, CFG["screen_w"])
        self.y     = random.randint(30, CFG["screen_h"] // 3)
        self.speed = speed if speed is not None else random.uniform(0.3, 0.8)
        self.w     = random.randint(50, 100)
        self.h     = random.randint(20, 35)
        self.alpha = random.randint(60, 120)

    def update(self):
        self.x -= self.speed
        if self.x < -self.w - 20:
            self.x = CFG["screen_w"] + 20
            self.y = random.randint(30, CFG["screen_h"] // 3)

    def draw(self, surf):
        s = pygame.Surface((self.w + 30, self.h + 20), pygame.SRCALPHA)
        col = (*C["cloud"], self.alpha)
        pygame.draw.ellipse(s, col, (15,  10, self.w - 20, self.h))
        pygame.draw.ellipse(s, col, (0,   18, self.w // 2, self.h - 8))
        pygame.draw.ellipse(s, col, (self.w // 2, 15, self.w // 2 + 10, self.h - 5))
        surf.blit(s, (int(self.x), int(self.y)))

STARS  = [Star()  for _ in range(60)]
CLOUDS = [Cloud(x=random.randint(0, CFG["screen_w"])) for _ in range(5)]

# ============================================================
#  BIRD
# ============================================================
class Bird:
    WING_FRAMES = 4

    def __init__(self):
        self.x        = 90
        self.y        = 280.0
        self.velocity = 0.0
        self.radius   = 16
        self.angle    = 0.0
        self.wing_t   = 0
        self.alive    = True
        # Ghost replay recording
        self.history: list[float] = []

    def jump(self):
        self.velocity = CFG["gravity_v"]   # set per difficulty
        play("jump")
        spawn_particles(self.x - 10, self.y, C["bird_wing"], n=6)

    def update(self):
        self.velocity += CFG["gravity_v2"]
        self.y        += self.velocity
        # Tilt
        target_angle   = max(-30, min(70, self.velocity * 4))
        self.angle    += (target_angle - self.angle) * 0.2
        self.wing_t    = (self.wing_t + 1) % (self.WING_FRAMES * 4)
        self.history.append(self.y)

    def draw(self, surf, ghost=False):
        cx, cy = int(self.x), int(self.y)
        r      = self.radius
        alpha  = 80 if ghost else 255

        if ghost:
            s = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(s, (*C["amber"], alpha), (r * 2, r * 2), r)
            surf.blit(s, (cx - r * 2, cy - r * 2))
            return

        # Rotated drawing
        bird_surf = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
        bx, by    = r * 2, r * 2

        # Wing (flap animation)
        wing_phase = int(self.wing_t // 4) % self.WING_FRAMES
        wing_offsets = [(-4, 4), (-4, 2), (-4, 0), (-4, 2)]
        wx, wy = wing_offsets[wing_phase]
        pygame.draw.ellipse(bird_surf, C["bird_wing"],
                            (bx - r + wx, by + wy, r + 4, r // 2))

        # Body
        pygame.draw.circle(bird_surf, C["bird_body"],  (bx, by), r)
        pygame.draw.circle(bird_surf, C["bird_hi"],    (bx - 4, by - 4), r // 3)

        # Eye
        pygame.draw.circle(bird_surf, C["bird_eye"],   (bx + 6, by - 5), 5)
        pygame.draw.circle(bird_surf, C["bird_pupil"], (bx + 8, by - 5), 2)

        # Beak
        pygame.draw.polygon(bird_surf, C["bird_beak"], [
            (bx + r - 2, by - 2),
            (bx + r + 10, by + 2),
            (bx + r - 2, by + 6),
        ])

        rotated = pygame.transform.rotate(bird_surf, -self.angle)
        rr      = rotated.get_rect(center=(cx, cy))
        surf.blit(rotated, rr)

# ============================================================
#  PIPE
# ============================================================
class Pipe:
    def __init__(self, diff_cfg):
        self.x          = CFG["screen_w"]
        self.gap        = diff_cfg[3]
        self.top_height = random.randint(70, CFG["screen_h"] - self.gap - 160)
        self.width      = 62
        self.speed      = diff_cfg[2]
        self.scored     = False

    def update(self):
        self.x -= self.speed

    def draw(self, surf):
        W = self.width
        th = self.top_height
        bot_y = th + self.gap
        bot_h = CFG["screen_h"] - bot_y - 55

        for (rx, ry, rw, rh) in [(self.x, 0, W, th), (self.x, bot_y, W, bot_h)]:
            # Main body
            pygame.draw.rect(surf, C["pipe"],      (rx, ry, rw, rh))
            # Left highlight
            pygame.draw.rect(surf, C["pipe_shine"],(rx + 4, ry, 6, rh))
            # Right shadow
            pygame.draw.rect(surf, C["pipe_dark"], (rx + W - 8, ry, 8, rh))

        # Caps
        cap_h = 22
        for (rx, ry) in [(self.x - 4, th - cap_h), (self.x - 4, bot_y)]:
            pygame.draw.rect(surf, C["pipe"],      (rx, ry, W + 8, cap_h), border_radius=4)
            pygame.draw.rect(surf, C["pipe_shine"],(rx + 4, ry + 2, 8, cap_h - 4))
            pygame.draw.rect(surf, C["pipe_dark"], (rx + W - 4, ry, 8, cap_h), border_radius=4)

    def collides(self, bird):
        bx, by, br = bird.x, bird.y, bird.radius - 2
        W = self.width
        if not (self.x - br < bx + br < self.x + W + br):
            return False
        if by - br < self.top_height or by + br > self.top_height + self.gap:
            return True
        return False

# ============================================================
#  EAR CALCULATION
# ============================================================
def calculate_ear(landmarks, eye_indices, img_w, img_h):
    pts = [np.array([landmarks[i].x * img_w, landmarks[i].y * img_h])
           for i in eye_indices]
    v1 = np.linalg.norm(pts[1] - pts[5])
    v2 = np.linalg.norm(pts[2] - pts[4])
    h  = np.linalg.norm(pts[0] - pts[3])
    return (v1 + v2) / (2.0 * h) if h > 0 else 0.3

# ============================================================
#  DRAW HELPERS
# ============================================================
SW, SH = CFG["screen_w"], CFG["screen_h"]

def draw_sky(surf, t):
    # Vertical gradient
    for y in range(SH):
        r = int(C["sky_top"][0] + (C["sky_bot"][0] - C["sky_top"][0]) * y / SH)
        g = int(C["sky_top"][1] + (C["sky_bot"][1] - C["sky_top"][1]) * y / SH)
        b = int(C["sky_top"][2] + (C["sky_bot"][2] - C["sky_top"][2]) * y / SH)
        pygame.draw.line(surf, (r, g, b), (0, y), (SW, y))
    for star in STARS:
        star.draw(surf, t)
    for cloud in CLOUDS:
        cloud.draw(surf)

def draw_ground(surf, offset):
    ground_y = SH - 55
    pygame.draw.rect(surf, C["ground"],   (0, ground_y, SW, 55))
    pygame.draw.rect(surf, C["grass"],    (0, ground_y, SW, 10))
    for x in range(int(offset) - 25, SW + 25, 25):
        pygame.draw.line(surf, C["ground_alt"],
                         (x, ground_y + 12), (x + 12, ground_y + 55), 2)

def draw_text_center(surf, text, font, color, y, shadow=True):
    if shadow:
        s = font.render(text, True, (0, 0, 0))
        surf.blit(s, (SW // 2 - s.get_width() // 2 + 2, y + 2))
    t = font.render(text, True, color)
    surf.blit(t, (SW // 2 - t.get_width() // 2, y))

def draw_panel(surf, x, y, w, h, alpha=200, radius=14):
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(s, (*C["sky_top"], alpha), (0, 0, w, h), border_radius=radius)
    pygame.draw.rect(s, (*C["amber"], 200),     (0, 0, w, h), width=2, border_radius=radius)
    surf.blit(s, (x, y))

def draw_button(surf, text, font, x, y, w, h, hover=False):
    col  = (255, 220, 50) if hover else (200, 160, 20)
    bgc  = (60, 50, 10)   if hover else (30, 25, 5)
    s    = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(s, (*bgc, 230),  (0, 0, w, h), border_radius=10)
    pygame.draw.rect(s, (*col, 255),  (0, 0, w, h), width=2, border_radius=10)
    surf.blit(s, (x, y))
    t = font.render(text, True, col)
    surf.blit(t, (x + w // 2 - t.get_width() // 2, y + h // 2 - t.get_height() // 2))

def medal_color(score, diff):
    thresholds = {"Easy": (5, 15), "Medium": (4, 12), "Hard": (3, 8)}
    lo, hi = thresholds.get(diff, (5, 15))
    if score >= hi: return (255, 215, 0), "GOLD"
    if score >= lo: return (192, 192, 192), "SILVER"
    return (205, 127, 50), "BRONZE"

# ============================================================
#  CALIBRATION SCREEN
# ============================================================
def run_calibration():
    """Collect 3 seconds of open-eye EAR, then prompt user to blink 3x."""
    phase       = "open"   # open → blink → done
    open_ears   = []
    blink_ears  = []
    blink_count = 0
    timer_start = time.time()
    threshold   = 0.21
    msg         = ""
    last_below  = False

    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        frame    = cv2.flip(frame, 1)
        h, w, _  = frame.shape
        rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results  = face_mesh.process(rgb)

        avg_ear  = 0.3
        if results.multi_face_landmarks:
            lm      = results.multi_face_landmarks[0].landmark
            l_ear   = calculate_ear(lm, LEFT_EYE, w, h)
            r_ear   = calculate_ear(lm, RIGHT_EYE, w, h)
            avg_ear = (l_ear + r_ear) / 2.0

        elapsed = time.time() - timer_start

        if phase == "open":
            if results.multi_face_landmarks:
                open_ears.append(avg_ear)
            if elapsed > 3.0:
                phase       = "blink"
                timer_start = time.time()
        elif phase == "blink":
            if results.multi_face_landmarks:
                blink_ears.append(avg_ear)
                if avg_ear < 0.19:
                    if not last_below:
                        blink_count += 1
                        last_below   = True
                else:
                    last_below = False
            if blink_count >= 3:
                phase = "done"
        elif phase == "done":
            if open_ears and blink_ears:
                open_mean  = np.mean(open_ears)
                blink_min  = np.min(blink_ears)
                threshold  = round((open_mean + blink_min) / 2.0, 3)
                threshold  = max(0.15, min(threshold, 0.26))
            break

        # --- RENDER ---
        screen.fill(C["sky_top"])
        draw_text_center(screen, "EYE CALIBRATION", F_HEAD, C["amber"], 60)
        draw_panel(screen, 40, 110, SW - 80, 380)

        if phase == "open":
            bar = min(elapsed / 3.0, 1.0)
            draw_text_center(screen, "Keep your eyes OPEN", F_MED, C["white"], 140)
            draw_text_center(screen, "Look straight at camera", F_SMALL, C["hud_idle"], 175)
            pygame.draw.rect(screen, C["pipe_dark"],  (60, 220, SW - 120, 18), border_radius=9)
            pygame.draw.rect(screen, C["pipe"],       (60, 220, int((SW - 120) * bar), 18), border_radius=9)
            draw_text_center(screen, f"{3 - int(elapsed)}s", F_MED, C["white"], 250)
        elif phase == "blink":
            draw_text_center(screen, "Now BLINK 3 times!", F_MED, C["amber"], 140)
            draw_text_center(screen, "Deliberate, full blinks", F_SMALL, C["hud_idle"], 175)
            for i in range(3):
                col = C["hud_blink"] if i < blink_count else C["hud_idle"]
                pygame.draw.circle(screen, col, (SW // 2 - 40 + i * 40, 240), 14)

        # Live EAR meter
        ear_norm = max(0, min(avg_ear / 0.35, 1.0))
        pygame.draw.rect(screen, (40, 40, 80), (60, 310, SW - 120, 14), border_radius=7)
        pygame.draw.rect(screen, C["hud_blink"], (60, 310, int((SW - 120) * ear_norm), 14), border_radius=7)
        t = F_MICRO.render(f"EAR: {avg_ear:.3f}", True, C["hud_idle"])
        screen.blit(t, (60, 330))

        # Webcam preview
        resized = cv2.resize(rgb, (120, 90))
        cam_s   = pygame.surfarray.make_surface(np.rot90(resized))
        screen.blit(cam_s, (SW // 2 - 60, 370))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                cap.release()
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return 0.21   # skip calibration

        pygame.display.flip()
        clock.tick(30)

    # Brief "done" screen
    for _ in range(60):
        screen.fill(C["sky_top"])
        draw_panel(screen, 60, 220, SW - 120, 160)
        draw_text_center(screen, "Calibration Complete!", F_HEAD, C["hud_blink"], 240)
        draw_text_center(screen, f"Your threshold: {threshold}", F_MED, C["white"], 285)
        draw_text_center(screen, "Tip: blink fully for best results", F_SMALL, C["hud_idle"], 320)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                cap.release()
                pygame.quit()
                sys.exit()
        pygame.display.flip()
        clock.tick(30)

    return threshold

# ============================================================
#  MAIN GAME
# ============================================================
def apply_difficulty():
    d = CFG["difficulty"][CFG["selected_diff"]]
    CFG["gravity_v2"] = d[0]
    CFG["gravity_v"]  = d[1]
    CFG["pipe_speed"] = d[2]
    CFG["pipe_gap"]   = d[3]
    CFG["pipe_int"]   = d[4]

def main():
    global MUTED

    save_data = load_save()
    apply_difficulty()

    # ---- State ----
    game_state    = "HOME"
    bird          = Bird()
    pipes         = []
    score         = 0
    high_scores   = save_data.get("high_scores", {"Easy": 0, "Medium": 0, "Hard": 0})
    total_blinks  = save_data.get("total_blinks", 0)
    ground_offset = 0.0
    t             = 0.0
    is_blinking   = False
    paused        = False
    ghost_history : list[float] = []   # best run y-positions

    # Home screen diff button state
    diff_keys = list(CFG["difficulty"].keys())

    # Countdown
    countdown     = 0
    countdown_t   = 0.0

    # ---- Pre-game calibration ----
    CFG["ear_threshold"] = run_calibration()

    def reset_game():
        nonlocal bird, pipes, score, ground_offset
        apply_difficulty()
        bird          = Bird()
        pipes         = [Pipe(CFG["difficulty"][CFG["selected_diff"]])]
        score         = 0
        ground_offset = 0.0

    # Initial reset
    reset_game()
    pipes = []   # don't show pipes on HOME

    cam_surface = None

    while True:
        dt          = clock.tick(CFG["fps"]) / 1000.0
        t          += dt
        mx, my      = pygame.mouse.get_pos()
        blink_detected = False

        # ---- Events ----
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                save_data["high_scores"]   = high_scores
                save_data["total_blinks"]  = total_blinks
                write_save(save_data)
                cap.release()
                pygame.quit()
                sys.exit()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_m:
                    MUTED = not MUTED
                if event.key == pygame.K_p and game_state == "PLAYING":
                    paused = not paused
                if event.key == pygame.K_SPACE:
                    if game_state == "HOME":
                        game_state = "COUNTDOWN"
                        countdown  = 3
                        countdown_t = time.time()
                        reset_game()
                    elif game_state == "GAMEOVER":
                        game_state = "COUNTDOWN"
                        countdown  = 3
                        countdown_t = time.time()
                        reset_game()
                    elif game_state == "PLAYING" and not paused:
                        bird.jump()
                if event.key == pygame.K_ESCAPE:
                    if game_state in ["PLAYING", "PAUSED"]:
                        game_state = "HOME"
                        reset_game()
                        pipes = []

            if event.type == pygame.MOUSEBUTTONDOWN:
                # Difficulty buttons (HOME screen)
                if game_state == "HOME":
                    for i, dk in enumerate(diff_keys):
                        bx = 50 + i * 130
                        by = SH - 195
                        if bx <= mx <= bx + 115 and by <= my <= by + 38:
                            CFG["selected_diff"] = dk
                            apply_difficulty()
                    # PLAY button
                    if SW // 2 - 80 <= mx <= SW // 2 + 80 and SH - 130 <= my <= SH - 90:
                        game_state  = "COUNTDOWN"
                        countdown   = 3
                        countdown_t = time.time()
                        reset_game()
                    # Mute button
                    if SW - 45 <= mx <= SW - 10 and 10 <= my <= 45:
                        MUTED = not MUTED
                    # Calibrate button
                    if 10 <= mx <= 130 and SH - 45 <= my <= SH - 15:
                        CFG["ear_threshold"] = run_calibration()

                if game_state == "GAMEOVER":
                    # Play again
                    if SW // 2 - 80 <= mx <= SW // 2 + 80 and SH // 2 + 80 <= my <= SH // 2 + 120:
                        game_state  = "COUNTDOWN"
                        countdown   = 3
                        countdown_t = time.time()
                        reset_game()
                    # Home button
                    if SW // 2 - 80 <= mx <= SW // 2 + 80 and SH // 2 + 130 <= my <= SH // 2 + 165:
                        game_state = "HOME"
                        reset_game()
                        pipes = []

        # ---- Webcam ----
        ret, frame = cap.read()
        if ret:
            frame    = cv2.flip(frame, 1)
            fh, fw, _ = frame.shape
            rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results  = face_mesh.process(rgb)

            if results.multi_face_landmarks:
                lm      = results.multi_face_landmarks[0].landmark
                l_ear   = calculate_ear(lm, LEFT_EYE, fw, fh)
                r_ear   = calculate_ear(lm, RIGHT_EYE, fw, fh)
                avg_ear = (l_ear + r_ear) / 2.0

                if avg_ear < CFG["ear_threshold"]:
                    if not is_blinking:
                        blink_detected = True
                        is_blinking    = True
                        total_blinks  += 1
                else:
                    is_blinking = False

            resized  = cv2.resize(rgb, (120, 90))
            cam_surface = pygame.surfarray.make_surface(np.rot90(resized))

        # ---- Countdown ----
        if game_state == "COUNTDOWN":
            remaining = 3 - int(time.time() - countdown_t)
            if remaining <= 0:
                game_state = "PLAYING"
                pipes      = [Pipe(CFG["difficulty"][CFG["selected_diff"]])]
            else:
                countdown = remaining

        # ---- Game Logic ----
        if game_state == "PLAYING" and not paused:
            if blink_detected:
                bird.jump()

            bird.update()

            # Ground ceiling
            if bird.y + bird.radius >= SH - 55:
                bird.y     = SH - 55 - bird.radius
                game_state = "GAMEOVER"
                play("die")
                spawn_particles(bird.x, bird.y, C["bird_body"], n=20)
                if score > high_scores.get(CFG["selected_diff"], 0):
                    high_scores[CFG["selected_diff"]] = score
                    ghost_history = bird.history[:]
                    write_save({"high_scores": high_scores, "total_blinks": total_blinks})

            if bird.y - bird.radius <= 0:
                game_state = "GAMEOVER"
                play("die")
                spawn_particles(bird.x, bird.y, C["bird_body"], n=20)

            # Pipes
            diff = CFG["difficulty"][CFG["selected_diff"]]
            if not pipes or pipes[-1].x < SW - diff[4]:
                pipes.append(Pipe(diff))

            for pipe in pipes[:]:
                pipe.update()
                if pipe.collides(bird):
                    game_state = "GAMEOVER"
                    play("die")
                    spawn_particles(bird.x, bird.y, C["bird_body"], n=20)
                    if score > high_scores.get(CFG["selected_diff"], 0):
                        high_scores[CFG["selected_diff"]] = score
                        ghost_history = bird.history[:]
                        write_save({"high_scores": high_scores, "total_blinks": total_blinks})
                if not pipe.scored and pipe.x + pipe.width < bird.x:
                    pipe.scored = True
                    score      += 1
                    play("score")
                    spawn_particles(bird.x, bird.y - 30, C["amber"], n=8)

            pipes = [p for p in pipes if p.x > -p.width - 10]
            ground_offset = (ground_offset - diff[2]) % 25

        # Update clouds
        for cloud in CLOUDS:
            cloud.update()

        # Update particles
        for p in particles[:]:
            p.update()
            if p.life <= 0:
                particles.remove(p)

        # ============================================================
        #  RENDER
        # ============================================================
        draw_sky(screen, t)

        # Ghost
        if game_state == "PLAYING" and ghost_history:
            frame_idx = min(len(bird.history), len(ghost_history)) - 1
            if 0 <= frame_idx < len(ghost_history):
                ghost = Bird()
                ghost.x = bird.x
                ghost.y = ghost_history[frame_idx]
                ghost.draw(screen, ghost=True)

        # Pipes
        for pipe in pipes:
            pipe.draw(screen)

        # Ground
        draw_ground(screen, ground_offset)

        # Bird
        bird.draw(screen)

        # Particles
        for p in particles:
            p.draw(screen)

        # ---- HUD: webcam overlay ----
        if cam_surface:
            screen.blit(cam_surface, (10, 10))
            box_col = C["hud_blink"] if is_blinking else C["white"]
            pygame.draw.rect(screen, box_col, (10, 10, 120, 90), 2)
            lbl = F_MICRO.render("BLINK!" if is_blinking else "tracking", True, box_col)
            screen.blit(lbl, (14, 74))

        # Mute button
        mc  = C["amber"] if not MUTED else C["hud_idle"]
        mt  = F_MICRO.render("🔊" if not MUTED else "🔇", True, mc)
        screen.blit(mt, (SW - 35, 14))

        # ============================================================
        #  STATE OVERLAYS
        # ============================================================
        if game_state == "HOME":
            ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
            ov.fill((5, 10, 35, 160))
            screen.blit(ov, (0, 0))

            # Title
            draw_text_center(screen, "BLINK BIRD", F_TITLE, C["amber"], 65)
            draw_text_center(screen, "Control with your eyes", F_SMALL, C["hud_idle"], 118)

            # Stats panel
            draw_panel(screen, 30, 150, SW - 60, 110)
            hs_str = " | ".join(f"{k}: {high_scores.get(k,0)}" for k in diff_keys)
            draw_text_center(screen, "HIGH SCORES", F_SMALL, C["amber"], 165)
            draw_text_center(screen, hs_str, F_SMALL, C["white"], 190)
            draw_text_center(screen, f"Total blinks: {total_blinks}", F_MICRO, C["hud_idle"], 220)

            # How to play
            draw_panel(screen, 30, 275, SW - 60, 120)
            draw_text_center(screen, "HOW TO PLAY", F_SMALL, C["amber"], 290)
            for i, line in enumerate([
                "• Keep face visible to webcam",
                "• BLINK fully to make the bird jump",
                "• Dodge pipes — survive as long as you can",
            ]):
                t_surf = F_MICRO.render(line, True, C["white"])
                screen.blit(t_surf, (50, 315 + i * 22))

            # Difficulty buttons
            draw_text_center(screen, "DIFFICULTY", F_SMALL, C["amber"], SH - 210)
            for i, dk in enumerate(diff_keys):
                bx   = 50 + i * 130
                by   = SH - 195
                hov  = bx <= mx <= bx + 115 and by <= my <= by + 38
                sel  = dk == CFG["selected_diff"]
                bcol = C["amber"] if sel else (C["white"] if hov else C["hud_idle"])
                draw_button(screen, dk, F_SMALL, bx, by, 115, 38, hover=sel or hov)

            # Play button
            draw_button(screen, "▶  PLAY  (SPACE)", F_MED, SW // 2 - 80, SH - 130, 160, 42, hover=True)

            # Calibrate button
            draw_button(screen, "Re-calibrate", F_MICRO, 10, SH - 45, 120, 30)

        elif game_state == "COUNTDOWN":
            draw_sky(screen, t)
            for pipe in pipes:
                pipe.draw(screen)
            draw_ground(screen, ground_offset)
            bird.draw(screen)
            ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 100))
            screen.blit(ov, (0, 0))
            num = F_TITLE.render(str(countdown), True, C["amber"])
            screen.blit(num, (SW // 2 - num.get_width() // 2, SH // 2 - 50))
            draw_text_center(screen, "Get ready...", F_MED, C["white"], SH // 2 + 20)

        elif game_state == "PLAYING":
            # Score
            sc_surf = F_TITLE.render(str(score), True, C["white"])
            shadow  = F_TITLE.render(str(score), True, (0, 0, 0))
            screen.blit(shadow, (SW // 2 - sc_surf.get_width() // 2 + 2, 12))
            screen.blit(sc_surf, (SW // 2 - sc_surf.get_width() // 2, 10))

            # Diff label
            dl = F_MICRO.render(CFG["selected_diff"], True, C["hud_idle"])
            screen.blit(dl, (SW - dl.get_width() - 8, 50))

            if paused:
                ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
                ov.fill((0, 0, 0, 160))
                screen.blit(ov, (0, 0))
                draw_panel(screen, SW // 2 - 110, SH // 2 - 80, 220, 160)
                draw_text_center(screen, "PAUSED", F_HEAD, C["amber"], SH // 2 - 60)
                draw_text_center(screen, "P  to resume", F_SMALL, C["white"], SH // 2 - 10)
                draw_text_center(screen, "ESC  to quit to menu", F_SMALL, C["white"], SH // 2 + 20)
                draw_text_center(screen, f"M  {'unmute' if MUTED else 'mute'}", F_SMALL, C["white"], SH // 2 + 50)

        elif game_state == "GAMEOVER":
            # Dim
            ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 140))
            screen.blit(ov, (0, 0))

            panel_y = SH // 2 - 160
            draw_panel(screen, 35, panel_y, SW - 70, 330)

            draw_text_center(screen, "GAME OVER", F_HEAD, C["red"], panel_y + 18)

            # Medal
            is_hs = score >= high_scores.get(CFG["selected_diff"], 0)
            mc2, mname = medal_color(score, CFG["selected_diff"])
            pygame.draw.circle(screen, mc2, (SW // 2, panel_y + 80), 28)
            ml = F_MED.render(mname[0], True, C["black"])
            screen.blit(ml, (SW // 2 - ml.get_width() // 2, panel_y + 68))
            mn = F_MICRO.render(mname, True, mc2)
            screen.blit(mn, (SW // 2 - mn.get_width() // 2, panel_y + 115))

            draw_text_center(screen, f"Score   {score}", F_MED, C["white"], panel_y + 145)
            best = high_scores.get(CFG["selected_diff"], 0)
            draw_text_center(screen, f"Best     {best}", F_MED, C["amber"], panel_y + 178)
            if is_hs and score > 0:
                draw_text_center(screen, "★ NEW HIGH SCORE ★", F_SMALL, C["hud_blink"], panel_y + 212)

            draw_button(screen, "▶  Play Again  (SPACE)", F_SMALL,
                        SW // 2 - 80, SH // 2 + 80, 160, 40, hover=True)
            draw_button(screen, "⌂  Main Menu", F_SMALL,
                        SW // 2 - 80, SH // 2 + 130, 160, 36)

        pygame.display.flip()

    cap.release()
    pygame.quit()


if __name__ == "__main__":
    main()
