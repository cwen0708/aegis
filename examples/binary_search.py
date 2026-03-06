def binary_search(arr, target):
    """
    Performs binary search on a sorted array to find the target.

    Args:
        arr (list): A sorted list of numbers.
        target: The value to search for.

    Returns:
        int: The index of the target if found, otherwise -1.
    """
    low = 0
    high = len(arr) - 1

    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1

if __name__ == "__main__":
    # Test cases
    print("Running binary search tests...")

    # Test case 1: Target found in the middle
    arr1 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    target1 = 5
    expected1 = 4
    result1 = binary_search(arr1, target1)
    assert result1 == expected1, f"Test Case 1 Failed: Expected {expected1}, Got {result1}"
    print(f"Test Case 1 Passed: arr={arr1}, target={target1}, result={result1}")

    # Test case 2: Target found at the beginning
    arr2 = [10, 20, 30, 40, 50]
    target2 = 10
    expected2 = 0
    result2 = binary_search(arr2, target2)
    assert result2 == expected2, f"Test Case 2 Failed: Expected {expected2}, Got {result2}"
    print(f"Test Case 2 Passed: arr={arr2}, target={target2}, result={result2}")

    # Test case 3: Target found at the end
    arr3 = [10, 20, 30, 40, 50]
    target3 = 50
    expected3 = 4
    result3 = binary_search(arr3, target3)
    assert result3 == expected3, f"Test Case 3 Failed: Expected {expected3}, Got {result3}"
    print(f"Test Case 3 Passed: arr={arr3}, target={target3}, result={result3}")

    # Test case 4: Target not found
    arr4 = [1, 3, 5, 7, 9]
    target4 = 6
    expected4 = -1
    result4 = binary_search(arr4, target4)
    assert result4 == expected4, f"Test Case 4 Failed: Expected {expected4}, Got {result4}"
    print(f"Test Case 4 Passed: arr={arr4}, target={target4}, result={result4}")

    # Test case 5: Empty array
    arr5 = []
    target5 = 1
    expected5 = -1
    result5 = binary_search(arr5, target5)
    assert result5 == expected5, f"Test Case 5 Failed: Expected {expected5}, Got {result5}"
    print(f"Test Case 5 Passed: arr={arr5}, target={target5}, result={result5}")

    # Test case 6: Single element array, target found
    arr6 = [7]
    target6 = 7
    expected6 = 0
    result6 = binary_search(arr6, target6)
    assert result6 == expected6, f"Test Case 6 Failed: Expected {expected6}, Got {result6}"
    print(f"Test Case 6 Passed: arr={arr6}, target={target6}, result={result6}")

    # Test case 7: Single element array, target not found
    arr7 = [7]
    target7 = 5
    expected7 = -1
    result7 = binary_search(arr7, target7)
    assert result7 == expected7, f"Test Case 7 Failed: Expected {expected7}, Got {result7}"
    print(f"Test Case 7 Passed: arr={arr7}, target={target7}, result={result7}")

    print("All binary search tests passed!")