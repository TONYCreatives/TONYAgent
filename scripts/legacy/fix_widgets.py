with open('c:\\Users\\iig2y\\Desktop\\TONYAgent\\src\\tonyagent\\ui\\widgets\\__init__.py', 'r') as f:
    lines = f.readlines()

# Find and remove the extra ')'
for i, line in enumerate(lines):
    if line.strip() == ')' and i+1 < len(lines) and lines[i+1].strip() == '' and i+2 < len(lines) and 'class PillSegmentedButton' in lines[i+2]:
        lines[i] = ''
        break

with open('c:\\Users\\iig2y\\Desktop\\TONYAgent\\src\\tonyagent\\ui\\widgets\\__init__.py', 'w') as f:
    f.writelines(lines)

print('Fixed')