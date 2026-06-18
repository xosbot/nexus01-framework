import asyncio
import subprocess

BLOCKED = ["rm -rf /", "chmod 777", "mkfs", "> /dev/sda", ":(){ :|:& };:", "dd if=", "wget|sh"]

async def run_command(cmd: str, timeout: int = 30) -> dict:
    if any(b in cmd for b in BLOCKED):
        return {"error": "Command blocked for safety", "exit_code": -1}
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "exit_code": proc.returncode,
        }
    except asyncio.TimeoutError:
        return {"error": f"Command timed out after {timeout}s", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}
