import os
import sys
import shutil
import subprocess

def run(cmd):
    subprocess.run(cmd, shell=True)

def kill_node_py():
    # Kill node.exe
    run("taskkill /F /IM node.exe")
    # Kill python.exe
    run("taskkill /F /IM python.exe")
    print("Killed node and python processes")

def remove_standalone(path):
    try:
        shutil.rmtree(path)
        print("Removed .next/standalone")
    except Exception as e:
        print(f"Failed to remove: {e}")

if __name__ == "__main__":
    kill_node_py()
    remove_standalone(".next/standalone")
    print("Cleanup done")
