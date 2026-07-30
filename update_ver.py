with open("app/main.py", "r") as f:
    code = f.read()

code = code.replace('"latest_version": "1.0.1"', '"latest_version": "1.0.2"')
code = code.replace('"build_number": 1', '"build_number": 2')
code = code.replace('"build_number": 2', '"build_number": 2')

with open("app/main.py", "w") as f:
    f.write(code)
