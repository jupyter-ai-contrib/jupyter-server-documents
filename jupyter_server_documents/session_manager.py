import os
from typing import Optional, Any
from jupyter_server.services.sessions.sessionmanager import SessionManager, KernelName, ModelName
from jupyter_server.serverapp import ServerApp
from jupyter_server_fileid.manager import BaseFileIdManager
from jupyter_server_documents.rooms.yroom_manager import YRoomManager
from jupyter_server_documents.rooms.yroom import YRoom
from jupyter_server_documents.kernel_client import DocumentAwareKernelClient


class YDocSessionManager(SessionManager): 
    """A Jupyter Server Session Manager that connects YDocuments
    to Kernel Clients.
    """
    
    @property
    def serverapp(self) -> ServerApp:
        """When running in Jupyter Server, the parent 
        of this class is an instance of the ServerApp.
        """
        return self.parent
    
    @property
    def file_id_manager(self) -> BaseFileIdManager:
        """The Jupyter Server's File ID Manager."""
        return self.serverapp.web_app.settings["file_id_manager"]
    
    @property
    def yroom_manager(self) -> YRoomManager:
        """The Jupyter Server's YRoom Manager."""
        return self.serverapp.web_app.settings["yroom_manager"]

    _room_ids: dict[str, str]
    """
    Dictionary of room IDs, keyed by session ID.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._room_ids = {}

    def _ensure_real_path(self, path, name):
        """
        When JupyterLab creates a session, it uses a fake path
        which is the relative path + UUID, i.e. the notebook
        name is incorrect temporarily. It later makes multiple
        updates to the session to correct the path.
        
        Here, we create the true path to store in the fileID service
        by dropping the UUID and appending the file name.
        """
        return os.path.join(os.path.split(path)[0], name)

    def get_yroom(self, session_id: str) -> YRoom:
        """
        Get the `YRoom` for a session given its ID. The session must have
        been created first via a call to `create_session()`.
        """
        room_id = self._room_ids.get(session_id, None)
        yroom = self.yroom_manager.get_room(room_id) if room_id else None
        if not yroom:
            raise LookupError(f"No room found for session '{session_id}'.")
        return yroom

    def _init_session_yroom(self, session_id: str, path: str) -> YRoom:
        """
        Returns a `YRoom` for a session identified by the given `session_id` and
        `path`. This should be called only in `create_session()`.

        This method stores the new room ID & session ID in `self._room_ids`. The
        `YRoom` for a session can be retrieved via `self.get_yroom()` after this
        method is called.
        """
        file_id = self.file_id_manager.index(path)
        room_id = f"json:notebook:{file_id}"
        yroom = self.yroom_manager.get_room(room_id)
        self._room_ids[session_id] = room_id
        return yroom

    async def _ensure_yroom_connected(self, session_id: str, kernel_id: str) -> None:
        """
        Ensures that a session's yroom is connected to its kernel client.

        This method is critical for maintaining the connection between collaborative
        document state (yroom) and kernel execution state. It handles scenarios where
        the yroom-kernel connection may have been lost, such as:

        - Server restarts where sessions persist but in-memory connections are lost
        - Remote/persistent kernels that survive across server lifecycles
        - Recovery from transient failures or race conditions during session setup

        The method is idempotent - it checks if the yroom is already connected before
        attempting to add it, preventing duplicate connections.

        Args:
            session_id: The unique identifier for the session
            kernel_id: The unique identifier for the kernel

        Note:
            This method silently handles cases where the yroom or kernel don't exist,
            or where the session has no associated yroom. Failures are logged but
            don't raise exceptions.
        """
        # Check if this session has an associated yroom in the cache
        room_id = self._room_ids.get(session_id)

        # If not cached, populate it from the session's path
        # This handles persistent sessions that survive server restarts
        if not room_id:
            try:
                # Get the session from the database to find its path
                # Use super() to avoid infinite recursion since we're called from get_session
                session = await super().get_session(session_id=session_id)
                if session and session.get("type") == "notebook":
                    path = session.get("path")
                    name = session.get("name")
                    real_path = self._ensure_real_path(path, name)
                    if real_path:
                        # Use the same logic as _init_session_yroom to calculate room_id
                        file_id = self.file_id_manager.index(real_path)
                        room_id = f"json:notebook:{file_id}"
                        # Cache it for future calls
                        self._room_ids[session_id] = room_id
                        self.log.debug(f"Populated room_id {room_id} from session path for session {session_id}")
                    else:
                        self.log.debug(f"Session {session_id} has no path")
                        return
                else:
                    self.log.debug(f"Session {session_id} is not a notebook type")
                    return
            except Exception as e:
                self.log.warning(f"Failed to lookup session {session_id}: {e}")
                return

        if not room_id:
            # Session has no yroom (e.g., console session or non-notebook type)
            return

        # Get the yroom if it exists
        yroom = self.yroom_manager.get_room(room_id)
        if not yroom:
            # Room doesn't exist yet or was cleaned up
            return

        # Ensure the yroom is added to the kernel client
        try:
            kernel_manager = self.serverapp.kernel_manager.get_kernel(kernel_id)
            kernel_client = kernel_manager.kernel_client

            # Check if yroom is already connected to avoid duplicate connections
            if hasattr(kernel_client, '_yrooms') and yroom not in kernel_client._yrooms:
                await kernel_client.add_yroom(yroom)
                self.log.info(
                    f"Reconnected yroom {room_id} to kernel_client for session {session_id}. "
                    f"This ensures kernel messages are routed to the collaborative document."
                )
        except Exception as e:
            # Log but don't fail - the session is still valid even if yroom connection fails
            self.log.warning(
                f"Failed to connect yroom to kernel_client for session {session_id}: {e}"
            )

    async def get_session(self, **kwargs) -> Optional[dict[str, Any]]:
        """
        Retrieves a session and ensures the yroom-kernel connection is established.

        This override of the parent's get_session() adds a critical step: verifying
        and restoring the connection between the session's yroom (collaborative state)
        and its kernel client (execution engine).

        Why this matters:
        - When reconnecting to persistent/remote kernels, the in-memory yroom connection
          may not exist even though both the session and kernel are valid
        - Server restarts can break yroom-kernel connections while sessions persist
        - This ensures that every time a session is retrieved, it's fully functional
          for collaborative notebook editing and execution

        Args:
            **kwargs: Arguments passed to the parent's get_session() method
                     (e.g., session_id, path, kernel_id)

        Returns:
            The session model dict, or None if no session is found
        """
        session = await super().get_session(**kwargs)

        # If no session found, return None
        if session is None:
            return None

        # Extract session and kernel information
        session_id = session.get("id")
        kernel_info = session.get("kernel")

        # Only process sessions with valid kernel and session ID
        if not kernel_info or not session_id:
            return session

        kernel_id = kernel_info.get("id")
        if not kernel_id:
            return session

        # Ensure the yroom is connected to the kernel client
        # This is especially important for persistent kernels that survive server restarts
        await self._ensure_yroom_connected(session_id, kernel_id)

        return session


    async def create_session(
        self,
        path: Optional[str] = None,
        name: Optional[ModelName] = None,
        type: Optional[str] = None,
        kernel_name: Optional[KernelName] = None,
        kernel_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        After creating a session, connects the yroom to the kernel client.
        Sets kernel status to "starting" before kernel launch.
        """
        # For notebooks, set up the YRoom and set initial status before starting kernel
        
        should_setup_yroom = (
            type == "notebook" and
            name is not None and
            path is not None
        )

        yroom = None
        if should_setup_yroom:
            real_path = self._ensure_real_path(path, name)
            
            # Initialize the YRoom before starting the kernel
            file_id = self.file_id_manager.index(real_path)
            room_id = f"json:notebook:{file_id}"
            self.log.critical(f"{real_path}  {file_id}  {room_id}")

            yroom = self.yroom_manager.get_room(room_id)

            # Set initial kernel status to "starting" in awareness
            awareness = yroom.get_awareness()
            if awareness is not None:
                self.log.info("Setting kernel execution_state to 'starting' before kernel launch")
                awareness.set_local_state_field(
                    "kernel", {"execution_state": "starting"}
                )
        
        # Now create the session and start the kernel
        session_model = await super().create_session(
            path,
            name,
            type,
            kernel_name,
            kernel_id
        )
        session_id = session_model["id"]
        if kernel_id is None:
            kernel_id = session_model["kernel"]["id"]

        # If the type is not 'notebook', return the session model immediately
        if type != "notebook":
            self.log.warning(
                f"Document type '{type}' is not recognized by YDocSessionManager."
            )
            return session_model

        # If name or path is None, we cannot map to a yroom,
        # so just move on.
        if name is None or path is None:
            self.log.warning(f"`name` or `path` was not given for new session at '{path}'.")
            return session_model

        # Store the room ID for this session
        if yroom:
            self._room_ids[session_id] = yroom.room_id
        else:
            # Shouldn't happen, but handle it anyway
            real_path = os.path.join(os.path.split(path)[0], name)
            yroom = self._init_session_yroom(session_id, real_path)
        
        # Add YRoom to this session's kernel client
        # Ensure the kernel client is fully connected before proceeding
        # to avoid queuing messages on first execution
        kernel_manager = self.serverapp.kernel_manager.get_kernel(kernel_id)
        kernel_client = kernel_manager.kernel_client
        await kernel_client.add_yroom(yroom)
        self.log.info(f"Connected yroom {yroom.room_id} to kernel {kernel_id}. yroom: {yroom}")
        return session_model
    
    async def update_session(self, session_id: str, **update) -> None:
        """
        Updates the session identified by `session_id` using the keyword
        arguments passed to this method. Each keyword argument should correspond
        to a column in the sessions table.

        This class calls the `update_session()` parent method, then updates the
        kernel client if `update` contains `kernel_id`.
        """
        # Apply update and return early if `kernel_id` was not updated
        if "kernel_id" not in update:
            return await super().update_session(session_id, **update)
        
        # Otherwise, first remove the YRoom from the old kernel client and add
        # the YRoom to the new kernel client, before applying the update.
        old_session_info = (await self.get_session(session_id=session_id) or {})
        old_kernel_id = old_session_info.get("kernel_id", None)
        new_kernel_id = update.get("kernel_id", None)
        self.log.info(
            f"Updating session '{session_id}' from kernel '{old_kernel_id}' "
            f"to kernel '{new_kernel_id}'."
        )
        yroom = self.get_yroom(session_id)
        if old_kernel_id:
            old_kernel_manager = self.serverapp.kernel_manager.get_kernel(old_kernel_id)
            old_kernel_client = old_kernel_manager.kernel_client
            await old_kernel_client.remove_yroom(yroom=yroom)
        if new_kernel_id:
            new_kernel_manager = self.serverapp.kernel_manager.get_kernel(new_kernel_id)
            new_kernel_client = new_kernel_manager.kernel_client
            await new_kernel_client.add_yroom(yroom=yroom)

        # Apply update and return
        return await super().update_session(session_id, **update)
    
    
    async def delete_session(self, session_id):
        """
        Deletes the session and disconnects the yroom from the kernel client.
        """
        session = await self.get_session(session_id=session_id)
        kernel_id = session["kernel"]["id"]

        # Remove YRoom from session's kernel client
        yroom = self.get_yroom(session_id)
        kernel_manager = self.serverapp.kernel_manager.get_kernel(kernel_id)
        kernel_client = kernel_manager.kernel_client
        await kernel_client.remove_yroom(yroom)

        # Remove room ID stored for the session
        self._room_ids.pop(session_id, None)

        # Delete the session via the parent method
        await super().delete_session(session_id)