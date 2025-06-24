import subprocess
import shlex
import os
from typing import Optional, Dict, List, Union, Any, Set

# Whitelist of allowed commands for security
ALLOWED_COMMANDS: Set[str] = {
    # Basic file and directory operations
    "ls", "grep", "find", "cat", "head", "tail", "wc",
    # Search tools
    "grep", "rg", "ack", "ag",
    # File manipulation
    "cp", "mv", "rm", "mkdir", "touch", "chmod", "chown",
    # Archive tools
    "tar", "gzip", "gunzip", "zip", "unzip",
    # Text processing
    "sed", "awk", "cut", "sort", "uniq", "tr", "diff", "patch",
    # Network tools
    "curl", "wget", "ping", "netstat", "ssh", "scp",
    # System information
    "ps", "top", "df", "du", "free", "uname", "whoami", "date",
    # Development tools
    "git", "npm", "pip", "python", "node", "java", "javac", "gcc", "make",
    # Package managers
    "apt", "apt-get", "yum", "brew", "conda",
    # Jupyter specific
    "jupyter", "ipython", "nbconvert"
}

class CommandNotAllowedError(Exception):
    """Exception raised when a command is not in the whitelist."""
    pass


def bash(command: str, description: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    """Runs a bash command and returns the result
    
    Parameters
    ----------
    command : str
        The bash command to execute
    description : str
        A description of what the command does (for logging purposes)
    timeout : Optional[int], optional
        Timeout in seconds for the command execution, by default None
        
    Returns
    -------
    Dict[str, Any]
        A dictionary containing:
        - stdout: The standard output as a string
        - stderr: The standard error as a string
        - returncode: The return code of the command
    
    Raises
    ------
    CommandNotAllowedError
        If the command is not in the whitelist of allowed commands
    subprocess.TimeoutExpired
        If the command execution times out
    """
    try:
        # Split the command into arguments if it's not already a list
        if isinstance(command, str):
            args = shlex.split(command)
        else:
            args = command
        
        # Check if the command is in the whitelist
        if not args or args[0] not in ALLOWED_COMMANDS:
            raise CommandNotAllowedError(
                f"Command '{args[0] if args else ''}' is not in the whitelist of allowed commands. "
                f"Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}"
            )
            
        # Execute the command
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False
        )
        
        # Wait for the command to complete with timeout if specified
        stdout, stderr = process.communicate(timeout=timeout)
        
        # Return the result
        return {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": process.returncode
        }
    except subprocess.TimeoutExpired:
        # Kill the process if it times out
        process.kill()
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=timeout,
            output=stdout,
            stderr=stderr
        )

def glob(pattern: str, path: str = ".") -> List[str]:
    """Runs the unix glob command and returns the result
    
    Parameters
    ----------
    pattern : str
        The glob pattern to match (e.g., "*.py", "**/*.md")
    path : str, optional
        The base path to search from, by default "."
        
    Returns
    -------
    List[str]
        A list of file paths matching the pattern
    """
    import glob as glob_module
    import os
    
    # Join the path and pattern if path is provided
    search_pattern = os.path.join(path, pattern)
    
    # Use recursive glob if the pattern contains **
    if "**" in pattern:
        return glob_module.glob(search_pattern, recursive=True)
    else:
        return glob_module.glob(search_pattern)

