"""
UI.py: everything that gets drawn to the screen: the left sidebar (the
four flickering arrows + a status readout) and the maze itself
(walls, path, start/goal, the player avatar).

This is the main file you'll want to edit to fix usability problems with
the arrows: their size (Config.ARROW_SIZE_PX), spacing, order
(Config.SIDEBAR_ORDER), color, contrast, and labeling are all decided in
`_draw_sidebar` and its helpers below. This file only draws the arrows;
it does not decide what frequency each one flickers at or how sensitive
its detection is; those live in `Config.DIRECTIONS`, so change frequencies
and thresholds there rather than here.

Quick map of this file:
    UI.__init__            - loads fonts/images, builds one FlashableIcon per arrow
    draw                   - called once per frame from Main.py; draws everything
    _draw_sidebar          - top-level: panel + title, then lays out and draws the arrows
    _layout_arrow_positions - works out where each arrow's center goes (size is fixed)
    _make_checker_surface  - "square" mode: the small flickering checker pattern
    _make_solid_surface    - "cosine" mode: a solid color that fades smoothly instead
    _draw_one_arrow        - masks the arrow's fill into its shape and draws it
    _draw_wall_tile        - one visual "brick" of maze wall
    _draw_maze             - the maze grid (walls/path/start/goal)
    _draw_avatar           - the player icon
    _arrow_polygon         - the (x, y) points that make up one arrow's outline
    _draw_hud              - the small "steps / time" text at the bottom
    draw_eeg_scope         - optional live EEG trace panel
"""
import numpy as np
import pygame as pg

from FlashableIcon import FlashableIcon
from Config import (
    BG, PANEL, TEXT, CHECKER1, CHECKER2, ARROW_ARMED_TINT, PATH, START, GOAL,
    FREQUENCIES, REFRESH_HZ, ARROW_SIZE_PX, ICON_FLICKER_MODE,
    EDGE_PX, ARROW_WALL_TINT, ARROW_WAIT_TINT,
)

# usability: full names for the message line, a single letter is easy to miss
DIR_NAMES = {"N": "north", "S": "south", "W": "west", "E": "east"}


def _shade(rgb, factor):
    """Multiply an (r, g, b) color by `factor` (e.g. 0.8 = darker, 1.2 = lighter)."""
    r, g, b = rgb
    return (max(0, min(255, int(r * factor))),
            max(0, min(255, int(g * factor))),
            max(0, min(255, int(b * factor))))


