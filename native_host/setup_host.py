import winreg
import os
import json

# 1. Define the names based on your team's contract
HOST_NAME = "com.lpbd.native.host"
# Get the absolute path of the current directory where this script is saved
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

def create_registry_key(manifest_path):
    """Creates the Windows Registry key pointing to your host manifest."""
    try:
        # Path: HKEY_CURRENT_USER\Software\Google\Chrome\NativeMessagingHosts\com.lpbd.native.host
        key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
        
        # Create/Open the key
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        
        # Set the (Default) value to the full path of your JSON manifest
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest_path)
        winreg.CloseKey(key)
        
        print(f"Successfully registered {HOST_NAME} in Windows Registry.")
        print(f"Pointing to: {manifest_path}")
    except Exception as e:
        print(f"Error creating registry key: {e}")

if __name__ == "__main__":
    # Ensure the script looks for the manifest in the same folder
    manifest_file = os.path.join(CURRENT_DIR, f"{HOST_NAME}.json")
    
    if os.path.exists(manifest_file):
        create_registry_key(manifest_file)
    else:
        print(f"Error: Could not find {manifest_file} in this folder.")
        print("Make sure your JSON manifest and this script are in the same directory.")