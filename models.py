# models.py
from sqlmodel import SQLModel, Field
from typing import Optional

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str
    password_hash: str
    role: str = "user"

class Lobby(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    owner_user_id: Optional[int]
    board_size: int = 19
    status: str = "open"
    time_control: Optional[int] = None

class Game(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lobby_id: Optional[int]
    black_user_id: Optional[int]
    white_user_id: Optional[int]
    board_size: int = 19
    komi: float = 6.5
    result: Optional[str] = None
