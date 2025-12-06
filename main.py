# main.py
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import SQLModel, Field, Session, create_engine, select
from passlib.hash import bcrypt
import uuid
from typing import Optional, Dict, List
import time

from go_engine import Board, BLACK, WHITE
from models import User, Lobby, Game
# в начале файла (если ещё нет)
from pydantic import BaseModel

app = FastAPI()

DATABASE_URL = "sqlite:///./db/go_app.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)

app.mount("/static", StaticFiles(directory="static"), name="static")

# very simple token store (demo only)
TOKENS: Dict[str,int] = {}
ONLINE_USERS: Dict[int, bool] = {}  # user_id -> online

@app.get("/", response_class=HTMLResponse)
async def index():
    with open('static/index.html', 'r', encoding='utf-8') as f:
        return f.read()

class RegisterIn(BaseModel):
    username: str
    password: str

# Замените старую /api/register на этот блок
@app.post('/api/register')
def register(data: RegisterIn):
    username = (data.username or "").strip()
    password = data.password or ""
    if not username or not password:
        raise HTTPException(400, 'username and password required')

    # Обрежем пароль по байтам до 72 (bcrypt limit)
    pw_bytes = password.encode('utf-8')
    if len(pw_bytes) > 72:
        pw_bytes = pw_bytes[:72]
        safe_password = pw_bytes.decode('utf-8', 'ignore')
        # можно логировать факт усечения
        print(f"[WARN] password for user {username} truncated to 72 bytes for bcrypt")
    else:
        safe_password = password

    # пробуем захешировать, ловим возможные исключения
    try:
        hashed = bcrypt.hash(safe_password)
    except Exception as e:
        # возвращаем понятную ошибку вместо 500
        raise HTTPException(500, f'password hashing failed: {e}')

    with Session(engine) as s:
        existing = s.exec(select(User).where(User.username == username)).first()
        if existing:
            raise HTTPException(400, 'username taken')
        u = User(username=username, password_hash=hashed)
        s.add(u); s.commit(); s.refresh(u)
        return {'id': u.id, 'username': u.username}

class LoginIn(BaseModel):
    username: str
    password: str

@app.post('/api/login_json')
def login_json(data: LoginIn):
    username = (data.username or "").strip()
    password = data.password or ""
    if not username or not password:
        raise HTTPException(400, 'username and password required')

    # обрезаем пароль по байтам аналогично при проверке
    pw_bytes = password.encode('utf-8')
    if len(pw_bytes) > 72:
        pw_bytes = pw_bytes[:72]
    safe_password = pw_bytes.decode('utf-8', 'ignore')

    with Session(engine) as s:
        u = s.exec(select(User).where(User.username == username)).first()
        if not u:
            raise HTTPException(401, 'invalid credentials')
        try:
            ok = bcrypt.verify(safe_password, u.password_hash)
        except Exception as e:
            raise HTTPException(500, f'password verify failed: {e}')
        if not ok:
            raise HTTPException(401, 'invalid credentials')
        token = str(uuid.uuid4())
        TOKENS[token] = u.id
        ONLINE_USERS[u.id] = True
        return {'access_token': token, 'token_type': 'bearer', 'user': {'id': u.id, 'username': u.username, 'role': u.role}}




@app.post('/api/logout')
def logout(token: Optional[str] = None):
    if not token:
        raise HTTPException(401, 'no token')
    uid = TOKENS.pop(token, None)
    if uid:
        ONLINE_USERS[uid] = False
    return {'ok': True}

def get_user_by_token(token: Optional[str]):
    if not token: return None
    uid = TOKENS.get(token)
    if not uid: return None
    with Session(engine) as s:
        return s.get(User, uid)

