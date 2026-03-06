import os
import glob

def replace_in_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replacing simple string replacements
    replacements = {
        '"endpoint_v4": "sd_mcast"': '"endpoint_v4": "sd_mcast"',
        '"endpoint_v4": "sd_multicast"': '"endpoint_v4": "sd_multicast"',
        '"endpoint_v4": "sd-mcast"': '"endpoint_v4": "sd-mcast"',
        '"endpoint_v4": "ep1"': '"endpoint_v4": "ep1"',
        '"endpoint_v4": "ep2"': '"endpoint_v4": "ep2"',
        '"endpoint_v4": "unicast-ep-v4"': '"endpoint_v4": "unicast-ep-v4"',
        '"endpoint_v6": "unicast-ep-v6"': '"endpoint_v6": "unicast-ep-v6"',
        '"endpoint_v4": "main_udp"': '"endpoint_v4": "main_udp"',
        '"endpoint_v4": "main_tcp"': '"endpoint_v4": "main_tcp"'
    }

    new_content = content
    for old, new in replacements.items():
        new_content = new_content.replace(old, new)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for f in glob.glob('tests/*.py'):
    replace_in_file(f)
