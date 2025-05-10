import typing
import asyncio
from traitlets import default
from traitlets import Instance
from traitlets import Int
from traitlets import Dict
from traitlets import Type
from traitlets import Unicode
from traitlets import validate
from traitlets import observe
from traitlets import Set
from traitlets import TraitError
from traitlets import DottedObjectName
from traitlets.utils.importstring import import_item

from jupyter_client.manager import AsyncKernelManager

# from . import types
from .states import ExecutionStates, LifecycleStates
from .kernel_client import AsyncKernelClient


class NextGenKernelManager(AsyncKernelManager):
    
    main_client = Instance(AsyncKernelClient, allow_none=True)

    client_class = DottedObjectName(
        "jupyter_rtc_core.kernels.kernel_client.DocumentAwareKernelClient"
    )
    
    client_factory: Type = Type(klass="jupyter_rtc_core.kernels.kernel_client.DocumentAwareKernelClient")

    connection_attempts: int = Int(
        default_value=10,
        help="The number of initial heartbeat attempts once the kernel is alive. Each attempt is 1 second apart."
    ).tag(config=True)
    
    execution_state: ExecutionStates = Unicode()
    
    @validate("execution_state")
    def _validate_execution_state(self, proposal: dict):
        value = proposal["value"]
        if type(value) == ExecutionStates:
            # Extract the enum value.
            value = value.value
        if not value in ExecutionStates:
            raise TraitError(f"execution_state must be one of {ExecutionStates}")
        return value

    lifecycle_state: LifecycleStates = Unicode()
    
    @validate("lifecycle_state")
    def _validate_lifecycle_state(self, proposal: dict):
        value = proposal["value"]
        if type(value) == LifecycleStates:
            # Extract the enum value.
            value = value.value
        if not value in LifecycleStates:
            raise TraitError(f"lifecycle_state must be one of {LifecycleStates}")
        return value
    
    state = Dict()
    
    @default('state')
    def _default_state(self):
        return {
            "execution_state": self.execution_state,
            "lifecycle_state": self.lifecycle_state
        }
    
    @observe('execution_state')
    def _observer_execution_state(self, change):
        state = self.state
        state["execution_state"] = change['new']
        self.state = state    
    
    @observe('lifecycle_state')
    def _observer_lifecycle_state(self, change):
        state = self.state
        state["lifecycle_state"] = change['new']
        self.state = state    
    
    @validate('state')
    def _validate_state(self, change):
        value = change['value']
        if 'execution_state' not in value or 'lifecycle_state' not in value:
            TraitError("State needs to include execution_state and lifecycle_state")
        return value
    
    @observe('state')
    def _state_changed(self, change):
        for observer in self._state_observers:
            observer(change["new"])
    
    _state_observers = Set(allow_none=True)
    
    def set_state(
        self, 
        lifecycle_state: LifecycleStates = None, 
        execution_state: ExecutionStates = None,
        broadcast=True
    ):
        if lifecycle_state:
            self.lifecycle_state = lifecycle_state.value
        if execution_state:
            self.execution_state = execution_state.value
            
        if broadcast:
            # Broadcast this state change to all listeners
            self.broadcast_state()

    async def start_kernel(self, *args, **kwargs):
        self.set_state(LifecycleStates.STARTING, ExecutionStates.STARTING)
        out = await super().start_kernel(*args, **kwargs)
        self.set_state(LifecycleStates.STARTED)
        await self.connect()
        return out
        
    async def shutdown_kernel(self, *args, **kwargs):
        self.set_state(LifecycleStates.TERMINATING)
        await self.disconnect()
        out = await super().shutdown_kernel(*args, **kwargs)
        self.set_state(LifecycleStates.TERMINATED, ExecutionStates.DEAD)
     
    async def restart_kernel(self, *args, **kwargs):
        self.set_state(LifecycleStates.RESTARTING)
        return await super().restart_kernel(*args, **kwargs)

    async def connect(self):
        """Open a single client interface to the kernel.
        
        Ideally this method doesn't care if the kernel
        is actually started. It will just try a ZMQ 
        connection anyways and wait. This is helpful for
        handling 'pending' kernels, which might still 
        be in a starting phase. We can keep a connection
        open regardless if the kernel is ready. 
        """
        self.set_state(LifecycleStates.CONNECTING, ExecutionStates.BUSY)
        # Use the new API for getting a client.
        self.main_client = self.client()
        # Track execution state by watching all messages that come through
        # the kernel client.
        self.main_client.add_listener(self.execution_state_listener)
        self.main_client.start_channels()
        await self.main_client.start_listening()
        # The Heartbeat channel is paused by default; unpause it here
        self.main_client.hb_channel.unpause()
        # Wait for a living heartbeat.
        attempt = 0
        while not self.main_client.hb_channel.is_alive():
            attempt += 1
            if attempt > self.connection_attempts:
                # Set the state to unknown.
                self.set_state(LifecycleStates.UNKNOWN, ExecutionStates.UNKNOWN)
                raise Exception("The kernel took too long to connect to the ZMQ sockets.")
            # Wait a second until the next time we try again.
            await asyncio.sleep(1)
        # Send an initial kernel info request on the shell channel.
        self.main_client.send_kernel_info()
        self.set_state(LifecycleStates.CONNECTED)
        
    async def disconnect(self):
        await self.main_client.stop_listening()
        self.main_client.stop_channels()

    def broadcast_state(self):
        """Broadcast state to all listeners"""
        if not self.main_client:
            return 
        
        # Emit this state to all listeners
        for listener in self.main_client._listeners:
            # Manufacture a status message
            session = self.main_client.session
            msg = session.msg("status", {"execution_state": self.execution_state})
            msg = session.serialize(msg)
            listener("iopub", msg)    
            
    def execution_state_listener(self, channel_name: str, msg: list[bytes]):
        """Set the execution state by watching messages returned by the shell channel."""
        # Only continue if we're on the IOPub where the status is published.
        if channel_name != "iopub":
            return
        session = self.main_client.session        
        # Unpack the message 
        deserialized_msg = session.deserialize(msg, content=False)
        if deserialized_msg["msg_type"] == "status":
            content = session.unpack(deserialized_msg["content"])
            execution_state = content["execution_state"]
            if execution_state == "starting":
                # Don't broadcast, since this message is already going out.
                self.set_state(LifecycleStates.STARTING, execution_state, broadcast=False)
            else:
                parent = deserialized_msg.get("parent_header", {})
                msg_id = parent.get("msg_id", "")
                parent_channel = self.main_client.message_source_cache.get(msg_id, None)
                if parent_channel and parent_channel == "shell":
                    # Don't broadcast, since this message is already going out.
                    self.set_state(LifecycleStates.CONNECTED, execution_state, broadcast=False)
            