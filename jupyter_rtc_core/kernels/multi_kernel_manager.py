from jupyter_server.services.kernels.kernelmanager import AsyncMappingKernelManager


class NextGenMappingKernelManager(AsyncMappingKernelManager):
    
    def start_watching_activity(self, kernel_id):
        pass
    
    def stop_buffering(self, kernel_id):
        pass