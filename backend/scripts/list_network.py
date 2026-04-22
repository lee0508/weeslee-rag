# -*- coding: utf-8 -*-
"""List network share contents"""
import os
import sys

# Network path
network_path = r"\\diskstation\W2_프로젝트폴더"

try:
    if os.path.exists(network_path):
        items = os.listdir(network_path)
        print(f"Found {len(items)} items in {network_path}:")
        print("-" * 50)
        for item in items[:30]:  # Show first 30
            full_path = os.path.join(network_path, item)
            if os.path.isdir(full_path):
                print(f"[DIR]  {item}")
            else:
                print(f"[FILE] {item}")
    else:
        print(f"Path not found: {network_path}")
except Exception as e:
    print(f"Error: {e}")