def grep(pattern: str, path: str, include: Optional[str] = None) -> Dict[str, Any]:
    """Runs the unix grep command and returns the result
    
    Parameters
    ----------
    pattern : str
        The pattern to search for
    path : str
        The path to search in (file or directory)
    include : Optional[str], optional
        File pattern to include in the search (e.g., "*.py"), by default None
        
    Returns
    -------
    Dict[str, Any]
        A dictionary containing:
        - stdout: The standard output as a string
        - stderr: The standard error as a string
        - returncode: The return code of the command
        - matches: A parsed list of matches (if returncode is 0)
    """
    import shutil
    import json
    
    # Check if ripgrep is available (preferred for performance)
    use_ripgrep = shutil.which("rg") is not None
    
    if use_ripgrep:
        # Construct ripgrep command
        cmd = ["rg", "--json", pattern]
        
        # Add include pattern if specified
        if include:
            cmd.extend(["--glob", include])
            
        # Add path
        cmd.append(path)
        
        # Execute the command
        result = bash(cmd, f"Searching for '{pattern}' in {path} using ripgrep", None)
        
        # Parse the JSON output if successful
        if result["returncode"] == 0 and result["stdout"]:
            matches = []
            for line in result["stdout"].strip().split("\n"):
                try:
                    match_data = json.loads(line)
                    if match_data.get("type") == "match":
                        matches.append({
                            "path": match_data.get("data", {}).get("path", {}).get("text", ""),
                            "line_number": match_data.get("data", {}).get("line_number", 0),
                            "line": match_data.get("data", {}).get("lines", {}).get("text", "").strip()
                        })
                except json.JSONDecodeError:
                    pass
            
            result["matches"] = matches
    else:
        # Fallback to standard grep
        cmd = ["grep", "-r", "--line-number"]
        
        # Add include pattern if specified
        if include:
            cmd.extend(["--include", include])
            
        # Add pattern and path
        cmd.extend([pattern, path])
        
        # Execute the command
        result = bash(cmd, f"Searching for '{pattern}' in {path} using grep", None)
        
        # Parse the output if successful
        if result["returncode"] == 0 and result["stdout"]:
            matches = []
            for line in result["stdout"].strip().split("\n"):
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    matches.append({
                        "path": parts[0],
                        "line_number": int(parts[1]),
                        "line": parts[2].strip()
                    })
            
            result["matches"] = matches
        elif result["returncode"] == 1:
            # grep returns 1 when no matches are found (not an error)
            result["matches"] = []
    
    return result

def ls(path: str = ".", ignore: Optional[List[str]] = None) -> Dict[str, Any]:
    """Runs the unix ls command and returns the result
    
    Parameters
    ----------
    path : str, optional
        The path to list contents for, by default "."
    ignore : Optional[List[str]], optional
        List of patterns to ignore, by default None
        
    Returns
    -------
    Dict[str, Any]
        A dictionary containing:
        - stdout: The standard output as a string
        - stderr: The standard error as a string
        - returncode: The return code of the command
        - entries: A parsed list of directory entries (if returncode is 0)
    """
    import os
    import fnmatch
    
    # Default to empty list if ignore is None
    ignore = ignore or []
    
    # Construct ls command with long format
    cmd = ["ls", "-la"]
    
    # Add path
    cmd.append(path)
    
    # Execute the command
    result = bash(cmd, f"Listing contents of {path}", None)
    
    # Parse the output if successful
    if result["returncode"] == 0 and result["stdout"]:
        entries = []
        lines = result["stdout"].strip().split("\n")
        
        # Skip the total line and parse each entry
        for line in lines[1:]:  # Skip the "total X" line
            parts = line.split(None, 8)
            if len(parts) >= 9:
                name = parts[8]
                
                # Skip if the entry matches any ignore pattern
                if any(fnmatch.fnmatch(name, pattern) for pattern in ignore):
                    continue
                
                # Determine if it's a directory from the first character of permissions
                is_dir = parts[0].startswith("d")
                
                entry = {
                    "name": name,
                    "type": "directory" if is_dir else "file",
                    "permissions": parts[0],
                    "links": int(parts[1]),
                    "owner": parts[2],
                    "group": parts[3],
                    "size": int(parts[4]),
                    "modified": f"{parts[5]} {parts[6]} {parts[7]}"
                }
                
                # Add full path
                entry["path"] = os.path.join(path, name)
                
                entries.append(entry)
        
        result["entries"] = entries
    
    return result