class UI:
    """
    Renders:
      - Maze in the middle of the window (walls, path, start/goal)
      - One arrow on each side of the maze + tiny HUD in the corner
      - Avatar as rubber_duck.png centered in its cell
    """
    def __init__(self, surface: pg.Surface, cell_px: int = 48, maze_rect: pg.Rect = None):
        self.surf = surface
        self.cell_px = cell_px
        # usability: where the maze sits in the window, the arrows go around it
        self.maze_rect = maze_rect

        pg.font.init()
        self.font = pg.font.SysFont("consolas", 16)
        self.small = pg.font.SysFont("consolas", 13)
        # usability: big text for the goal and pause messages
        self.big = pg.font.SysFont("consolas", 40)

        # avatar image
        img = pg.image.load("rubber_duck.png").convert_alpha()
        self.avatar_img = pg.transform.smoothscale(img, (int(cell_px * 0.8), int(cell_px * 0.8)))

        # One flicker generator per direction, driven by the frequencies
        # defined once in Config.DIRECTIONS: do not hardcode frequencies
        # here again, or the sidebar and the BCI pipeline can drift apart.
        # ICON_FLICKER_MODE ("square" or "cosine") picks the flicker style
        # for all arrows — see Config.py and FlashableIcon.py.
        self.icons = {d: FlashableIcon(f, refresh_hz=REFRESH_HZ, mode=ICON_FLICKER_MODE)
                      for d, f in FREQUENCIES.items()}

    # --------------- public API ---------------
    def draw(self, maze, pos_rc, armed_dir, steps=0, elapsed_s=0.0,
             waiting=False, hit_wall=False, finished=False, paused=False):
        """Draw one full frame: maze, avatar, arrows, HUD and messages. Call once per frame."""
        # usability: clear the whole window, the arrows are all around the maze now and not in one sidebar
        self.surf.fill(BG)
        self._draw_maze(maze)
        self._draw_avatar(pos_rc)
        # usability: no flicker when paused or done, there is nothing to choose then
        if not (paused or finished):
            self._draw_arrows(armed_dir, waiting, hit_wall)
        # small HUD (now includes steps + timer)
        self._draw_hud(maze, pos_rc, steps, elapsed_s)
        # usability: says what the last command did, moved or hit a wall
        self._draw_message(armed_dir, hit_wall)

        mins = int(elapsed_s // 60)
        secs = int(elapsed_s % 60)
        # usability: tell the player they made it, with the steps and the time
        if finished:
            self._draw_banner(f"Goal reached in {steps} steps, {mins:02d}:{secs:02d}", GOAL)
        # usability: shows that the game is paused and how to go on
        elif paused:
            self._draw_banner("Paused, press Space to go on", TEXT)

    # --------------- layout helpers ---------------
    def maze_offset(self):
        """Top-left pixel offset of the maze draw area."""
        return self.maze_rect.topleft

    # --------------- drawing ---------------
    def _draw_arrows(self, armed_dir, waiting, hit_wall):
        """
        Draw the four flickering arrows, one on each side of the maze.

        This is the main place to make usability changes to the arrows:
        size (Config.ARROW_SIZE_PX), the space around the maze
        (Config.EDGE_PX) and the outline colors (Config.ARROW_*_TINT).
        None of this affects which physical frequency each arrow flickers
        at (that lives in Config.DIRECTIONS), only how it looks and where it sits.
        """
        # usability: each arrow sits on the side it points to, so you can watch the duck while you look at it
        r = self.maze_rect
        gap = EDGE_PX // 2  # middle of the free space around the maze
        spots = {
            "N": (r.centerx, r.top - gap),
            "S": (r.centerx, r.bottom + gap),
            "W": (r.left - gap, r.centery),
            "E": (r.right + gap, r.centery),
        }

        frame = getattr(self, "frame_idx", 0)
        for d, (cx, cy) in spots.items():
            outline = None
            # usability: grey outline on every arrow while the cooldown runs
            if waiting:
                outline = ARROW_WAIT_TINT
            # usability: purple when the duck moved, red when it hit a wall
            if d == armed_dir:
                outline = ARROW_WALL_TINT if hit_wall else ARROW_ARMED_TINT
            self._draw_one_arrow(d, cx, cy, ARROW_SIZE_PX, frame, outline)

    def _make_checker_surface(self, size, phase):
        """
        Build the small checkerboard pattern that fills one arrow, for
        "square" flicker mode.

        `phase` is 0 or 1 and swaps which color goes in which square
        alternating `phase` every frame (see FlashableIcon) is what makes
        the arrow appear to flicker.
        """
        checker_surf = pg.Surface((size * 2, size * 2))
        checker_surf.fill((0, 0, 0))
        square = size // 4  # size of each checker cell
        colors = [CHECKER1, CHECKER2] if phase == 0 else [CHECKER2, CHECKER1]
        for row in range(0, size * 2, square):
            for col in range(0, size * 2, square):
                color = colors[((row // square) + (col // square)) % 2]
                pg.draw.rect(checker_surf, color, (col, row, square, square))
        return checker_surf

    def _make_solid_surface(self, size, brightness):
        """
        Build a plain (non-checkered) surface for "cosine" flicker mode.

        Its color fades continuously between CHECKER2 (brightness 0.0) and
        CHECKER1 (brightness 1.0), so the arrow pulses smoothly instead of
        hard-swapping a checker pattern.
        """
        color = tuple(
            int(round(c2 + (c1 - c2) * brightness))
            for c1, c2 in zip(CHECKER1, CHECKER2)
        )
        surf = pg.Surface((size * 2, size * 2))
        surf.fill(color)
        return surf

    def _draw_one_arrow(self, d, cx, cy, size, frame, outline=None):
        """Draw a single flickering arrow centered at (cx, cy), plus its outline color (if any)."""
        icon = self.icons.get(d)
        brightness = icon.luminance(frame) if icon is not None else 0.0

        if icon is not None and icon.mode == "cosine":
            fill_surf = self._make_solid_surface(size, brightness)
        else:
            # "square" mode: brightness is always exactly 0.0 or 1.0.
            phase = int(round(brightness))
            fill_surf = self._make_checker_surface(size, phase)

        # Cut the fill down to an arrow shape: draw the arrow outline in
        # solid white on an otherwise transparent surface, then multiply
        # it onto the fill so only the arrow-shaped pixels survive (this
        # is called "masking").
        poly = self._arrow_polygon(d, (size, size), size)  # centered on the fill surface
        mask = pg.Surface((size * 2, size * 2), pg.SRCALPHA)
        mask.fill((0, 0, 0, 0))
        pg.draw.polygon(mask, (255, 255, 255, 255), poly)
        fill_surf.blit(mask, (0, 0), None, pg.BLEND_RGBA_MULT)

        # draw onto main surface, centered at (cx, cy)
        rect = fill_surf.get_rect(center=(cx, cy))
        self.surf.blit(fill_surf, rect)

        # usability: the outline color says wait, moved or wall. no outline when nothing happened
        # 5 px and not 3 so you still see it while you stare at the arrow
        if outline:
            pg.draw.polygon(self.surf, outline,
                            [(x + cx - size, y + cy - size) for (x, y) in poly], 5)

    def _draw_wall_tile(self, x, y, cp, is_bottom_of_run, is_rightmost_of_run):
        """Draw one wall cell with a simple pseudo-3D "cap + front + side" look."""
        # Colors
        top_col = (105, 154, 104)  # wall cap
        front_col = _shade(top_col, 0.78)  # darker "front"
        right_col = _shade(top_col, 0.86)  # slightly darker "side"
        hi_col = _shade(top_col, 1.25)  # thin highlight on top edge

        depth = max(6, int(cp * 0.22))  # thickness of front overlay
        sidew = max(4, int(cp * 0.12))  # width of right-side overlay

        # 1) Top face = full tile (prevents gaps in vertical stacks)
        top_rect = pg.Rect(x, y, cp, cp)
        pg.draw.rect(self.surf, top_col, top_rect)

        # 2) Front face only at bottom of a vertical run
        if is_bottom_of_run:
            front_rect = pg.Rect(x, y + cp - depth, cp, depth)
            pg.draw.rect(self.surf, front_col, front_rect)

        # 3) Right face only at rightmost cell in a horizontal run
        if is_rightmost_of_run:
            right_rect = pg.Rect(x + cp - sidew, y, sidew, cp)
            pg.draw.rect(self.surf, right_col, right_rect)

        # 4) Subtle highlight along the very top edge for a "cap"
        pg.draw.line(self.surf, hi_col, (x, y), (x + cp, y), 1)

    def _draw_maze(self, maze):
        """Draw the maze grid: walls, open path, start and goal tiles, plus a light grid overlay."""
        offx, offy = self.maze_offset()
        cp = self.cell_px

        # Background for maze area
        maze_rect = pg.Rect(offx, offy, maze.cols * cp, maze.rows * cp)
        pg.draw.rect(self.surf, BG, maze_rect)

        for r in range(maze.rows):
            for c in range(maze.cols):
                x = offx + c * cp
                y = offy + r * cp
                ch = maze.lines[r][c]

                if ch == "#":
                    # Are we at the bottom of a vertical wall run?
                    below_wall = (r + 1 < maze.rows and maze.lines[r + 1][c] == "#")
                    is_bottom = not below_wall  # draw front only at the bottom

                    # Are we at the rightmost of a horizontal wall run?
                    right_wall = (c + 1 < maze.cols and maze.lines[r][c + 1] == "#")
                    is_rightmost = not right_wall  # draw side only on the outer edge

                    self._draw_wall_tile(x, y, cp, is_bottom_of_run=is_bottom, is_rightmost_of_run=is_rightmost)

                elif ch == " ":
                    pg.draw.rect(self.surf, PATH, pg.Rect(x, y, cp, cp))
                elif ch == "S":
                    pg.draw.rect(self.surf, START, pg.Rect(x, y, cp, cp))
                elif ch == "G":
                    pg.draw.rect(self.surf, GOAL, pg.Rect(x, y, cp, cp))

        # Optional subtle grid
        for rr in range(maze.rows + 1):
            yy = offy + rr * cp
            pg.draw.line(self.surf, (35, 35, 42), (offx, yy), (offx + maze.cols * cp, yy), 1)
        for cc in range(maze.cols + 1):
            xx = offx + cc * cp
            pg.draw.line(self.surf, (35, 35, 42), (xx, offy), (xx, offy + maze.rows * cp), 1)

    def _draw_avatar(self, pos_rc):
        """Draw the player avatar centered in its current maze cell."""
        cp = self.cell_px
        offx, offy = self.maze_offset()
        r, c = pos_rc
        cx = offx + c * cp + cp // 2
        cy = offy + r * cp + cp // 2
        rect = self.avatar_img.get_rect(center=(cx, cy))
        self.surf.blit(self.avatar_img, rect)

    def _arrow_polygon(self, d, center_xy, size):
        """Return the triangle points for an arrow pointing in direction `d`, centered at center_xy."""
        cx, cy = center_xy
        s = size
        if d == "N":
            return [(cx, cy - s), (cx - s // 2, cy + s // 2), (cx + s // 2, cy + s // 2)]
        if d == "S":
            return [(cx, cy + s), (cx - s // 2, cy - s // 2), (cx + s // 2, cy - s // 2)]
        if d == "E":
            return [(cx + s, cy), (cx - s // 2, cy - s // 2), (cx - s // 2, cy + s // 2)]
        if d == "W":
            return [(cx - s, cy), (cx + s // 2, cy - s // 2), (cx + s // 2, cy + s // 2)]
        return [(cx, cy)]

    def _draw_hud(self, maze, pos_rc, steps=0, elapsed_s=0.0):
        """Draw the small "position / goal / steps / time" readout and the key hint at the top left."""
        r, c = pos_rc
        # Line 1: position + goal
        line1 = f"r:{r} c:{c}   goal:{maze.goal}"

        # Line 2: steps + timer (mm:ss)
        mins = int(elapsed_s // 60)
        secs = int(elapsed_s % 60)
        line2 = f"steps:{steps}   time:{mins:02d}:{secs:02d}"

        img1 = self.small.render(line1, True, TEXT)
        img2 = self.small.render(line2, True, TEXT)

        # usability: the hud goes in the top left corner, the left side is for the W arrow now
        self.surf.blit(img1, (12, 10))
        self.surf.blit(img2, (12, 28))

        # usability: so you know the keys work in this window too
        hint = self.small.render("arrows: move   space: pause   r: restart   esc: quit", True, TEXT)
        self.surf.blit(hint, (12, 46))

    # usability: one line in the bottom left that says what the last command did
    def _draw_message(self, armed_dir, hit_wall):
        """Draw "Moved north" or "Wall to the east" (in red) while the highlight is on."""
        if not armed_dir:
            return
        name = DIR_NAMES[armed_dir]
        if hit_wall:
            text, color = f"Wall to the {name}", ARROW_WALL_TINT
        else:
            text, color = f"Moved {name}", TEXT
        img = self.font.render(text, True, color)
        self.surf.blit(img, (12, self.surf.get_height() - 30))

    # usability: big text in a box over the middle of the maze, for the goal and pause messages
    def _draw_banner(self, text, color):
        """Draw `text` big and centered on the maze, in a dark box with a `color` border."""
        img = self.big.render(text, True, color)
        box = img.get_rect(center=self.maze_rect.center).inflate(40, 30)
        pg.draw.rect(self.surf, PANEL, box)
        pg.draw.rect(self.surf, color, box, 3)
        self.surf.blit(img, img.get_rect(center=box.center))

    def draw_eeg_scope(self, eeg_8xN: np.ndarray):
        """
        Fast mini-scope for 8 channels:
        - draws only every 4th frame (~15 FPS)
        - downsample to panel width
        - cache per-channel scaling, refresh ~1/s

        Not called by Main.py by default; kept for tools/experiments that
        want to show live EEG traces inside the game window.
        """
        if eeg_8xN is None or eeg_8xN.size == 0:
            return

        fi = getattr(self, "frame_idx", 0)

        # layout
        left_margin = 8
        right_margin = 8
        top = 44 + 4 * 48 + 30              # under your 4 arrows
        width = self.maze_rect.left - (left_margin + right_margin)  # usability: no sidebar anymore, we use the space left of the maze
        height = self.surf.get_height() - top - 8
        if height <= 60 or width <= 10:
            return

        # panel bg
        panel = pg.Rect(0, top - 8, self.maze_rect.left, height + 16)
        pg.draw.rect(self.surf, (22, 22, 22), panel)

        data = eeg_8xN
        ch, n = data.shape
        ch = min(8, ch)
        lanes = ch
        lane_h = max(1, height // lanes)

        # downsample to width
        if n > width:
            idx = np.linspace(0, n - 1, width).astype(int)
            data = data[:, idx]
            n = width
            xs = np.arange(width)
        else:
            xs = np.linspace(0, width - 1, n).astype(int)

        # cache scaling once per second
        scale_refresh_frames = 60
        if getattr(self, "_scope_scale_frame", -9999) + scale_refresh_frames <= fi:
            p_low = []
            p_high = []
            for ci in range(ch):
                seg = data[ci]
                lo, hi = np.percentile(seg, [5, 95])  # robust range
                if hi - lo < 1e-6:  # avoid zero range
                    hi = lo + 1.0
                p_low.append(lo); p_high.append(hi)
            self._scope_p_low = p_low
            self._scope_p_high = p_high
            self._scope_scale_frame = fi

        p_low = getattr(self, "_scope_p_low", [-50.0] * ch)
        p_high = getattr(self, "_scope_p_high", [50.0] * ch)

        # draw lanes
        for ci in range(ch):
            seg = data[ci]
            lo = p_low[ci]; hi = p_high[ci]
            mid = 0.5 * (lo + hi)
            half = 0.5 * (hi - lo)

            y0 = top + ci * lane_h
            y_mid = y0 + lane_h // 2

            # baseline
            pg.draw.line(self.surf, (40, 40, 40), (left_margin, y_mid),
                        (left_margin + width, y_mid), 1)

            # normalized -> pixels
            if half < 1e-6:
                ys = np.full_like(xs, y_mid)
            else:
                norm = (seg - mid) / half         # ~[-1..1]
                ys = (y_mid - norm * (lane_h * 0.40)).astype(int)

            # single polyline
            pts = [(left_margin + x, ys[k]) for k, x in enumerate(xs)]
            if len(pts) > 1:
                pg.draw.lines(self.surf, (0, 200, 255), False, pts, 1)

            # label
            lbl = self.small.render(f"Ch{ci+1}", True, (160, 160, 160))
            self.surf.blit(lbl, (12, y0 + 2))