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

from . import types
from . import states
from .kernel_client import AsyncKernelClient


class NextGenKernelManager(AsyncKernelManager):

    main_client = Instance(AsyncKernelClient, allow_none=True)

    client_class = DottedObjectName(
        "jupyter_rtc_core.kernels.kernel_client.NextGenAsyncKernelClient"
    )
    
    client_factory: Type = Type(klass="jupyter_rtc_core.kernels.kernel_client.NextGenAsyncKernelClient")

    # Configurable settings in a kernel manager that I want.
    time_to_connect: int = Int(
        default_value=10,
        help="The timeout for connecting to a kernel."
    ).tag(config=True)
    
    execution_state: types.EXECUTION_STATES = Unicode()
    
    @validate("execution_state")
    def _validate_execution_state(self, proposal: dict):
        if not proposal["value"] in states.EXECUTION_STATES:
            raise TraitError(f"execution_state must be one of {states.EXECUTION_STATES}")
        return proposal["value"]

    lifecycle_state: types.EXECUTION_STATES = Unicode()
    
    @validate("lifecycle_state")
    def _validate_lifecycle_state(self, proposal: dict):
        if not proposal["value"] in states.LIFECYCLE_STATES:
            raise TraitError(f"lifecycle_state must be one of {states.LIFECYCLE_STATES}")
        return proposal["value"]
    
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
        lifecycle_state: typing.Optional[types.LIFECYCLE_STATES] = None, 
        execution_state: typing.Optional[types.EXECUTION_STATES] = None,
        broadcast=True
    ):
        if lifecycle_state:
            self.lifecycle_state = lifecycle_state
        if execution_state:
            self.execution_state = execution_state
            
        if broadcast:
            # Broadcast this state change to all listeners
            self.broadcast_state()

    async def start_kernel(self, *args, **kwargs):
        self.set_state("starting", "starting")
        out = await super().start_kernel(*args, **kwargs)
        self.set_state("started")
        await self.connect()
        return out
        
    async def shutdown_kernel(self, *args, **kwargs):
        self.set_state("terminating")
        await self.disconnect()
        out = await super().shutdown_kernel(*args, **kwargs)
        self.set_state("terminated", "dead")
     
    async def restart_kernel(self, *args, **kwargs):
        self.set_state("restarting")
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
        self.set_state("connecting", "busy")
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
            if attempt > self.time_to_connect:
                # Set the state to unknown.
                self.set_state("unknown", "unknown")
                raise Exception("The kernel took too long to connect to the ZMQ sockets.")
            # Wait a second until the next time we try again.
            await asyncio.sleep(1)
        # Send an initial kernel info request on the shell channel.
        self.main_client.kernel_info()
        self.set_state("connected")
        
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
            
    def execution_state_listener(self, channel_name, msg):
        """Set the execution state by watching messages returned by the shell channel."""
        # Only continue if we're on the IOPub where the status is published.
        if channel_name != "iopub":
            return
        session = self.main_client.session        
        _, smsg = session.feed_identities(msg)
        # Unpack the message 
        deserialized_msg = session.deserialize(smsg, content=False)
        if deserialized_msg["msg_type"] == "status":
            content = session.unpack(deserialized_msg["content"])
            status = content["execution_state"]
            if status == "starting":
                # Don't broadcast, since this message is already going out.
                self.set_state("starting", status, broadcast=False)
            else:
                parent = deserialized_msg.get("parent_header", {})
                msg_id = parent.get("msg_id", "")
                parent_channel = self.main_client.message_source_cache.get(msg_id, None)
                if parent_channel and parent_channel == "shell":
                    # Don't broadcast, since this message is already going out.
                    self.set_state("connected", status, broadcast=False)
            