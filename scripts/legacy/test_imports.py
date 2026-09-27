import sys
sys.path.insert(0, r'c:\Users\iig2y\Desktop\TONYAgent\src')

from tonyagent import providers, tools
print('Providers OK')
print('Tools:', tools.tool_registry.list_names())

from tonyagent.ui.views.main_window import MainWindow
print('MainWindow OK')

from tonyagent.sandbox import SandboxManager
print('SandboxManager OK')

print('All imports OK!')