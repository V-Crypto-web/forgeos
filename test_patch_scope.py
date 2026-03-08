from forgeos.verification.patch_scope_analyzer import ScopeAnalyzer, PatchScopeClass

analyzer = ScopeAnalyzer()

narrow_patch = """
--- a/file1.py
+++ b/file1.py
@@ -1,3 +1,4 @@
 def existing():
-    return 1
+    return 2
+    # comment
"""

res = analyzer.evaluate_patch(narrow_patch, risk_profile="low")
print("NARROW PATCH:", res.scope_class.name, "| Rejected:", res.is_rejected)

wide_patch_structural = """
--- a/file1.py
+++ b/file1.py
@@ -1,3 +1,4 @@
+import requests
 def existing():
     pass
--- a/file2.py
+++ b/file2.py
@@ -1,3 +1,4 @@
+class NewFeature:
+    pass
"""

res = analyzer.evaluate_patch(wide_patch_structural, risk_profile="low")
print("WIDE STRUCTURAL PATCH:", res.scope_class.name, "| Rejected:", res.is_rejected, "| Reason:", res.rejection_reason)

huge_patch = """
--- a/file1.py
+++ b/file1.py
""" + "+    pass\n" * 200

res = analyzer.evaluate_patch(huge_patch, risk_profile="medium")
print("HUGE PATCH:", res.scope_class.name, "| Rejected:", res.is_rejected, "| Reason:", res.rejection_reason)
