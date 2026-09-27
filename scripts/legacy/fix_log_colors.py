import re

with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/ui/views/main_window.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the _log method - replace tuple colors with single color strings
old_log = '''        # Configure tags
        self.log_textbox.tag_config("info", foreground=("gray30", "gray70"))
        self.log_textbox.tag_config("success", foreground=("green", "lightgreen"))
        self.log_textbox.tag_config("warning", foreground=("orange", "gold"))
        self.log_textbox.tag_config("error", foreground=("red", "lightcoral"))'''

new_log = '''        # Configure tags - use single color strings that work in both light/dark modes
        self.log_textbox.tag_config("info", foreground="gray")
        self.log_textbox.tag_config("success", foreground="green")
        self.log_textbox.tag_config("warning", foreground="orange")
        self.log_textbox.tag_config("error", foreground="red")'''

content = content.replace(old_log, new_log)

with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/ui/views/main_window.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed _log method color tags')