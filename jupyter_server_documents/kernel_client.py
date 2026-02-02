"""Document-aware kernel client for collaborative notebook editing.

This module extends nextgen-kernels-api's JupyterServerKernelClient to add
notebook-specific functionality required for real-time collaboration:

- Routes kernel messages to collaborative YRooms for document state synchronization
- Processes and separates large outputs to optimize document size
- Tracks cell execution states and updates awareness for real-time UI feedback
- Manages notebook metadata updates from kernel info
"""
from nextgen_kernels_api.services.kernels.client import JupyterServerKernelClient

from jupyter_server_documents.document_aware_mixin import DocumentAwareMixin


class DocumentAwareKernelClient(DocumentAwareMixin, JupyterServerKernelClient):
    """Kernel client with collaborative document awareness and output processing.

    Extends the base JupyterServerKernelClient to integrate with YRooms for
    real-time collaboration, process outputs for optimization, and track cell
    execution states across connected clients.

    This class combines:
    - JupyterServerKernelClient: Base kernel client with message handling
    - DocumentAwareMixin: YRoom integration, output processing, cell state tracking
    """

    def __init__(self, *args, **kwargs):
        """Initialize the document-aware kernel client."""
        super().__init__(*args, **kwargs)
        # Initialize document-aware functionality from mixin
        self._init_document_aware_mixin()
