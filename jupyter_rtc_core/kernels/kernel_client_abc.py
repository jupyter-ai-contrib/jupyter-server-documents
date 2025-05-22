import typing as t
from abc import ABC, abstractmethod

from jupyter_rtc_core.rooms.yroom import YRoom


class KernelClientABC(ABC):
    
    @abstractmethod
    async def start_listening(self):
        ...
        
    @abstractmethod
    async def stop_listening(self):
        ...
        
    @abstractmethod
    def handle_incoming_message(self, channel_name: str, msg: list[bytes]):
        ...
        
    @abstractmethod
    async def handle_outgoing_message(self, channel_name: str, msg: list[bytes]):
        ...

    @abstractmethod
    def add_listener(self, callback: t.Callable[[str, list[bytes]], None]):
        ...
        
    @abstractmethod
    def remove_listener(self, callback: t.Callable[[str, list[bytes]], None]):
        ...


class DocumentAwareKernelClientABC(KernelClientABC):
    
    @abstractmethod    
    async def add_yroom(self, yroom: YRoom):
        ...

    @abstractmethod
    async def remove_yroom(self, yroom: YRoom):
        ...