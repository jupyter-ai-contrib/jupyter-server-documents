from jupyter_server.services.kernels.kernelmanager import AsyncMappingKernelManager


class NextGenMappingKernelManager(AsyncMappingKernelManager):
    
    def start_watching_activity(self, kernel_id):
        pass
    
    def stop_buffering(self, kernel_id):
        pass

    # NOTE: Since we disable watching activity and buffering here, 
    # this method needs to be forked and remove code related to these things. 
    async def restart_kernel(self, kernel_id, now=False):
        """Restart a kernel by kernel_id"""
        self._check_kernel_id(kernel_id)
        await self.pinned_superclass._async_restart_kernel(self, kernel_id, now=now)