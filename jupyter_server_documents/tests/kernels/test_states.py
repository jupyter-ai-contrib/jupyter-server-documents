import pytest

from jupyter_server_documents.kernels.states import LifecycleStates, ExecutionStates, StrContainerEnum, StrContainerEnumMeta


class TestStrContainerEnumMeta:
    """Test cases for StrContainerEnumMeta."""

    def test_contains_by_name(self):
        """Test that enum names are found with 'in' operator."""
        assert "IDLE" in ExecutionStates
        assert "STARTED" in LifecycleStates

    def test_contains_by_value(self):
        """Test that enum values are found with 'in' operator."""
        assert "idle" in ExecutionStates
        assert "started" in LifecycleStates

    def test_contains_missing(self):
        """Test that missing items are not found."""
        assert "MISSING" not in ExecutionStates
        assert "missing" not in LifecycleStates


class TestStrContainerEnum:
    """Test cases for StrContainerEnum base class."""

    def test_is_string_subclass(self):
        """Test that StrContainerEnum is a string subclass."""
        assert issubclass(StrContainerEnum, str)

    def test_enum_value_is_string(self):
        """Test that enum values can be used as strings."""
        idle_state = ExecutionStates.IDLE
        assert isinstance(idle_state, str)
        assert idle_state == "idle"
        assert idle_state.upper() == "IDLE"


class TestLifecycleStates:
    """Test cases for LifecycleStates enum."""

    def test_all_states_defined(self):
        """Test that all expected lifecycle states are defined."""
        expected_states = [
            "UNKNOWN", "STARTING", "STARTED", "TERMINATING", "CONNECTING",
            "CONNECTED", "RESTARTING", "RECONNECTING", "CULLED", 
            "DISCONNECTED", "TERMINATED", "DEAD"
        ]
        
        for state in expected_states:
            assert hasattr(LifecycleStates, state)

    def test_state_values(self):
        """Test that state values are lowercase versions of names."""
        assert LifecycleStates.UNKNOWN.value == "unknown"
        assert LifecycleStates.STARTING.value == "starting"
        assert LifecycleStates.STARTED.value == "started"
        assert LifecycleStates.TERMINATING.value == "terminating"
        assert LifecycleStates.CONNECTING.value == "connecting"
        assert LifecycleStates.CONNECTED.value == "connected"
        assert LifecycleStates.RESTARTING.value == "restarting"
        assert LifecycleStates.RECONNECTING.value == "reconnecting"
        assert LifecycleStates.CULLED.value == "culled"
        assert LifecycleStates.DISCONNECTED.value == "disconnected"
        assert LifecycleStates.TERMINATED.value == "terminated"
        assert LifecycleStates.DEAD.value == "dead"

    def test_state_equality(self):
        """Test that states can be compared by value."""
        assert LifecycleStates.UNKNOWN == "unknown"
        assert LifecycleStates.STARTING == "starting"
        assert LifecycleStates.CONNECTED == "connected"

    def test_state_membership(self):
        """Test state membership using 'in' operator."""
        assert "starting" in LifecycleStates
        assert "STARTING" in LifecycleStates
        assert "connected" in LifecycleStates
        assert "CONNECTED" in LifecycleStates
        assert "invalid_state" not in LifecycleStates

    def test_state_iteration(self):
        """Test iterating over lifecycle states."""
        states = list(LifecycleStates)
        assert len(states) == 12  # Total number of defined states
        assert LifecycleStates.UNKNOWN in states
        assert LifecycleStates.DEAD in states


class TestExecutionStates:
    """Test cases for ExecutionStates enum."""

    def test_all_states_defined(self):
        """Test that all expected execution states are defined."""
        expected_states = ["BUSY", "IDLE", "STARTING", "UNKNOWN", "DEAD"]
        
        for state in expected_states:
            assert hasattr(ExecutionStates, state)

    def test_state_values(self):
        """Test that state values are lowercase versions of names."""
        assert ExecutionStates.BUSY.value == "busy"
        assert ExecutionStates.IDLE.value == "idle"
        assert ExecutionStates.STARTING.value == "starting"
        assert ExecutionStates.UNKNOWN.value == "unknown"
        assert ExecutionStates.DEAD.value == "dead"

    def test_state_equality(self):
        """Test that states can be compared by value."""
        assert ExecutionStates.BUSY == "busy"
        assert ExecutionStates.IDLE == "idle"
        assert ExecutionStates.STARTING == "starting"
        assert ExecutionStates.UNKNOWN == "unknown"
        assert ExecutionStates.DEAD == "dead"

    def test_state_membership(self):
        """Test state membership using 'in' operator."""
        assert "busy" in ExecutionStates
        assert "BUSY" in ExecutionStates
        assert "idle" in ExecutionStates
        assert "IDLE" in ExecutionStates
        assert "invalid_state" not in ExecutionStates

    def test_state_iteration(self):
        """Test iterating over execution states."""
        states = list(ExecutionStates)
        assert len(states) == 5  # Total number of defined states
        assert ExecutionStates.BUSY in states
        assert ExecutionStates.IDLE in states

    def test_state_string_operations(self):
        """Test that states can be used in string operations."""
        busy_state = ExecutionStates.BUSY
        assert busy_state.upper() == "BUSY"
        assert busy_state.capitalize() == "Busy"
        assert len(busy_state) == 4
        assert busy_state.startswith("b")


class TestEnumIntegration:
    """Integration tests for both enums."""

    def test_enum_types_are_different(self):
        """Test that the two enum types are distinct."""
        # Since both are StrContainerEnum subclasses, they compare as equal strings
        # but they are different types
        assert type(LifecycleStates.STARTING) != type(ExecutionStates.STARTING)
        assert LifecycleStates.STARTING is not ExecutionStates.STARTING

    def test_enum_values_can_be_same(self):
        """Test that enum values can be the same string."""
        # Both have "starting", "unknown", "dead" values
        assert LifecycleStates.STARTING.value == ExecutionStates.STARTING.value == "starting"
        assert LifecycleStates.UNKNOWN.value == ExecutionStates.UNKNOWN.value == "unknown"
        assert LifecycleStates.DEAD.value == ExecutionStates.DEAD.value == "dead"

    def test_enum_members_are_unique_within_enum(self):
        """Test that enum members are unique within their enum."""
        lifecycle_values = [state.value for state in LifecycleStates]
        execution_values = [state.value for state in ExecutionStates]
        
        # Check for uniqueness within each enum
        assert len(lifecycle_values) == len(set(lifecycle_values))
        assert len(execution_values) == len(set(execution_values))

    def test_enum_membership_is_type_specific(self):
        """Test that membership checks are type-specific."""
        # "idle" is in ExecutionStates but not in LifecycleStates
        assert "idle" in ExecutionStates
        assert "idle" not in LifecycleStates
        
        # "connected" is in LifecycleStates but not in ExecutionStates
        assert "connected" in LifecycleStates
        assert "connected" not in ExecutionStates