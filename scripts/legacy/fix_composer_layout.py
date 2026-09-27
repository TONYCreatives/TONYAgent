import re

with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/ui/views/main_window.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the composer layout - the btn_frame needs proper column configuration
# Find the composer frame creation and fix the button layout
old_composer = '''        # Send/Stop buttons
        btn_frame = PillFrame(self.composer_frame, fg_color="transparent", height=40)
        btn_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        btn_frame.grid_columnconfigure(0, weight=1)

        self.stop_btn = DangerPillButton(
            btn_frame,
            text="Stop",
            width=100,
            command=self._on_stop,
        )
        self.stop_btn.grid(row=0, column=1, padx=4)
        self.stop_btn.grid_remove()  # Hidden by default

        self.send_btn = PrimaryPillButton(
            btn_frame,
            text="Send",
            width=100,
            command=self._on_send,
        )
        self.send_btn.grid(row=0, column=2, padx=4)

        # Token count label
        self.token_label = PillLabel(
            btn_frame,
            text="Tokens: 0",
            font=("Segoe UI", 11),
            text_color=("gray50", "gray60"),
        )
        self.token_label.grid(row=0, column=0, sticky="w", padx=12)'''

new_composer = '''        # Send/Stop buttons
        btn_frame = PillFrame(self.composer_frame, fg_color="transparent", height=40)
        btn_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        # Configure columns: 0=token label (left), 1=spacer (expand), 2=stop, 3=send
        btn_frame.grid_columnconfigure(0, weight=0)
        btn_frame.grid_columnconfigure(1, weight=1)  # Spacer expands to push buttons right
        btn_frame.grid_columnconfigure(2, weight=0)
        btn_frame.grid_columnconfigure(3, weight=0)

        # Token count label (left side)
        self.token_label = PillLabel(
            btn_frame,
            text="Tokens: 0",
            font=("Segoe UI", 11),
            text_color=("gray50", "gray60"),
        )
        self.token_label.grid(row=0, column=0, sticky="w", padx=12)

        self.stop_btn = DangerPillButton(
            btn_frame,
            text="Stop",
            width=100,
            command=self._on_stop,
        )
        self.stop_btn.grid(row=0, column=2, padx=4)
        self.stop_btn.grid_remove()  # Hidden by default

        self.send_btn = PrimaryPillButton(
            btn_frame,
            text="Send",
            width=100,
            command=self._on_send,
        )
        self.send_btn.grid(row=0, column=3, padx=4)'''

content = content.replace(old_composer, new_composer)

with open('c:/Users/iig2y/Desktop/TONYAgent/src/tonyagent/ui/views/main_window.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed composer layout')