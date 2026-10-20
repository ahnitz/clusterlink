"""CI must not silently omit platform-dependent native tests."""
import sys
import unittest

result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.discover(sys.argv[1]))
if result.skipped:
    print('Required tests skipped:', result.skipped, file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
