#!/usr/bin/env python
"""
Coverage Example - Demonstrates how test coverage works
This file shows what happens when you run tests with coverage.
"""

def calculate_invoice_total(lessons, tax_rate=0.1):
    """
    Calculate total invoice amount with tax.
    
    Args:
        lessons: List of lesson dictionaries with 'cost' key
        tax_rate: Tax rate as decimal (0.1 = 10%)
    
    Returns:
        Total amount including tax
    """
    if not lessons:  # Line 1: No lessons
        return 0.0   # Line 2: Return 0
    
    subtotal = 0.0   # Line 3: Initialize subtotal
    
    for lesson in lessons:  # Line 4: Loop through lessons
        if 'cost' in lesson:  # Line 5: Check if cost exists
            subtotal += lesson['cost']  # Line 6: Add cost
        else:  # Line 7: No cost field
            raise ValueError("Lesson missing cost field")  # Line 8: Error
    
    if subtotal < 0:  # Line 9: Negative subtotal
        return 0.0    # Line 10: Return 0 for negative
    
    tax = subtotal * tax_rate  # Line 11: Calculate tax
    total = subtotal + tax     # Line 12: Add tax to subtotal
    
    return total  # Line 13: Return total


# Example test scenarios and their coverage:

def test_scenario_1():
    """Test with valid lessons - covers most lines"""
    lessons = [
        {'cost': 100.0},
        {'cost': 50.0}
    ]
    result = calculate_invoice_total(lessons, 0.1)
    # This covers: Lines 1, 3, 4, 5, 6, 9, 11, 12, 13
    # Missing: Lines 2, 7, 8, 10
    return result == 165.0  # (100 + 50) * 1.1


def test_scenario_2():
    """Test with empty lessons - covers line 2"""
    lessons = []
    result = calculate_invoice_total(lessons)
    # This covers: Lines 1, 2
    # Missing: Lines 3-13
    return result == 0.0


def test_scenario_3():
    """Test with missing cost field - covers error path"""
    lessons = [{'name': 'Piano lesson'}]  # No 'cost' field
    try:
        calculate_invoice_total(lessons)
        return False  # Should have raised error
    except ValueError:
        # This covers: Lines 1, 3, 4, 5, 7, 8
        # Missing: Lines 2, 6, 9, 10, 11, 12, 13
        return True


def test_scenario_4():
    """Test with negative subtotal - covers line 10"""
    lessons = [{'cost': -100.0}]
    result = calculate_invoice_total(lessons)
    # This covers: Lines 1, 3, 4, 5, 6, 9, 10
    # Missing: Lines 2, 7, 8, 11, 12, 13
    return result == 0.0


# Coverage Analysis:
"""
If you run ALL test scenarios, you get 100% coverage:
- Lines 1-13 are all executed

If you only run test_scenario_1, you get ~70% coverage:
- Covered: 1, 3, 4, 5, 6, 9, 11, 12, 13
- Missing: 2, 7, 8, 10

This shows you need more tests to cover edge cases!
"""

if __name__ == '__main__':
    print("Coverage Example - Invoice Calculation")
    print("=" * 50)
    
    print("Test 1 (valid lessons):", test_scenario_1())
    print("Test 2 (empty lessons):", test_scenario_2())
    print("Test 3 (missing cost):", test_scenario_3())
    print("Test 4 (negative cost):", test_scenario_4())
    
    print("\nCoverage shows which lines are tested:")
    print("- High coverage = most code paths tested")
    print("- Low coverage = missing edge cases")
    print("- 100% coverage = all code paths tested")
