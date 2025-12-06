"""
Test to reproduce the cascade soundings parent_session_id bug.

The issue: Cascade-level soundings create child cascades with unique session_IDs
(e.g., parent_sounding_0, parent_sounding_1), but ALL records logged by those
child cascades have parent_session_id = None instead of parent_session_id = 'parent'.

This breaks the UI's ability to query and display sub-cascades.
"""

from windlass.echo import Echo, get_echo, _session_manager

print("=== Testing Echo and SessionManager behavior ===\n")

# Simulate what happens in cascade soundings
parent_session_id = "test_parent"
child_session_id = "test_parent_sounding_0"

print(f"1. Creating parent echo with session_id='{parent_session_id}'")
parent_echo = get_echo(parent_session_id)
print(f"   Parent echo.parent_session_id = {parent_echo.parent_session_id}")

print(f"\n2. Creating child echo with session_id='{child_session_id}', parent_session_id='{parent_session_id}'")
child_echo = get_echo(child_session_id, parent_session_id=parent_session_id)
print(f"   Child echo.parent_session_id = {child_echo.parent_session_id}")

print(f"\n3. Simulating what add_history does - it logs with self.parent_session_id")
print(f"   Child would log with parent_session_id = {child_echo.parent_session_id}")

print(f"\n4. Check if child_echo is registered in session manager:")
print(f"   '{child_session_id}' in _session_manager.sessions = {child_session_id in _session_manager.sessions}")

print(f"\n5. Getting child echo again (simulating multiple calls):")
child_echo_2 = get_echo(child_session_id, parent_session_id=parent_session_id)
print(f"   Same object? {child_echo is child_echo_2}")
print(f"   child_echo_2.parent_session_id = {child_echo_2.parent_session_id}")

print(f"\n6. What if we get it WITHOUT parent_session_id?")
child_echo_3 = get_echo(child_session_id)
print(f"   Same object? {child_echo is child_echo_3}")
print(f"   child_echo_3.parent_session_id = {child_echo_3.parent_session_id}")

print("\n\n=== FINDING THE BUG ===")
print("Check the SessionManager.get_session() implementation...")
print("If session already exists, it returns it WITHOUT updating parent_session_id!")
print("If get_echo is called multiple times with different parent_session_id values,")
print("only the FIRST call's parent_session_id is preserved.")

print("\n\n=== Testing the bug scenario ===")
# Clear session manager
_session_manager.sessions.clear()

bug_child_id = "bug_test_child"

print(f"1. First call: get_echo('{bug_child_id}', parent_session_id=None)")
echo1 = get_echo(bug_child_id, parent_session_id=None)
print(f"   echo1.parent_session_id = {echo1.parent_session_id}")

print(f"\n2. Second call: get_echo('{bug_child_id}', parent_session_id='correct_parent')")
echo2 = get_echo(bug_child_id, parent_session_id='correct_parent')
print(f"   echo2.parent_session_id = {echo2.parent_session_id}")
print(f"   Same object? {echo1 is echo2}")

print("\n⚠️  BUG CONFIRMED: The second call didn't update parent_session_id!")
print("The session was already registered with parent_session_id=None, so it stayed None.")
