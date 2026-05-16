#!/usr/bin/env python3
"""Run tests for the social media automation project."""
import subprocess
import sys
from pathlib import Path

def run_tests():
    """Run all tests and return the result."""
    project_dir = Path(__file__).parent
    print(f"Running tests in {project_dir}")
    
    # Run pytest
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v"],
        cwd=project_dir,
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    print("\nSTDERR:")
    print(result.stderr)
    print(f"\nReturn code: {result.returncode}")
    
    return result.returncode == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)