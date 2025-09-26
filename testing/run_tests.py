#!/usr/bin/env python
"""
Test Runner Script for Maple Key Music Academy Billing API
Run this script to execute all billing tests and see results.
"""

import os
import sys
import django
from django.conf import settings
from django.test.utils import get_runner

def setup_django():
    """Setup Django environment for testing"""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maple_key_backend.settings')
    django.setup()

def run_tests():
    """Run the billing tests"""
    setup_django()
    
    # Get test runner
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    
    # Run tests
    failures = test_runner.run_tests(['billing.tests'])
    
    if failures:
        print(f"\n❌ {failures} test(s) failed!")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")

if __name__ == '__main__':
    print("🧪 Running Maple Key Music Academy Billing Tests...")
    print("=" * 60)
    run_tests()
