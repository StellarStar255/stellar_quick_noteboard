import os
import re
import base64
import sys
try:
    import pyperclip
except ImportError:
    pyperclip = None

def unpack_markdown_to_repo(markdown_file="packed_repo.md", output_path=".", force=False):
    content = None
    if not os.path.exists(markdown_file):
        print(f"Info: The file {markdown_file} was not found.")
        if pyperclip:
            try:
                content = pyperclip.paste()
                if content:
                    print("Info: Found content in clipboard. Using it to unpack.")
                else:
                    print("Error: Clipboard is empty.")
                    return
            except Exception as e:
                print(f"Error reading from clipboard: {e}")
                return
        else:
            print("Error: pyperclip not installed. Please install it to use clipboard functionality: pip install pyperclip")
            return
    else:
        try:
            with open(markdown_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {markdown_file}: {e}")
            return

    if not content:
        print("Error: No content to unpack.")
        return

    # Check if the output directory exists and is not empty
    if not force and os.path.exists(output_path):
        ignore_list = [".DS_Store", "unpack.py", "pack.py", "packed_repo.md", ".gitignore", "README.md"]
        files_in_dir = [f for f in os.listdir(output_path) if f not in ignore_list]
        if files_in_dir:
            # List some of the files in the directory
            print(f"The output directory '{output_path}' is not empty. Here are some of the files:")
            for f in files_in_dir[:5]:
                print(f"  - {f}")
            
            # Ask for confirmation
            response = input("Do you want to continue and possibly overwrite files? (y/n): ").lower()
            if response not in ["y", "yes"]:
                print("Unpacking cancelled.")
                return

    # Regex to find file paths, language, and their corresponding code blocks
    file_pattern = re.compile(r"## `(.+?)`\n\n```(.*?)\n(.*?)\n```", re.DOTALL)
    
    matches = file_pattern.findall(content)

    if not matches:
        print("No files were found in the markdown file. Is the format correct?")
        return

    print(f"Found {len(matches)} files to unpack.")

    for file_path_str, language, file_content in matches:
        # Normalize the path to be compatible with the OS
        normalized_path = os.path.join(*file_path_str.replace("\\\\", "/").split("/"))
        full_path = os.path.join(output_path, normalized_path)
        
        try:
            # Create the directory if it doesn't exist
            dir_name = os.path.dirname(full_path)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            # Decode if it's base64 encoded
            if ",base64" in language:
                decoded_content = base64.b64decode(file_content.encode("utf-8"))
                # Try to decode as utf-8 text, if it fails, write as binary
                try:
                    text_content = decoded_content.decode("utf-8")
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(text_content)
                except UnicodeDecodeError:
                    with open(full_path, "wb") as f:
                        f.write(decoded_content)
            else:
                # For backward compatibility or if not encoded
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(file_content)
            
            print(f"  - Created: {full_path}")

        except Exception as e:
            print(f"Error creating file {full_path}: {e}")

    print("\nUnpacking completed.")

if __name__ == "__main__":
    if os.path.exists("SAFE_LOCK"):
        print("SAFE_LOCK file found. Execution cancelled.")
        sys.exit(1)

    force = False
    if "--force" in sys.argv or "-f" in sys.argv:
        force = True
    
    unpack_markdown_to_repo(force=force)
