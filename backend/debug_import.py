
import sys
import os

# Add backend to path
sys.path.insert(0, os.getcwd())

try:
    print("Attempting to import app.main...")
    import app.main
    print("Successfully imported app.main")
except Exception as e:
    print(f"Failed to import app.main: {e}")
    import traceback
    traceback.print_exc()

try:
    print("Attempting to import app.api.suggestions...")
    import app.api.suggestions
    print("Successfully imported app.api.suggestions")
except Exception as e:
    print(f"Failed to import app.api.suggestions: {e}")
    import traceback
    traceback.print_exc()
