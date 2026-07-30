with open("app/main.py", "r") as f:
    content = f.read()

# Replace endpoint string or rewrite function directly
if "latest_version" in content:
    lines = content.splitlines()
    new_lines = []
    for line in lines:
        if '"latest_version":' in line:
            new_lines.append('        "latest_version": "1.0.2",')
        elif '"build_number":' in line:
            new_lines.append('        "build_number": 2,')
        else:
            new_lines.append(line)
    content = "\n".join(new_lines)

with open("app/main.py", "w") as f:
    f.write(content)

print("Main.py modified successfully!")