@app.get('/api/lobbies')
def list_lobbies():
    with Session(engine) as s:
        l = s.exec(select(Lobby)).all()
        # attach player usernames for convenience
        out = []
        for lob in l:
            g = s.exec(select(Game).where(Game.lobby_id == lob.id)).first()
            black = None
            white = None
            if g and g.black_user_id:
                bu = s.get(User, g.black_user_id)
                black = bu.username if bu else None
            if g and g.white_user_id:
                wu = s.get(User, g.white_user_id)
                white = wu.username if wu else None
            out.append({'id': lob.id, 'name': lob.name, 'owner_user_id': lob.owner_user_id, 'board_size': lob.board_size, 'status': lob.status, 'time_control': lob.time_control, 'black': black, 'white': white, 'game_id': g.id if g else None})
        return out

@app.get('/api/online')
def online_list():
    # returns list of online users and their ids
    with Session(engine) as s:
        users = s.exec(select(User)).all()
        return [{'id': u.id, 'username': u.username, 'online': ONLINE_USERS.get(u.id, False), 'role': u.role} for u in users]

class LobbyCreate(BaseModel):
    name: str
    timer: Optional[int] = 600  # по умолчанию 600 секунд

@app.post("/api/lobbies")
def create_lobby(lobby: LobbyCreate, token: str):
    user_id = TOKENS.get(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    with Session(engine) as s:
        u = s.get(User, user_id)
        if not u:
            raise HTTPException(401, "User not found")
        
        # создаём лобби с фиксированным размером 2
        new_lobby = Lobby(
            name=lobby.name.strip(),
            timer=lobby.timer,
            size=2,
            creator_id=u.id,
            players=[u.id]  # сразу добавляем создателя
        )
        s.add(new_lobby)
        s.commit()
        s.refresh(new_lobby)
        return new_lobby

@app.post('/api/join_lobby')
def join_lobby(lobby_id: int, token: Optional[str] = None):
    user = get_user_by_token(token)
    if not user: raise HTTPException(401, 'auth')
    with Session(engine) as s:
        lob = s.get(Lobby, lobby_id)
        if not lob: raise HTTPException(404, 'no lobby')
        g = s.exec(select(Game).where(Game.lobby_id == lob.id)).first()
        if not g:
            g = Game(lobby_id=lob.id, board_size=lob.board_size)
            s.add(g); s.commit(); s.refresh(g)
        # assign to black or white if empty
        if g.black_user_id is None:
            g.black_user_id = user.id
        elif g.white_user_id is None and g.black_user_id != user.id:
            g.white_user_id = user.id
        else:
            # already in or full
            pass
        s.add(g); s.commit(); s.refresh(g)
        return {'ok': True, 'game_id': g.id, 'black': g.black_user_id, 'white': g.white_user_id}

@app.post('/api/leave_lobby')
def leave_lobby(lobby_id: int, token: Optional[str] = None):
    user = get_user_by_token(token)
    if not user: raise HTTPException(401, 'auth')
    with Session(engine) as s:
        g = s.exec(select(Game).where(Game.lobby_id == lobby_id)).first()
        if not g: raise HTTPException(404,'no game')
        changed = False
        if g.black_user_id == user.id:
            g.black_user_id = None; changed = True
        if g.white_user_id == user.id:
            g.white_user_id = None; changed = True
        s.add(g); s.commit();
        return {'ok': True}

@app.post('/api/start_game')
def start_game(lobby_id: int, token: Optional[str] = None):
    user = get_user_by_token(token)
    if not user: raise HTTPException(401, 'auth')
    with Session(engine) as s:
        lob = s.get(Lobby, lobby_id)
        if not lob: raise HTTPException(404,'no lobby')
        if lob.owner_user_id != user.id:
            raise HTTPException(403,'only owner can start')
        g = s.exec(select(Game).where(Game.lobby_id == lob.id)).first()
        if not g or not g.black_user_id or not g.white_user_id:
            raise HTTPException(400,'need two players')
        lob.status = 'playing'
        s.add(lob); s.commit(); s.refresh(lob)
        return {'ok': True, 'game_id': g.id}

@app.post('/api/ban_user')
def ban_user(user_id: int, token: Optional[str] = None):
    caller = get_user_by_token(token)
    if not caller or caller.role != 'admin':
        raise HTTPException(403,'admin required')
    with Session(engine) as s:
        u = s.get(User, user_id)
        if not u: raise HTTPException(404,'no user')
        u.role = 'banned'
        s.add(u); s.commit()
        return {'ok': True}

@app.post('/api/unban_user')
def unban_user(user_id: int, token: Optional[str] = None):
    caller = get_user_by_token(token)
    if not caller or caller.role != 'admin':
        raise HTTPException(403,'admin required')
    with Session(engine) as s:
        u = s.get(User, user_id)
        if not u: raise HTTPException(404,'no user')
        if u.role == 'banned':
            u.role = 'user'
        s.add(u); s.commit()
        return {'ok': True}

# WebSocket manager
class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, List[WebSocket]] = {}
        self.games_state: Dict[int, Board] = {}
        self.game_meta: Dict[int, dict] = {}  # store metadata: last_action_ts etc.

    async def connect(self, game_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active.setdefault(game_id, []).append(websocket)

    def disconnect(self, game_id:int, websocket: WebSocket):
        if game_id in self.active and websocket in self.active[game_id]:
            self.active[game_id].remove(websocket)

    async def broadcast(self, game_id:int, message: dict):
        conns = list(self.active.get(game_id, []))
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

@app.websocket('/ws/game/{game_id}')
async def ws_game(websocket: WebSocket, game_id: int, token: Optional[str] = None):
    user = get_user_by_token(token)
    await manager.connect(game_id, websocket)
    try:
        # initialize game state if missing
        if game_id not in manager.games_state:
            # fetch lobby time_control
            with Session(engine) as s:
                g = s.get(Game, game_id)
                if g is None:
                    board = Board()
                else:
                    lob = s.get(Lobby, g.lobby_id) if g and g.lobby_id else None
                    tc = lob.time_control if lob else None
                    board = Board(size=g.board_size or 19, time_control=tc)
            manager.games_state[game_id] = board
            manager.game_meta[game_id] = {'last_ts': time.time()}
        board = manager.games_state[game_id]
        await websocket.send_json({'type':'state','board': board.board_state()})
        while True:
            data = await websocket.receive_json()
            typ = data.get('type')
            # timing: before processing move, consume time for current player
            if board.time_control is not None:
                now = time.time()
                last = manager.game_meta[game_id].get('last_ts', now)
                elapsed = now - last
                player = board.to_move
                board.remaining[player] -= elapsed
                manager.game_meta[game_id]['last_ts'] = now
                if board.remaining[player] <= 0:
                    winner = BLACK if player == WHITE else WHITE
                    await manager.broadcast(game_id, {'type':'result','msg': f'timeout, winner: {"black" if winner==BLACK else "white"}'})
                    break
            if typ == 'play':
                x = int(data.get('x'))
                y = int(data.get('y'))
                color = board.to_move
                ok, reason = board.play_move(x,y,color)
                if not ok:
                    await websocket.send_json({'type':'error','reason':reason})
                else:
                    manager.game_meta[game_id]['last_ts'] = time.time()
                    await manager.broadcast(game_id, {'type':'state','board': board.board_state()})
            elif typ == 'pass':
                board.pass_move()
                manager.game_meta[game_id]['last_ts'] = time.time()
                await manager.broadcast(game_id, {'type':'state','board': board.board_state()})
            elif typ == 'resign':
                await manager.broadcast(game_id, {'type':'result','msg':'player resigned'})
                break
    except WebSocketDisconnect:
        manager.disconnect(game_id, websocket)

if __name__ == '__main__':
    uvicorn.run('main:app', host='127.0.0.1', port=8000, reload=True)
