"""
Controller.py: turns BCI input (or, in principle, any input source with a
`.poll_direction()` method) into player movement on the maze grid.

This is a good file to read if you want to understand *when* a move is
accepted, but most usability tweaks (arrow layout, colors, sizes) belong in
UI.py and Config.py instead.
"""
from Config import VEC, WALK_SPEED_PX_S, MOVE_COOLDOWN_S, FEEDBACK_S


class Controller:
    """
    Owns the player's position/heading and applies incoming BCI directions
    to it, one grid cell at a time.

    `bci` is any object exposing `poll_direction() -> 'N'|'E'|'S'|'W'|''`.
    Main.py passes in a real `BCIListener`; tests or a keyboard-driven demo
    could pass in something else that implements the same method.
    """

    def __init__(self, maze, cell_px=48, walk_speed_px_s=WALK_SPEED_PX_S, bci=None):
        self.maze = maze
        self.cell_px = cell_px
        self.walk_speed = walk_speed_px_s
        self.pos_rc = maze.start
        self.heading = "E"
        self.armed_dir = None
        self.bci = bci

        # --- move debouncing -------------------------------------------------
        # After every command (a step or a wall bump) we ignore new directions for
        # `_move_cooldown` seconds. This stops a single sustained BCI
        # detection from being read as many rapid-fire moves.
        self._move_cooldown = MOVE_COOLDOWN_S
        self._cd_left = 0.0

        self.step_count = 0
        self.elapsed_time = 0.0

        # usability: did the last command move the duck or hit a wall, and how long we still show it
        self.last_moved = True
        self.feedback_left = 0.0
        # usability: true when the duck is on the goal, then the game stops
        self.finished = False
        # usability: space pauses the game, no input and no timer
        self.paused = False

    def _try_step(self, d):
        """
        Attempt to move one cell in direction `d`.
        Returns True and updates position/heading if that cell is walkable,
        otherwise returns False and leaves the player where it was.
        """
        dr, dc = VEC[d]
        nxt = (self.pos_rc[0] + dr, self.pos_rc[1] + dc)
        if self.maze.is_path(nxt):
            self.pos_rc = nxt
            self.heading = d
            self.step_count += 1
            return True
        return False

    # usability: one place for a command, the bci and the arrow keys both use it
    def move(self, d):
        """Apply one command in direction `d` (from the BCI or an arrow key)."""
        # usability: no moves while paused or after the goal
        if self.paused or self.finished:
            return

        self.armed_dir = d  # remember it so UI.py can highlight the matching arrow
        self.last_moved = self._try_step(d)
        self.feedback_left = FEEDBACK_S
        # usability: we wait after every command, a wall bump too, so one look is one command
        self._cd_left = self._move_cooldown

        # usability: you reached G so the game stops here
        if self.pos_rc == self.maze.goal:
            self.finished = True

    def handle_bci(self, dt):
        """Poll the BCI source (if any) and apply a move if one is ready."""
        if not self.bci:
            return

        # usability: we always read the stream, so old detections dont wait in the buffer and fire after the cooldown
        d = self.bci.poll_direction()  # 'N', 'E', 'S', 'W', or '' (nothing detected)
        # usability: a detection that comes during the cooldown is thrown away
        if d and self._cd_left <= 0:
            self.move(d)

    def update(self, dt):
        """Advance game state by `dt` seconds. Call once per frame from Main.py."""
        # usability: the timer stops when you pause or reach the goal
        if not (self.paused or self.finished):
            self.elapsed_time += dt

        if self._cd_left > 0:
            self._cd_left -= dt

        # usability: the highlight goes away after FEEDBACK_S so an old command does not look like a new one
        if self.feedback_left > 0:
            self.feedback_left -= dt
            if self.feedback_left <= 0:
                self.armed_dir = None

        self.handle_bci(dt)

    # usability: r puts everything back to the start without closing the game
    def restart(self):
        """Start the level again: duck on S, steps, time and all feedback reset."""
        self.pos_rc = self.maze.start
        self.heading = "E"
        self.armed_dir = None
        self._cd_left = 0.0
        self.step_count = 0
        self.elapsed_time = 0.0
        self.last_moved = True
        self.feedback_left = 0.0
        self.finished = False
        self.paused = False