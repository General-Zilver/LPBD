import winreg
import os
import json

# The host name string defined in your team contract
HOST_NAME = "com.lpbd.native.host"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

def update_manifest_file():
    """
    Rewrites the JSON manifest to use the absolute path of this 
    computer's specific folder structure.
    """
    manifest_file = os.path.join(CURRENT_DIR, f"{HOST_NAME}.json")
    # Dynamically find the path to the batch wrapper
    bat_path = os.path.join(CURRENT_DIR, "run_host.bat")
    
    if not os.path.exists(manifest_file):
        print(f"Error: {manifest_file} not found. Ensure it's in this folder.")
        return None

    with open(manifest_file, 'r') as f:
        data = json.load(f)

    # Inject the local absolute path for this user
    data["path"] = bat_path

    print(f"Current Extension ID in manifest: {data['allowed_origins'][0]}")
    new_id = input("Enter the Extension ID from chrome://extensions (or press Enter to keep current): ").strip()
    
    if new_id:
        # Ensure it has the proper chrome-extension:// prefix
        if not new_id.startswith("chrome-extension://"):
            new_id = f"chrome-extension://{new_id}/"
        data["allowed_origins"] = [new_id]

    with open(manifest_file, 'w') as f:
        json.dump(data, f, indent=4)
    
    return manifest_file

def register_host(manifest_path):
    """Creates the Windows Registry key for Chrome to find the host."""
    try:
        key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest_path)
        winreg.CloseKey(key)
        print(f"Successfully registered {HOST_NAME} in Windows Registry.")
    except Exception as e:
        print(f"Error creating registry key: {e}")

if __name__ == "__main__":
    # 1. Update the JSON file with the current folder's path
    m_path = update_manifest_file()
    
    # 2. Register it so Chrome knows where to look
    if m_path:
        register_host(m_path)
        print(f"Setup complete! Your local path is now mapped.")