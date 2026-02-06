#!/usr/bin/env python3
import math
import time
import random
import sys
import os
from collections import deque

# Terminal setup
WIDTH = 80
HEIGHT = 30
FPS = 60

# ANSI escape codes
CLEAR = '\033[2J'
HOME = '\033[H'
HIDE_CURSOR = '\033[?25l'
SHOW_CURSOR = '\033[?25h'
RESET = '\033[0m'

# Color functions
def rgb_to_ansi(r, g, b):
    """Convert RGB (0-255) to ANSI 24-bit color escape code"""
    return f'\033[38;2;{int(r)};{int(g)};{int(b)}m'

def hsv_to_rgb(h, s, v):
    """Convert HSV to RGB"""
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    
    return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)

# Particle class for effects
class Particle:
    def __init__(self, x, y, vx, vy, life, char='●', color=None):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.char = char
        self.color = color or (255, 255, 255)
        self.trail = deque(maxlen=8)
    
    def update(self, dt):
        self.trail.append((self.x, self.y))
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 50 * dt  # gravity
        self.life -= dt
        return self.life > 0

# Frame buffer to handle layered rendering
class FrameBuffer:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.clear()
    
    def clear(self):
        self.chars = [[' ' for _ in range(self.width)] for _ in range(self.height)]
        self.colors = [[(0, 0, 0) for _ in range(self.width)] for _ in range(self.height)]
    
    def set_pixel(self, x, y, char, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.chars[y][x] = char
            self.colors[y][x] = color
    
    def render(self):
        output = []
        for y in range(self.height):
            row = []
            last_color = None
            for x in range(self.width):
                color = self.colors[y][x]
                char = self.chars[y][x]
                
                # Only output color code if it changed
                if color != last_color:
                    row.append(rgb_to_ansi(*color))
                    last_color = color
                
                row.append(char)
            
            output.append(''.join(row) + RESET)
        
        return '\n'.join(output)

# Animation functions
def plasma_wave(x, y, t):
    """Generate plasma effect value"""
    v1 = math.sin(x * 0.1 + t)
    v2 = math.sin((x * 0.1 + y * 0.1) + t * 1.5)
    v3 = math.sin(math.sqrt((x - WIDTH/2)**2 + (y - HEIGHT/2)**2) * 0.1 - t * 2)
    v4 = math.sin(math.sqrt(x**2 + y**2) * 0.05 + t * 0.5)
    return (v1 + v2 + v3 + v4) / 4

def render_frame(t, particles, fire_buffer, rain_columns):
    """Render a single frame"""
    buffer = FrameBuffer(WIDTH, HEIGHT)
    
    # Layer 1: Plasma background
    for y in range(HEIGHT):
        for x in range(WIDTH):
            plasma = plasma_wave(x, y, t)
            hue = (plasma + 1) * 180 + t * 30
            r, g, b = hsv_to_rgb(hue % 360, 0.8, 0.6)
            buffer.set_pixel(x, y, '█', (r, g, b))
    
    # Layer 2: Fire effect
    # Update fire buffer
    for x in range(WIDTH):
        if HEIGHT - 1 not in fire_buffer:
            fire_buffer[HEIGHT - 1] = {}
        fire_buffer[HEIGHT - 1][x] = random.randint(0, 255) if random.random() > 0.4 else 0
    
    # Propagate fire upward
    for y in range(HEIGHT - 2, -1, -1):
        if y not in fire_buffer:
            fire_buffer[y] = {}
        for x in range(WIDTH):
            total = 0
            count = 0
            for dx in [-1, 0, 1]:
                for dy in [0, 1]:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < WIDTH and ny < HEIGHT and ny in fire_buffer and nx in fire_buffer[ny]:
                        total += fire_buffer[ny][nx]
                        count += 1
            
            if count > 0:
                fire_buffer[y][x] = max(0, (total / count) - random.randint(1, 20))
                
                # Apply fire color
                if fire_buffer[y][x] > 50:
                    intensity = fire_buffer[y][x] / 255
                    base_r, base_g, base_b = buffer.colors[y][x]
                    
                    # Fire colors
                    if intensity > 0.8:
                        r, g, b = 255, 255, 200  # White hot
                    elif intensity > 0.6:
                        r, g, b = 255, 200, 50   # Yellow
                    elif intensity > 0.3:
                        r, g, b = 255, 100, 0    # Orange
                    else:
                        r, g, b = 200, 0, 0      # Red
                    
                    # Blend with background
                    blend = intensity * 0.8
                    new_r = int(base_r * (1 - blend) + r * blend)
                    new_g = int(base_g * (1 - blend) + g * blend)
                    new_b = int(base_b * (1 - blend) + b * blend)
                    
                    buffer.set_pixel(x, y, '█', (new_r, new_g, new_b))
    
    # Layer 3: Matrix rain
    for col_id in range(0, WIDTH, 3):  # Every 3rd column for spacing
        if col_id not in rain_columns:
            rain_columns[col_id] = {
                'y': random.randint(-HEIGHT, 0),
                'speed': random.uniform(10, 30),
                'length': random.randint(5, 15)
            }
        
        rain = rain_columns[col_id]
        rain['y'] += rain['speed'] * (1/FPS)
        
        if rain['y'] > HEIGHT + rain['length']:
            rain['y'] = random.randint(-HEIGHT, -5)
            rain['speed'] = random.uniform(10, 30)
            rain['length'] = random.randint(5, 15)
        
        # Draw the rain
        for i in range(rain['length']):
            y = int(rain['y'] - i)
            if 0 <= y < HEIGHT:
                if i == 0:
                    # Head of the rain - bright white
                    buffer.set_pixel(col_id, y, chr(random.randint(0x30A0, 0x30FF)), (200, 255, 200))
                else:
                    # Fading tail
                    brightness = max(0, 255 - (i * 30))
                    buffer.set_pixel(col_id, y, chr(random.randint(0x30A0, 0x30FF)), (0, brightness, 0))
    
    # Layer 4: Particles
    for particle in particles:
        # Draw trail
        for i, (tx, ty) in enumerate(particle.trail):
            if i < len(particle.trail) - 1:  # Don't draw current position in trail
                fade = i / len(particle.trail)
                r, g, b = [int(c * fade * 0.5) for c in particle.color]
                buffer.set_pixel(int(tx), int(ty), '·', (r, g, b))
        
        # Draw particle
        life_ratio = particle.life / particle.max_life
        r, g, b = [int(c * life_ratio) for c in particle.color]
        buffer.set_pixel(int(particle.x), int(particle.y), particle.char, (r, g, b))
    
    return buffer.render()

def main():
    # Hide cursor and clear screen
    print(HIDE_CURSOR + CLEAR)
    
    # Initialize
    particles = []
    fire_buffer = {}
    rain_columns = {}
    
    # Timing
    last_time = time.time()
    frame_time = 1.0 / FPS
    t = 0
    frame_count = 0
    fps_time = time.time()
    current_fps = 0
    
    try:
        while True:
            current_time = time.time()
            dt = current_time - last_time
            
            if dt >= frame_time:
                # Update particles
                particles = [p for p in particles if p.update(dt)]
                
                # Spawn new particles
                # Fountain effect
                if random.random() < 0.5:
                    x = WIDTH // 2 + random.randint(-10, 10)
                    y = HEIGHT - 2
                    angle = random.uniform(-0.5, 0.5) - math.pi/2
                    speed = random.uniform(30, 50)
                    vx = math.cos(angle) * speed
                    vy = math.sin(angle) * speed
                    hue = (t * 50 + random.randint(0, 60)) % 360
                    color = hsv_to_rgb(hue, 1.0, 1.0)
                    particles.append(Particle(x, y, vx, vy, 3.0, '◆', color))
                
                # Side bursts
                if random.random() < 0.05:
                    side = random.choice([0, WIDTH-1])
                    y = random.randint(HEIGHT//3, 2*HEIGHT//3)
                    vx = 40 if side == 0 else -40
                    vy = random.uniform(-10, 10)
                    particles.append(Particle(side, y, vx, vy, 2.0, '★', (255, 200, 50)))
                
                # Sparkles
                if random.random() < 0.1:
                    x = random.randint(0, WIDTH-1)
                    y = random.randint(0, HEIGHT//2)
                    particles.append(Particle(x, y, 0, 5, 1.0, '✦', (255, 255, 255)))
                
                # Render frame
                print(HOME)
                frame = render_frame(t, particles, fire_buffer, rain_columns)
                print(frame)
                
                # FPS counter
                frame_count += 1
                if current_time - fps_time >= 1.0:
                    current_fps = frame_count
                    frame_count = 0
                    fps_time = current_time
                
                print(f"\n{RESET}FPS: {current_fps} | Particles: {len(particles)} | Time: {t:.1f}s")
                print("Press Ctrl+C to exit")
                
                last_time = current_time
                t += dt
            
            time.sleep(0.001)
    
    except KeyboardInterrupt:
        # Restore cursor and clear
        print(SHOW_CURSOR + CLEAR + HOME)
        print("Animation stopped!")

if __name__ == "__main__":
    # Check if terminal supports colors (can be overridden with FORCE_COLOR)
    if not sys.stdout.isatty() and os.environ.get('FORCE_COLOR', '').lower() not in ('1', 'true', 'yes'):
        # Check if we're in a pseudo terminal or have color support indicators
        if not any([
            os.environ.get('TERM', '').startswith('xterm'),
            os.environ.get('COLORTERM'),
            os.environ.get('FORCE_COLOR'),
            # Common CI/pseudo-terminal indicators
            os.environ.get('CI'),
            os.environ.get('GITHUB_ACTIONS'),
        ]):
            print("This script requires a terminal that supports ANSI colors!")
            print("If you're sure your terminal supports colors, run with: FORCE_COLOR=1 python3 animation.py")
            sys.exit(1)
    
    # Set terminal to UTF-8 if possible
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    
    main()

