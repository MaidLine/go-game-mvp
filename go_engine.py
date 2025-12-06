# go_engine.py
# Простая реализация движка Го с подсчётом по area (китайский), поддержкой захватов, проверкой самоуничтожения и запрета повторов (superko).

from collections import deque
import hashlib
import copy
import time

EMPTY = 0
BLACK = 1
WHITE = 2

class Board:
    def __init__(self, size=19, komi=6.5, time_control=None):
        self.size = size
        self.komi = komi
        self.grid = [[EMPTY]*size for _ in range(size)]
        self.history_hashes = set()
        self._push_history()
        self.captured = {BLACK:0, WHITE:0}
        self.to_move = BLACK  # black starts
        # timing
        self.time_control = time_control  # seconds per player (int) or None
        if time_control is not None:
            self.remaining = {BLACK: time_control, WHITE: time_control}
            self.last_action_ts = time.time()
        else:
            self.remaining = None
            self.last_action_ts = None

    def clone(self):
        b = Board(self.size, self.komi, self.time_control)
        b.grid = copy.deepcopy(self.grid)
        b.history_hashes = set(self.history_hashes)
        b.captured = dict(self.captured)
        b.to_move = self.to_move
        if self.remaining is not None:
            b.remaining = dict(self.remaining)
            b.last_action_ts = self.last_action_ts
        return b

    def _hash(self):
        s = ''.join(str(c) for row in self.grid for c in row) + str(self.to_move)
        return hashlib.sha1(s.encode()).hexdigest()

    def _push_history(self):
        self.history_hashes.add(self._hash())

    def inside(self,x,y):
        return 0 <= x < self.size and 0 <= y < self.size

    def neighbors(self,x,y):
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny = x+dx, y+dy
            if self.inside(nx,ny):
                yield nx,ny

    def _group_and_liberties(self, x, y):
        color = self.grid[y][x]
        if color == EMPTY:
            return set(), set()
        q = deque()
        q.append((x,y))
        visited = set([(x,y)])
        liberties = set()
        while q:
            cx,cy = q.popleft()
            for nx,ny in self.neighbors(cx,cy):
                if self.grid[ny][nx] == EMPTY:
                    liberties.add((nx,ny))
                elif self.grid[ny][nx] == color and (nx,ny) not in visited:
                    visited.add((nx,ny))
                    q.append((nx,ny))
        return visited, liberties

    def _remove_group(self, group):
        any_point = next(iter(group))
        ax, ay = any_point
        color = self.grid[ay][ax]
        for x,y in group:
            self.grid[y][x] = EMPTY
        return color, len(group)

    def legal_on_clone(self,x,y,color):
        b = self.clone()
        if not b.inside(x,y): return False, "out_of_bounds"
        if b.grid[y][x] != EMPTY: return False, "occupied"
        b.grid[y][x] = color
        opp = BLACK if color == WHITE else WHITE
        removed = []
        for nx,ny in b.neighbors(x,y):
            if b.grid[ny][nx] == opp:
                grp, libs = b._group_and_liberties(nx,ny)
                if len(libs) == 0:
                    removed.append(grp)
        for grp in removed:
            for gx,gy in grp:
                b.grid[gy][gx] = EMPTY
        grp, libs = b._group_and_liberties(x,y)
        if len(libs) == 0:
            return False, "suicide"
        b.to_move = opp
        h = b._hash()
        if h in b.history_hashes:
            return False, "ko_repetition"
        return True, "ok"

    def play_move(self, x, y, color=None):
        if color is None:
            color = self.to_move
        ok, reason = self.legal_on_clone(x,y,color)
        if not ok:
            return False, reason
        # apply on real board
        self.grid[y][x] = color
        opp = BLACK if color == WHITE else WHITE
        to_remove = []
        for nx,ny in self.neighbors(x,y):
            if self.grid[ny][nx] == opp:
                grp, libs = self._group_and_liberties(nx,ny)
                if len(libs) == 0:
                    to_remove.append(grp)
        for grp in to_remove:
            for gx,gy in grp:
                self.grid[gy][gx] = EMPTY
            self.captured[color] += len(grp)
        self.to_move = opp
        self._push_history()
        return True, "ok"

    def pass_move(self):
        self.to_move = BLACK if self.to_move == WHITE else WHITE
        self._push_history()

    def score_area(self):
        visited = [[False]*self.size for _ in range(self.size)]
        area = {BLACK:0, WHITE:0}
        for y in range(self.size):
            for x in range(self.size):
                c = self.grid[y][x]
                if c == BLACK: area[BLACK]+=1
                elif c == WHITE: area[WHITE]+=1
        for y in range(self.size):
            for x in range(self.size):
                if self.grid[y][x] != EMPTY or visited[y][x]:
                    continue
                q = deque([(x,y)])
                visited[y][x] = True
                region = [(x,y)]
                bordering = set()
                while q:
                    cx,cy = q.popleft()
                    for nx,ny in self.neighbors(cx,cy):
                        if self.grid[ny][nx] == EMPTY and not visited[ny][nx]:
                            visited[ny][nx] = True
                            q.append((nx,ny))
                            region.append((nx,ny))
                        elif self.grid[ny][nx] in (BLACK,WHITE):
                            bordering.add(self.grid[ny][nx])
                if len(bordering) == 1:
                    player = next(iter(bordering))
                    area[player] += len(region)
        black_score = area[BLACK]
        white_score = area[WHITE] + self.komi
        return {'black':black_score, 'white':white_score, 'diff': black_score - white_score}

    # timing helpers
    def consume_time(self):
        """
        Рассчитать и вычесть время, прошедшее с last_action_ts у текущего игрока.
        Возвращает (timed_out_bool, which_player_timed_out_or_None)
        """
        if self.time_control is None or self.remaining is None:
            return False, None
        now = time.time()
        elapsed = now - (self.last_action_ts or now)
        player = self.to_move
        self.remaining[player] -= elapsed
        self.last_action_ts = now
        if self.remaining[player] <= 0:
            return True, player
        return False, None

    def board_state(self):
        return {'size': self.size, 'grid': self.grid, 'to_move': self.to_move, 'captured': self.captured, 'remaining': self.remaining}
