from __future__ import annotations

import pytest


@pytest.fixture
def risky_python_diff() -> str:
    return """diff --git a/app/demo.py b/app/demo.py
index 1111111..2222222 100644
--- a/app/demo.py
+++ b/app/demo.py
@@ -1,2 +1,6 @@
 def handler(user):
+    query = f"SELECT * FROM users WHERE name = '{user}'"
+    # TODO tighten auth
+    try:
+        pass
+    except Exception:
     return user
"""
