#!/usr/bin/env python3
"""
Test runner for CallCenterAI Gateway with detailed error reporting.

Runs all test suites and generates comprehensive test reports.
"""
import sys
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add gateway directory to path
gateway_dir = Path(__file__).parent.parent
sys.path.insert(0, str(gateway_dir))

def run_tests() -> Dict[str, Any]:
    """Run all tests and return results."""
    print("=" * 80)
    print("CallCenterAI Gateway Test Suite")
    print("=" * 80)
    print(f"Started at: {datetime.now().isoformat()}\n")
    
    # Run pytest with coverage
    test_dir = Path(__file__).parent
    cmd = [
        sys.executable, "-m", "pytest",
        str(test_dir),
        "-v",  # Verbose output
        "--tb=short",  # Short traceback format
        "--cov=services",  # Coverage for services directory
        "--cov=models",  # Coverage for models directory
        "--cov-report=html:htmlcov",  # HTML coverage report
        "--cov-report=term",  # Terminal coverage report
        "--cov-report=json:coverage.json",  # JSON coverage report
        "--junit-xml=test-results.xml",  # JUnit XML for CI/CD
        "-W", "ignore::DeprecationWarning",  # Ignore deprecation warnings
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=gateway_dir)
        
        # Parse test results
        test_results = {
            "timestamp": datetime.now().isoformat(),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "passed": result.returncode == 0,
            "summary": _parse_test_summary(result.stdout)
        }
        
        # Print results
        print(result.stdout)
        if result.stderr:
            print("\nSTDERR:")
            print(result.stderr)
        
        # Print summary
        print("\n" + "=" * 80)
        print("Test Summary")
        print("=" * 80)
        if test_results["summary"]:
            print(f"Tests passed: {test_results['summary'].get('passed', 0)}")
            print(f"Tests failed: {test_results['summary'].get('failed', 0)}")
            print(f"Tests skipped: {test_results['summary'].get('skipped', 0)}")
        print(f"Exit code: {result.returncode}")
        print("=" * 80)
        
        # Generate HTML report
        if Path(gateway_dir / "htmlcov").exists():
            print(f"\nCoverage report generated: {gateway_dir / 'htmlcov' / 'index.html'}")
        
        # Generate JSON report
        if Path(gateway_dir / "coverage.json").exists():
            print(f"Coverage JSON: {gateway_dir / 'coverage.json'}")
        
        return test_results
        
    except Exception as e:
        print(f"FAILED: Test runner failed: {e}")
        return {
            "timestamp": datetime.now().isoformat(),
            "exit_code": 1,
            "error": str(e),
            "passed": False
        }


def _parse_test_summary(stdout: str) -> Dict[str, int]:
    """Parse test summary from pytest output."""
    summary = {"passed": 0, "failed": 0, "skipped": 0}
    
    # Look for summary line like "5 passed, 2 failed, 1 skipped"
    for line in stdout.split("\n"):
        if "passed" in line.lower() or "failed" in line.lower():
            import re
            passed_match = re.search(r"(\d+)\s+passed", line)
            failed_match = re.search(r"(\d+)\s+failed", line)
            skipped_match = re.search(r"(\d+)\s+skipped", line)
            
            if passed_match:
                summary["passed"] = int(passed_match.group(1))
            if failed_match:
                summary["failed"] = int(failed_match.group(1))
            if skipped_match:
                summary["skipped"] = int(skipped_match.group(1))
    
    return summary


def generate_test_report(test_results: Dict[str, Any]) -> str:
    """Generate HTML test report."""
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>CallCenterAI Gateway Test Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background-color: #4CAF50; color: white; padding: 20px; }}
        .failed {{ background-color: #f44336; color: white; padding: 10px; margin: 10px 0; }}
        .passed {{ background-color: #4CAF50; color: white; padding: 10px; margin: 10px 0; }}
        .summary {{ background-color: #f5f5f5; padding: 20px; margin: 20px 0; }}
        pre {{ background-color: #f5f5f5; padding: 10px; overflow-x: auto; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>CallCenterAI Gateway Test Report</h1>
        <p>Generated: {test_results['timestamp']}</p>
    </div>
    
    <div class="summary">
        <h2>Summary</h2>
        <p>Exit Code: {test_results['exit_code']}</p>
        <p>Status: {'PASSED' if test_results['passed'] else 'FAILED'}</p>
        {f"<p>Tests Passed: {test_results['summary'].get('passed', 0)}</p>" if test_results.get('summary') else ''}
        {f"<p>Tests Failed: {test_results['summary'].get('failed', 0)}</p>" if test_results.get('summary') else ''}
    </div>
    
    <div class="{'passed' if test_results['passed'] else 'failed'}">
        <h2>Test Output</h2>
        <pre>{test_results.get('stdout', 'No output')}</pre>
    </div>
    
    {f"<div><h2>Errors</h2><pre>{test_results.get('stderr', 'No errors')}</pre></div>" if test_results.get('stderr') else ''}
</body>
</html>
"""
    return html


def main():
    """Main entry point."""
    print("Running CallCenterAI Gateway tests...\n")
    
    # Run tests
    results = run_tests()
    
    # Generate HTML report
    html_report = generate_test_report(results)
    report_path = gateway_dir / "test-report.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_report)
    print(f"\nTest report generated: {report_path}")
    
    # Exit with test result code
    sys.exit(results["exit_code"])


if __name__ == "__main__":
    main()

