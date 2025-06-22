import asyncio
import subprocess
import sys
import os
import signal
import logging
from typing import Dict, Optional, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('process_manager')

class ProcessManager:
    """
    A utility class to manage external processes like FFmpeg
    """
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        self.process_logs: Dict[str, List[str]] = {}
        self.max_log_lines = 100
    
    def start_process(self, process_id: str, command: List[str], 
                     shell: bool = False, cwd: Optional[str] = None) -> Tuple[bool, str]:
        """
        Start a new process with the given command
        
        Args:
            process_id: Unique identifier for the process
            command: Command to execute as a list of strings
            shell: Whether to run the command in a shell
            cwd: Working directory for the process
            
        Returns:
            Tuple of (success, message)
        """
        if process_id in self.processes and self.processes[process_id].poll() is None:
            return False, f"Process {process_id} is already running"
        
        try:
            logger.info(f"Starting process {process_id}: {' '.join(command)}")
            
            # Initialize log for this process
            self.process_logs[process_id] = []
            
            # Start the process
            process = subprocess.Popen(
                command,
                shell=shell,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self.processes[process_id] = process
            
            # Start log collection in background
            asyncio.create_task(self._collect_output(process_id, process))
            
            return True, f"Process {process_id} started with PID {process.pid}"
        except Exception as e:
            logger.error(f"Error starting process {process_id}: {e}")
            return False, f"Error starting process: {str(e)}"
    
    async def _collect_output(self, process_id: str, process: subprocess.Popen):
        """Collect and store process output"""
        try:
            while process.poll() is None:
                if process.stdout:
                    line = process.stdout.readline()
                    if line:
                        # Add to log with max size limit
                        self.process_logs[process_id].append(line.strip())
                        if len(self.process_logs[process_id]) > self.max_log_lines:
                            self.process_logs[process_id].pop(0)
                        logger.debug(f"[{process_id}] {line.strip()}")
                await asyncio.sleep(0.1)
            
            # Process has ended, collect any remaining output
            if process.stdout:
                for line in process.stdout:
                    self.process_logs[process_id].append(line.strip())
                    if len(self.process_logs[process_id]) > self.max_log_lines:
                        self.process_logs[process_id].pop(0)
                    logger.debug(f"[{process_id}] {line.strip()}")
            
            logger.info(f"Process {process_id} ended with return code {process.returncode}")
        except Exception as e:
            logger.error(f"Error collecting output for process {process_id}: {e}")
    
    def stop_process(self, process_id: str) -> Tuple[bool, str]:
        """
        Stop a running process
        
        Args:
            process_id: Identifier of the process to stop
            
        Returns:
            Tuple of (success, message)
        """
        if process_id not in self.processes:
            return False, f"Process {process_id} not found"
        
        process = self.processes[process_id]
        if process.poll() is not None:
            return True, f"Process {process_id} already stopped"
        
        try:
            logger.info(f"Stopping process {process_id}")
            
            # Try graceful termination first
            if sys.platform == 'win32':
                # Windows
                process.terminate()
            else:
                # Unix-like
                os.kill(process.pid, signal.SIGTERM)
            
            # Wait a bit for graceful shutdown
            for _ in range(10):
                if process.poll() is not None:
                    return True, f"Process {process_id} stopped gracefully"
                asyncio.sleep(0.1)
            
            # Force kill if still running
            if process.poll() is None:
                if sys.platform == 'win32':
                    process.kill()
                else:
                    os.kill(process.pid, signal.SIGKILL)
                
                return True, f"Process {process_id} forcefully terminated"
            
            return True, f"Process {process_id} stopped"
        except Exception as e:
            logger.error(f"Error stopping process {process_id}: {e}")
            return False, f"Error stopping process: {str(e)}"
    
    def get_process_status(self, process_id: str) -> Tuple[bool, Dict]:
        """
        Get status information about a process
        
        Args:
            process_id: Identifier of the process
            
        Returns:
            Tuple of (success, status_dict)
        """
        if process_id not in self.processes:
            return False, {"error": f"Process {process_id} not found"}
        
        process = self.processes[process_id]
        return_code = process.poll()
        
        status = {
            "id": process_id,
            "pid": process.pid,
            "running": return_code is None,
            "return_code": return_code,
            "recent_logs": self.process_logs.get(process_id, [])[-10:]  # Last 10 log lines
        }
        
        return True, status
    
    def list_processes(self) -> List[Dict]:
        """
        List all managed processes and their status
        
        Returns:
            List of process status dictionaries
        """
        result = []
        for process_id in self.processes:
            success, status = self.get_process_status(process_id)
            if success:
                result.append(status)
        
        return result
    
    def cleanup(self):
        """Stop all running processes"""
        for process_id in list(self.processes.keys()):
            self.stop_process(process_id)

# Singleton instance
_instance = None

def get_manager() -> ProcessManager:
    """Get the singleton ProcessManager instance"""
    global _instance
    if _instance is None:
        _instance = ProcessManager()
    return _instance
