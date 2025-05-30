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
        "jupyter_server_documents.kernels.kernel_client.DocumentAwareKernelClient"
    )
    
    client_factory: Type = Type(klass="jupyter_server_documents.kernels.kernel_client.DocumentAwareKernelClient")

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
    
    def set_state(
        self, 
        lifecycle_state: LifecycleStates = None, 
        execution_state: ExecutionStates = None,
    ):
        if lifecycle_state:
            self.lifecycle_state = lifecycle_state.value
        if execution_state:
            self.execution_state = execution_state.value

    async def start_kernel(self, *args, **kwargs):
        self.set_state(LifecycleStates.STARTING, ExecutionStates.STARTING)
        out = await super().start_kernel(*args, **kwargs)
        self.set_state(LifecycleStates.STARTED)
        # Schedule the kernel to connect.
        # Do not await here, since many clients expect
        # the server to complete the start flow even
        # if the kernel is not fully connected yet.
        task = asyncio.create_task(self.connect())
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
        # Use the new API for getting a client.
        self.main_client = self.client()
        # Track execution state by watching all messages that come through
        # the kernel client.
        self.main_client.add_listener(self.execution_state_listener)
        self.set_state(LifecycleStates.CONNECTING, ExecutionStates.STARTING)
        await self.broadcast_state()
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
            await asyncio.sleep(0.5)
        # Wait for the kernel to reach an idle state.
        while self.execution_state != ExecutionStates.IDLE.value:
            self.main_client.send_kernel_info()
            await asyncio.sleep(0.1)
        
    async def disconnect(self):
        await self.main_client.stop_listening()
        self.main_client.stop_channels()

    async def broadcast_state(self):
        """Broadcast state to all listeners"""
        if not self.main_client:
            return 

        # Manufacture an IOPub status message from the shell channel.
        session = self.main_client.session
        parent_header = session.msg_header("status")
        parent_msg_id = parent_header["msg_id"]
        self.main_client.message_cache.add({
            "msg_id": parent_msg_id,
            "channel": "shell",
            "cellId": None
        })
        msg = session.msg("status", content={"execution_state": self.execution_state}, parent=parent_header)
        smsg = session.serialize(msg)[1:]
        await self.main_client.handle_outgoing_message("iopub", smsg)
            
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
                self.set_state(execution_state=ExecutionStates.STARTING)
            else:
                parent = deserialized_msg.get("parent_header", {})
                msg_id = parent.get("msg_id", "")
                message_data = self.main_client.message_cache.get(msg_id)
                if message_data is None:
                    return
                parent_channel = message_data.get("channel")
                if parent_channel and parent_channel == "shell":
                    self.set_state(LifecycleStates.CONNECTED, ExecutionStates(execution_state))