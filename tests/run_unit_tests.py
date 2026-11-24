#!/usr/bin/env python3
"""
Unit Test Runner for FinSyntra RAG Pipeline Improvements
Runs all unit tests for the new modules
"""
import sys
import os
import subprocess
import pytest
from pathlib import Path

# Add the src directory to the Python path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

def run_tests():
    """Run all unit tests"""
    print("🧪 Running FinSyntra RAG Pipeline Unit Tests")
    print("=" * 60)
    
    # Get the tests directory
    tests_dir = Path(__file__).parent
    unit_tests_dir = tests_dir / "unit"
    
    if not unit_tests_dir.exists():
        print(f"❌ Unit tests directory not found: {unit_tests_dir}")
        return False
    
    # Find all test files
    test_files = list(unit_tests_dir.glob("test_*.py"))
    
    if not test_files:
        print(f"❌ No test files found in {unit_tests_dir}")
        return False
    
    print(f"📁 Found {len(test_files)} test files:")
    for test_file in test_files:
        print(f"   • {test_file.name}")
    
    print("\n🚀 Starting test execution...")
    print("-" * 60)
    
    # Run tests with pytest
    try:
        # Change to the project root directory
        project_root = Path(__file__).parent.parent
        os.chdir(project_root)
        
        # Run pytest with verbose output
        result = pytest.main([
            str(unit_tests_dir),
            "-v",
            "--tb=short",
            "--strict-markers",
            "--disable-warnings"
        ])
        
        if result == 0:
            print("\n✅ All tests passed!")
            return True
        else:
            print(f"\n❌ Tests failed with exit code: {result}")
            return False
            
    except Exception as e:
        print(f"\n💥 Error running tests: {e}")
        return False

def run_specific_test(test_name):
    """Run a specific test file"""
    print(f"🧪 Running specific test: {test_name}")
    print("=" * 60)
    
    tests_dir = Path(__file__).parent
    test_file = tests_dir / "unit" / f"test_{test_name}.py"
    
    if not test_file.exists():
        print(f"❌ Test file not found: {test_file}")
        return False
    
    try:
        # Change to the project root directory
        project_root = Path(__file__).parent.parent
        os.chdir(project_root)
        
        # Run specific test
        result = pytest.main([
            str(test_file),
            "-v",
            "--tb=short",
            "--strict-markers",
            "--disable-warnings"
        ])
        
        if result == 0:
            print(f"\n✅ Test {test_name} passed!")
            return True
        else:
            print(f"\n❌ Test {test_name} failed with exit code: {result}")
            return False
            
    except Exception as e:
        print(f"\n💥 Error running test {test_name}: {e}")
        return False

def list_available_tests():
    """List all available test files"""
    tests_dir = Path(__file__).parent
    unit_tests_dir = tests_dir / "unit"
    
    if not unit_tests_dir.exists():
        print("❌ Unit tests directory not found")
        return
    
    test_files = list(unit_tests_dir.glob("test_*.py"))
    
    if not test_files:
        print("❌ No test files found")
        return
    
    print("📋 Available test files:")
    for test_file in test_files:
        test_name = test_file.stem.replace("test_", "")
        print(f"   • {test_name}")
    
    print("\n💡 To run a specific test, use:")
    print("   python tests/run_unit_tests.py <test_name>")
    print("   Example: python tests/run_unit_tests.py memory")

def main():
    """Main function"""
    if len(sys.argv) > 1:
        if sys.argv[1] == "list":
            list_available_tests()
        elif sys.argv[1] == "help":
            print("🧪 FinSyntra RAG Pipeline Unit Test Runner")
            print("=" * 50)
            print("\nUsage:")
            print("  python tests/run_unit_tests.py           # Run all tests")
            print("  python tests/run_unit_tests.py <name>    # Run specific test")
            print("  python tests/run_unit_tests.py list      # List available tests")
            print("  python tests/run_unit_tests.py help      # Show this help")
            print("\nAvailable test modules:")
            print("  • memory        - Session memory and key-value store")
            print("  • query_rewriter - Query rewriting and pronoun resolution")
            print("  • entity_registry - Entity canonicalization and registry")
            print("  • policy        - Policy engine and RBAC enforcement")
            print("  • grounding_validator - Factual claim validation")
            print("  • table_retriever - Structured data retrieval")
            print("  • answer_consistency - Answer consistency checking")
            print("  • audit_log     - Audit logging and compliance")
            print("  • hr_card       - HR data formatting and display")
        else:
            test_name = sys.argv[1]
            success = run_specific_test(test_name)
            sys.exit(0 if success else 1)
    else:
        success = run_tests()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()

