import json
from collections import OrderedDict
from traitlets import Dict, Instance, Int
from traitlets.config import LoggingConfigurable


class MissingKeyException(Exception):
    """An exception when a dictionary is missing a required key."""

class InvalidKeyException(Exception):
    """An exception when the key doesn't match msg_id property in value"""


class KernelMessageCache(LoggingConfigurable):
    """
    A cache for storing kernel messages, optimized for access by message ID and cell ID.

    The cache uses an OrderedDict for message IDs to maintain insertion order and
    implement LRU eviction.  Messages are also indexed by cell ID for faster
    retrieval when the cell ID is known.

    Attributes:
        _by_cell_id (dict):  A dictionary mapping cell IDs to message data.
        _by_msg_id (OrderedDict): An OrderedDict mapping message IDs to message data,
                                 maintaining insertion order for LRU eviction.
        maxsize (int): The maximum number of messages to store in the cache.
    """

    _by_cell_id = Dict({})
    _by_msg_id = Instance(OrderedDict, default_value=OrderedDict())
    maxsize = Int(default_value=10000).tag(config=True)


    def __repr__(self):
        """
        Returns a JSON string representation of the message ID cache.
        """
        return json.dumps(self._by_msg_id, indent=2)

    def __getitem__(self, msg_id):
        """
        Retrieves a message from the cache by message ID.  Moves the accessed
        message to the end of the OrderedDict to update its access time.

        Args:
            msg_id (str): The message ID.

        Returns:
            dict: The message data.

        Raises:
            KeyError: If the message ID is not found in the cache.
        """
        out = self._by_msg_id[msg_id]
        self._by_msg_id.move_to_end(msg_id)
        return out

    def __setitem__(self, msg_id, value):
        """
        Adds a message to the cache.  If the cache is full, the least recently
        used message is evicted.

        Args:
            msg_id (str): The message ID.
            value (dict): The message data.

        Raises:
            Exception: If the msg_id does not match the message ID in the value,
                       or if the message data is missing required fields
                       ("msg_id", "channel").
        """
        if "msg_id" not in value:
            raise MissingKeyException("`msg_id` missing in message data")

        if "channel" not in value:
            raise MissingKeyException("`channel` missing in message data")
        
        if value["msg_id"] != msg_id:
            raise InvalidKeyException("Key must match `msg_id` in value")

        # Remove the existing msg_id if a new msg with same cell_id exists
        if value["channel"] == "shell" and "cell_id" in value and value["cell_id"] in self._by_cell_id:
            existing_msg_id = self._by_cell_id[value["cell_id"]]["msg_id"]
            if msg_id != existing_msg_id:
                del self._by_msg_id[existing_msg_id]
        
        if "cell_id" in value and value['cell_id'] is not None:
            self._by_cell_id[value['cell_id']] = value

        self._by_msg_id[msg_id] = value
        if len(self._by_msg_id) > self.maxsize:
            self._remove_oldest()

    def _remove_oldest(self):
        """
        Removes the least recently used message from the cache.
        """
        try:
            key, item = self._by_msg_id.popitem(last=False)
            if 'cell_id' in item:  # Check if 'cell_id' key exists
                try:
                    del self._by_cell_id[item['cell_id']]
                except KeyError:
                    pass  # Handle the case where the cell_id is not present
        except KeyError:
            pass  # Handle the case where the cache is empty

    def __delitem__(self, msg_id):
        """
        Removes a message from the cache by message ID.

        Args:
            msg_id (str): The message ID.
        """
        msg_data = self._by_msg_id[msg_id]
        try:
            cell_id = msg_data["cell_id"]
            del self._by_cell_id[cell_id]
        except KeyError:
            pass
        del self._by_msg_id[msg_id]

    def __contains__(self, msg_id):
        """
        Checks if a message with the given message ID is in the cache.

        Args:
            msg_id (str): The message ID.

        Returns:
            bool: True if the message is in the cache, False otherwise.
        """
        return msg_id in self._by_msg_id

    def __iter__(self):
        """
        Returns an iterator over the message IDs in the cache.
        """
        for msg_id in self._by_msg_id:
            yield msg_id

    def __len__(self):
        """
        Returns the number of messages in the cache.
        """
        return len(self._by_msg_id)

    def add(self, data):
        """
        Adds a message to the cache using its message ID as the key.

        Args:
            data (dict): The message data.
        """
        self[data['msg_id']] = data

    def get(self, msg_id=None, cell_id=None):
        """
        Retrieves a message from the cache, either by message ID or cell ID.

        Args:
            msg_id (str, optional): The message ID. Defaults to None.
            cell_id (str, optional): The cell ID. Defaults to None.

        Returns:
            dict: The message data, or None if not found.
        """
        try:
            out = self._by_cell_id[cell_id]
            msg_id = out['msg_id']
            self._by_msg_id.move_to_end(msg_id)
            return out
        except KeyError:
            try:
                out = self._by_msg_id[msg_id]
                self._by_msg_id.move_to_end(msg_id)
                return out
            except KeyError:
                return None

    def remove(self, msg_id=None, cell_id=None):
        """
        Removes a message from the cache, either by message ID or cell ID.

        Args:
            msg_id (str, optional): The message ID. Defaults to None.
            cell_id (str, optional): The cell ID. Defaults to None.
        """
        try:
            out = self._by_cell_id[cell_id]
            msg_id = out['msg_id']
            del self._by_msg_id[msg_id]
            del self._by_cell_id[cell_id]
        except KeyError:
            try:
                out = self._by_msg_id[msg_id]
                try:
                    cell_id = out['cell_id']
                    del self._by_cell_id[cell_id]
                except KeyError:
                    pass
                finally:
                    del self._by_msg_id[msg_id]
            except KeyError:
                return

    def pop(self, msg_id=None, cell_id=None):
        """
        Removes and returns a message from the cache, either by message ID or cell ID.

        Args:
            msg_id (str, optional): The message ID. Defaults to None.
            cell_id (str, optional): The cell ID. Defaults to None.

        Returns:
            dict: The message data.

        Raises:
            KeyError: If the message ID or cell ID is not found.
        """
        try:
            out = self._by_cell_id[cell_id]
        except KeyError:
            out = self._by_msg_id[msg_id]
        self.remove(msg_id=out['msg_id'])
        return out