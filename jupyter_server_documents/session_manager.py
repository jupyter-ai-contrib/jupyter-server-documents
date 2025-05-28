import os
from typing import Optional, Any
from jupyter_server.services.sessions.sessionmanager import SessionManager, KernelName, ModelName
from jupyter_server.serverapp import ServerApp
from jupyter_server_fileid.manager import BaseFileIdManager
from jupyter_server_documents.rooms.yroom_manager import YRoomManager
from jupyter_server_documents.rooms.yroom import YRoom
from jupyter_server_documents.kernels.kernel_client import DocumentAwareKernelClient


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

    def get_kernel_client(self, kernel_id) -> DocumentAwareKernelClient:
        """Get the kernel client for a running kernel."""
        kernel_manager = self.kernel_manager.get_kernel(kernel_id)
        kernel_client = kernel_manager.main_client
        return kernel_client

    # The `type` argument here is for future proofing this API. 
    # Today, only notebooks have ydocs with kernels connected. 
    # In the future, we will include consoles here.
    def get_yroom(self, path, type) -> YRoom:
        """Get the yroom for a given path."""
        file_id = self.file_id_manager.index(path)
        room_id = f"json:notebook:{file_id}"
        yroom = self.yroom_manager.get_room(room_id)
        return yroom

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
        """
        output = await super().create_session(
            path,
            name,
            type,
            kernel_name,
            kernel_id
        )
        if kernel_id is None:
            kernel_id = output["kernel"]["id"]

        # Connect this session's yroom to the kernel.
        if type == "notebook":
            # If name or path is None, we cannot map to a yroom,
            # so just move on.
            if name is None or path is None:
                self.log.debug("`name` or `path` was not given, so a yroom was not set up for this session.")
                return output
            # When JupyterLab creates a session, it uses a fake path
            # which is the relative path + UUID, i.e. the notebook
            # name is incorrect temporarily. It later makes multiple
            # updates to the session to correct the path.
            # 
            # Here, we create the true path to store in the fileID service
            # by dropping the UUID and appending the file name.
            real_path = os.path.join(os.path.split(path)[0], name)
            yroom = self.get_yroom(real_path, type)
            # TODO: we likely have a race condition here... need to 
            # think about it more. Currently, the kernel client gets
            # created after the kernel starts fully. We need the 
            # kernel client instantiated _before_ trying to connect
            # the yroom.
            kernel_client = self.get_kernel_client(kernel_id)
            await kernel_client.add_yroom(yroom)
            self.log.info(f"Connected yroom {yroom.room_id} to kernel {kernel_id}. yroom: {yroom}")
        else:
            self.log.debug(f"Document type {type} is not supported by YRoom.")
        return output
    
    async def delete_session(self, session_id):
        """
        Deletes the session and disconnects the yroom from the kernel client.
        """
        session = await self.get_session(session_id=session_id)
        kernel_id, path, type = session["kernel"]["id"], session["path"], session["type"]
        yroom = self.get_yroom(path, type)
        kernel_client = self.get_kernel_client(kernel_id)
        await kernel_client.remove_yroom(yroom)
        await super().delete_session(session_id)