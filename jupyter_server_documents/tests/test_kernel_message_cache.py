import pytest
from collections import OrderedDict
from jupyter_server_documents.kernels.message_cache import InvalidKeyException, KernelMessageCache, MissingKeyException  # Replace your_module


def create_cache(maxsize=None):
    if maxsize:
        cache = KernelMessageCache(maxsize=maxsize)
    else:
        cache = KernelMessageCache()
    
    # somehow the same cache is shared in the tests
    # clearing the cache so tests pass
    cache._by_msg_id.clear() 
    return cache


def create_message(msg_id, channel, cell_id=None, content="test content"):
    message = {
        "msg_id": msg_id,
        "channel": channel,
        "content": content,
    }
    if cell_id:
        message["cell_id"] = cell_id
    return message


def test_setitem_and_getitem():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache["msg1"] = message1
    assert cache["msg1"] == message1


def test_setitem_key_mismatch():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    with pytest.raises(InvalidKeyException, match="Key must match `msg_id` in value"):
        cache["wrong_key"] = message1


def test_setitem_missing_msg_id():
    cache = create_cache()
    message1 = {"channel": "shell"}  # Missing msg_id
    with pytest.raises(MissingKeyException, match="`msg_id` missing in message data"):
        cache["key"] = message1


def test_setitem_missing_channel():
    cache = create_cache()
    message1 = {"msg_id": "msg1"}  # Missing channel
    with pytest.raises(MissingKeyException, match="`channel` missing in message data"):
        cache["msg1"] = message1


def test_setitem_with_cell_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell", "cell1")
    cache["msg1"] = message1
    assert cache._by_cell_id["cell1"] == message1
    assert "msg1" in cache._by_msg_id


def test_setitem_without_cell_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache["msg1"] = message1
    assert "msg1" in cache._by_msg_id
    assert not cache._by_cell_id


def test_delitem():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache["msg1"] = message1
    del cache["msg1"]
    assert "msg1" not in cache
    assert "msg1" not in cache._by_msg_id


def test_delitem_with_cell_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell", "cell1")
    cache["msg1"] = message1
    del cache["msg1"]
    assert "msg1" not in cache
    assert "cell1" not in cache._by_cell_id
    assert "msg1" not in cache._by_msg_id


def test_contains():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache["msg1"] = message1
    assert "msg1" in cache
    assert "nonexistent_key" not in cache


def test_iter():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    message2 = create_message("msg2", "shell")
    cache["msg1"] = message1
    cache["msg2"] = message2
    keys = list(cache)
    assert "msg1" in keys
    assert "msg2" in keys
    assert len(keys) == 2


def test_len():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    message2 = create_message("msg2", "shell")
    cache["msg1"] = message1
    cache["msg2"] = message2
    assert len(cache) == 2


def test_add():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache.add(message1)
    assert cache["msg1"] == message1
    assert "msg1" in cache._by_msg_id


def test_get_by_msg_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache["msg1"] = message1
    retrieved_message = cache.get(msg_id="msg1")
    assert retrieved_message == message1
    assert isinstance(cache._by_msg_id, OrderedDict)  # Check it's still OrderedDict


def test_get_by_cell_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell", "cell1")
    cache["msg1"] = message1
    retrieved_message = cache.get(cell_id="cell1")
    assert retrieved_message == message1
    assert isinstance(cache._by_msg_id, OrderedDict)  # Check it's still OrderedDict


def test_get_not_found():
    cache = create_cache()
    retrieved_message = cache.get(msg_id="nonexistent_key")
    assert retrieved_message is None


def test_remove_by_msg_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache["msg1"] = message1
    cache.remove(msg_id="msg1")
    assert "msg1" not in cache
    assert "msg1" not in cache._by_msg_id


def test_remove_by_cell_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell", "cell1")
    cache["msg1"] = message1
    cache.remove(cell_id="cell1")
    assert "msg1" not in cache
    assert "cell1" not in cache._by_cell_id
    assert "msg1" not in cache._by_msg_id


def test_remove_nonexistent():
    cache = create_cache()
    cache.remove(msg_id="nonexistent_key")  # Should not raise an error
    cache.remove(cell_id="nonexistent_cell")  # Should not raise an error


def test_pop_by_msg_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache["msg1"] = message1
    popped_message = cache.pop(msg_id="msg1")
    assert popped_message == message1
    assert "msg1" not in cache
    assert "msg1" not in cache._by_msg_id


def test_pop_by_cell_id():
    cache = create_cache()
    message1 = create_message("msg1", "shell", "cell1")
    cache["msg1"] = message1
    popped_message = cache.pop(cell_id="cell1")
    assert popped_message == message1
    assert "msg1" not in cache
    assert "cell1" not in cache._by_cell_id
    assert "msg1" not in cache._by_msg_id


def test_pop_nonexistent():
    cache = create_cache()
    with pytest.raises(KeyError):
        cache.pop(msg_id="nonexistent_key")


def test_repr():
    cache = create_cache()
    message1 = create_message("msg1", "shell")
    cache["msg1"] = message1
    representation = repr(cache)
    assert '"msg1":' in representation
    assert '"channel": "shell"' in representation


def test_lru_behavior():
    cache = create_cache()
    cache._by_msg_id = OrderedDict()  # Reset to OrderedDict for LRU test
    cache._by_msg_id["msg1"] = create_message("msg1", "shell")
    cache._by_msg_id["msg2"] = create_message("msg2", "shell")
    cache._by_msg_id["msg3"] = create_message("msg3", "shell")

    # Access "msg1" to make it the most recently used
    cache["msg1"]

    # Check the order after accessing
    expected_order = ["msg2", "msg3", "msg1"]
    assert list(cache._by_msg_id.keys()) == expected_order


def test_maxsize_eviction():
    cache = create_cache(2)
    message1 = create_message("msg1", "shell")
    message2 = create_message("msg2", "shell")
    message3 = create_message("msg3", "shell")

    cache["msg1"] = message1
    cache["msg2"] = message2
    cache["msg3"] = message3  # This should evict "msg1"

    assert "msg1" not in cache
    assert "msg2" in cache
    assert "msg3" in cache
    assert len(cache) == 2


def test_remove_oldest():
    cache = create_cache()
    cache = KernelMessageCache(maxsize=2)
    message1 = create_message("msg1", "shell")
    message2 = create_message("msg2", "shell")
    message3 = create_message("msg3", "shell")
    cache["msg1"] = message1
    cache["msg2"] = message2
    cache["msg3"] = message3 # should trigger remove_oldest

    assert "msg1" not in cache
    assert "msg2" in cache
    assert "msg3" in cache

def test_maxsize_eviction_with_cell_id():
    cache = create_cache(2)
    message1 = create_message("msg1", "shell", "cell1")
    message2 = create_message("msg2", "shell", "cell2")
    message3 = create_message("msg3", "shell", "cell3")

    cache["msg1"] = message1
    cache["msg2"] = message2
    cache["msg3"] = message3  # This should evict "msg1"

    assert "msg1" not in cache
    assert "msg2" in cache
    assert "msg3" in cache
    assert "cell1" not in cache._by_cell_id
    assert "cell2" in cache._by_cell_id
    assert "cell3" in cache._by_cell_id

def test_existing_msg_id_is_removed():
    cache = create_cache()
    message1 = create_message("msg1", "shell", "cell1")
    message2 = create_message("msg2", "shell", "cell1")

    cache["msg1"] = message1
    cache["msg2"] = message2

    assert "msg1" not in cache
    assert message2 == cache["msg2"]