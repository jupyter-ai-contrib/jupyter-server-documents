"""
WIP.

This file just contains interfaces to be filled out later.
"""

from .yroom import YRoom

class YRoomManager:
    _rooms_by_id: dict[str, YRoom]

    def __init__(self):
        self._rooms_by_id = {}
    
    def get_room(self, room_id: str) -> YRoom | None:
        # TODO
        return None
        
    def delete_room(self, room: YRoom) -> None:
        # TODO
        return