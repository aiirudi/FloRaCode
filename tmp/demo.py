# -*- coding: utf-8 -*-
"""快速排序（Quick Sort）示例。

快速排序是一种基于分治思想的排序算法：
1. 从数组中选择一个基准值（pivot）；
2. 通过一趟划分（partition），将数组分为两部分：
   - 左边部分都小于等于基准值；
   - 右边部分都大于基准值；
3. 对左右两部分递归执行上述步骤，直到子数组长度为 0 或 1。

平均时间复杂度：O(n log n)
最坏时间复杂度：O(n^2)（例如每次划分都极不平衡时）
空间复杂度：O(log n)（递归栈深度）
稳定性：不稳定
"""

from typing import List, Optional, TypeVar

T = TypeVar("T")


def partition(arr: List[T], low: int, high: int) -> int:
    """对 arr[low..high] 进行一次划分，返回基准值的最终位置。

    采用 Lomuto 划分方案：选择最右侧元素作为基准值。
    """
    pivot = arr[high]      # 基准值
    i = low - 1            # i 指向「小于等于 pivot 区域」的最后一个元素

    for j in range(low, high):
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]

    # 将基准值放到正确位置
    arr[i + 1], arr[high] = arr[high], arr[i + 1]
    return i + 1


def quick_sort(arr: List[T], low: int = 0, high: Optional[int] = None) -> None:
    """对数组 arr 在 [low, high] 区间内进行原地快速排序。"""
    if high is None:
        high = len(arr) - 1

    if low < high:
        pivot_index = partition(arr, low, high)
        quick_sort(arr, low, pivot_index - 1)
        quick_sort(arr, pivot_index + 1, high)


if __name__ == "__main__":
    test_cases = [
        [3, 6, 8, 10, 1, 2, 1],
        [5, 2, 9, 1, 7, 6, 3],
        [],
        [42],
        [4, 4, 4, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1],
    ]

    for data in test_cases:
        arr = data[:]  # 复制一份，避免破坏原列表
        quick_sort(arr)
        print(f"{data} -> {arr}")
